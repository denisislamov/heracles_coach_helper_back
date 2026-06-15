"""Хендлеры Telegram: онбординг, приём еды (фото/текст/число), меню, настройки."""
import datetime as dt
import logging
import re

import pytz
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import ai
import barcode as barcode_mod
import config
import db
import feedback
import foodfacts
import i18n
from i18n import t
import keyboards as kb
import nutrition
import payments
import reminders
import reports
import version

log = logging.getLogger("calbot.handlers")

# Текст-«число калорий»: «350», «+200», «350 ккал»
_NUM_RE = re.compile(r"^\+?\s*(\d{1,5})\s*(ккал|kcal|кал|cal)?$", re.IGNORECASE)

def _plans_table(lang: str = "ru") -> str:
    """Компактная таблица тарифов (моноширинный блок)."""
    fd = payments.free_daily_ai()
    fp = payments.free_period_days()
    price = config.SUBSCRIPTION_PRICE_STARS
    if payments.macros_tier_enabled():
        body = (
            "                 Free   Premium  +КБЖУ\n"
            f"               {str(fd):<6} ∞        ∞\n"
            f"               {str(fp)+'d':<6} ∞        ∞\n"
            "Б/Ж/У            —      —        ✅\n"
        )
        tail = t("plans_tail_macros", lang, price=price, mprice=payments.macros_price())
    else:
        body = (
            "                 Free        Premium\n"
            f"               {str(fd):<11} ∞\n"
            f"               {str(fp)+'d':<11} ∞\n"
        )
        tail = t("plans_tail", lang, price=price)
    return "\n" + t("plans_title", lang) + "\n```\n" + body + "```" + tail


def welcome_text(lang: str = "ru") -> str:
    base = t("welcome", lang)
    if payments.monetization_enabled():
        base += "\n" + _plans_table(lang)
    return base


def _today(user) -> dt.date:
    return dt.datetime.now(pytz.timezone(user["timezone"])).date()


async def _gate(update, context):
    """Проверка лимита ИИ-анализов. Если лимит исчерпан — шлёт пэйвол и возвращает (None, today, None).
    Иначе возвращает (mode, today, user)."""
    user = await db.get_user(update.effective_user.id)
    today = _today(user)
    mode = payments.access_mode(user, today)
    if mode == "blocked":
        reason = "limit" if payments.within_free_period(user) else "period"
        await payments.send_paywall(update, reason)
        return None, today, None
    return mode, today, user


async def _apply_corrections(result: dict):
    """Переопределить калории позиций известными выверенными значениями (food_corrections)."""
    if not result:
        return
    items = result.get("items") or []
    changed = False
    for it in items:
        kcal = await db.lookup_correction(it.get("name", ""))
        if kcal is not None:
            it["calories"] = int(kcal)
            changed = True
    if changed and items:
        result["calories"] = sum(int(i.get("calories", 0)) for i in items)


async def _run_estimate(update, user, mode, image_bytes=None, caption=None):
    """Вызвать ИИ с нужной моделью/ключом. Для BYOK при ошибке — фолбэк на общий ключ.
    Возвращает result-dict или None (если не получилось — вызывающий шлёт сообщение)."""
    model, api_key = payments.ai_params(user, mode)
    # high detail (точнее) для полноценной модели, low — для дешёвой free-модели
    detail = "high" if model == config.OPENAI_MODEL else "low"
    macros = payments.macros_enabled(user)
    lang = user["lang"]
    try:
        result = await ai.estimate_food(image_bytes=image_bytes, caption=caption,
                                        model=model, api_key=api_key, detail=detail,
                                        include_macros=macros, lang=lang)
    except Exception as e:
        if mode == "byok":
            log.warning("BYOK-ключ не сработал, фолбэк на общий: %s", e)
            await update.effective_message.reply_text(t("byok_fallback", lang))
            try:
                result = await ai.estimate_food(image_bytes=image_bytes, caption=caption,
                                                model=config.OPENAI_MODEL, detail="high",
                                                include_macros=macros)
            except Exception as e2:
                log.exception("Фолбэк тоже не удался: %s", e2)
                return None
        else:
            log.exception("Ошибка ИИ-оценки: %s", e)
            return None
    # переопределяем калории известных блюд выверенными значениями из админки
    await _apply_corrections(result)
    return result


# ------------------------------------------------------------------- команды

async def _handle_referral(update, context, inserted: bool):
    """Если новый пользователь пришёл по ссылке ?start=ref_<id> — начислить бонус обоим."""
    if not (inserted and payments.referral_enabled() and context.args):
        return
    arg = context.args[0]
    if not arg.startswith("ref_") or not arg[4:].isdigit():
        return
    ref_id = int(arg[4:])
    uid = update.effective_user.id
    if ref_id == uid:
        return
    referrer = await db.get_user(ref_id)
    if not referrer:
        return
    if not await db.add_referral(ref_id, uid):
        return  # этот новичок уже был чьим-то рефералом
    days = payments.referral_reward_days()
    flang = i18n.norm_lang(update.effective_user.language_code)  # язык нового друга
    rlang = referrer["lang"]  # язык реферера
    await db.grant_referral_reward(uid, days)
    await update.message.reply_text(t("ref_friend_bonus", flang, days=days), parse_mode="Markdown")
    needed = payments.referral_friends_needed()
    cnt = await db.count_referrals(ref_id)
    try:
        if cnt % needed == 0:
            await db.grant_referral_reward(ref_id, days)
            await context.bot.send_message(ref_id, t("ref_got_bonus", rlang, days=days),
                                           parse_mode="Markdown")
        else:
            await context.bot.send_message(ref_id, t("ref_progress", rlang, n=needed - cnt % needed))
    except Exception:
        pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    context.user_data.pop("entry_date", None)  # сбрасываем «другой день»
    inserted = await db.ensure_user(u.id, u.username)
    await _handle_referral(update, context, inserted)
    if inserted:  # язык по настройкам Telegram у нового пользователя
        await db.update_settings(u.id, lang=i18n.norm_lang(u.language_code))
    trial_note = None
    if inserted and payments.monetization_enabled() and config.TRIAL_DAYS > 0:
        await db.grant_premium_days(u.id, config.TRIAL_DAYS)
        trial_note = config.TRIAL_DAYS  # текст соберём ниже по языку
    user = await db.get_user(u.id)
    lang = user["lang"]
    reports.schedule_user(context.application, user)
    await update.message.reply_text(welcome_text(lang), parse_mode="Markdown")
    if trial_note:
        await update.message.reply_text(t("trial_note", lang, n=trial_note))
    if not user["onboarded"]:
        # Онбординг: сначала режим цели, затем способ задать калории.
        context.user_data["onboarding"] = True
        context.user_data["awaiting"] = "goal_mode"
        await update.message.reply_text(
            t("choose_goal", lang), parse_mode="Markdown",
            reply_markup=kb.goal_mode_menu(lang))
    else:
        await update.message.reply_text(t("menu", lang), reply_markup=kb.main_menu(lang))


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    user = await db.get_user(update.effective_user.id)
    await update.message.reply_text(t("menu", user["lang"]), reply_markup=kb.main_menu(user["lang"]))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    lang = user["lang"] if user else "ru"
    await update.message.reply_text(welcome_text(lang), parse_mode="Markdown")


async def _invite_text(context, uid, lang="ru") -> str:
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    days = payments.referral_reward_days()
    needed = payments.referral_friends_needed()
    cnt = await db.count_referrals(uid)
    cond = t("invite_cond_each", lang) if needed == 1 else t("invite_cond_n", lang, n=needed)
    return t("invite_title", lang) + "\n\n" + t("invite_body", lang, days=days, cond=cond,
                                                 link=link, cnt=cnt)


async def invite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    user = await db.get_user(update.effective_user.id)
    if not payments.referral_enabled():
        await update.message.reply_text(t("invite_off", user["lang"]))
        return
    await update.message.reply_text(
        await _invite_text(context, update.effective_user.id, user["lang"]), parse_mode="Markdown")


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    user = await db.get_user(update.effective_user.id)
    await update.message.reply_text(t("reset_confirm", user["lang"]), parse_mode="Markdown",
                                    reply_markup=kb.reset_confirm(user["lang"]))


async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    lang = user["lang"] if user else "ru"
    notes = version.latest_notes()
    txt = f"🤖 *Жиромер* v{version.VERSION}"
    if notes:
        txt += "\n\n" + t("ver_changes", lang) + "\n" + "\n".join(f"• {n}" for n in notes)
    await update.message.reply_text(txt, parse_mode="Markdown")


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать свой Telegram user_id (нужен для ADMIN_IDS)."""
    await update.message.reply_text(
        f"Твой Telegram ID: `{update.effective_user.id}`\n"
        "Добавь его в переменную ADMIN_IDS на сервисе, чтобы получить права администратора.",
        parse_mode="Markdown")


async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    user = await db.get_user(update.effective_user.id)
    await update.message.reply_text(
        t("fb_title", user["lang"]), parse_mode="Markdown",
        reply_markup=feedback.menu_keyboard(user["lang"]))


async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    if context.user_data.get("awaiting") in feedback.MEDIA_STATES:
        await feedback.handle_media(update, context, "video", update.message.video.file_id)
    else:
        user = await db.get_user(update.effective_user.id)
        await update.message.reply_text(t("video_no", user["lang"]))


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await feedback.handle_document(update, context)


# ----------------------------------------------------- логирование приёма пищи

def _active_date(context, user) -> dt.date:
    """Дата, в которую пишем приёмы: выбранный «другой день» или сегодня."""
    iso = context.user_data.get("entry_date") if context else None
    if iso:
        try:
            return dt.date.fromisoformat(iso)
        except ValueError:
            pass
    return _today(user)


def _progress_line(total: int, goal: int, lang: str = "ru", label: str = None) -> str:
    """Строка с итогом дня и прогрессом к цели. label — дата для бэкдейта."""
    if not goal:
        return t("no_goal", lang, total=total)
    remaining = goal - total
    bar = reports._progress_bar(total, goal)
    head = (t("today_progress", lang, total=total, goal=goal) if label is None
            else f"{label}: *{total}* / {goal}")
    line = head + f"\n{bar}\n"
    line += t("left", lang, n=remaining) if remaining >= 0 else t("over", lang, n=-remaining)
    return line


async def _macro_progress_line(user, day) -> str:
    """Строка прогресса по Б/Ж/У за день (только если КБЖУ доступен и есть данные)."""
    if not payments.macros_enabled(user):
        return ""
    m = await db.day_macros(user["user_id"], day)
    if not (m["protein"] or m["fat"] or m["carb"]):
        return ""  # нет данных по макросам — не показываем нули
    pg, fg, cg = nutrition.goals_for_user(user)
    return f"\nБ {m['protein']}/{pg} · Ж {m['fat']}/{fg} · У {m['carb']}/{cg} г"


async def _maybe_advice(update, user, day, total, goal):
    """Совет по питанию с учётом режима цели и (для КБЖУ) дефицита макросов.

    Срабатывает в обе стороны: похудение/поддержание — при приближении к лимиту;
    набор — при недоборе калорий.
    """
    mode = user["goal_mode"] or "lose"
    near_limit = goal and total >= 0.8 * goal
    undereat = goal and mode == "gain" and total <= 0.7 * goal
    if not (near_limit or undereat):
        return
    entries = await db.day_entries(user["user_id"], day)
    names = [e["item"] for e in entries if e["item"]]
    macros = macro_goals = None
    if payments.macros_enabled(user):
        macros = await db.day_macros(user["user_id"], day)
        pg, fg, cg = nutrition.goals_for_user(user)
        macro_goals = {"protein": pg, "fat": fg, "carb": cg}
    try:
        advice = await ai.diet_advice(goal, total, names, goal_mode=mode,
                                      macros=macros, macro_goals=macro_goals,
                                      lang=user["lang"])
        await update.effective_message.reply_text(t("advice_prefix", user["lang"], advice=advice))
    except Exception:
        pass


async def _log_and_reply(update, context, calories: int, item: str, result: dict = None):
    user = await db.get_user(update.effective_user.id)
    lang = user["lang"]
    day = _active_date(context, user)
    backdated = day != _today(user)
    p = f = c = None
    if result and payments.macros_enabled(user):
        p, f, c = result.get("protein_g"), result.get("fat_g"), result.get("carb_g")
    entry_id = await db.add_entry(user["user_id"], calories, item, day, p, f, c)
    total = await db.day_total(user["user_id"], day)
    goal = user["goal"] or 0

    if backdated:
        head = t("logged_back", lang, date=day.strftime('%d.%m.%Y'), item=item, cal=calories)
        label = day.strftime("%d.%m")
    else:
        head = t("logged", lang, item=item, cal=calories)
        label = None
    if p is not None and (p or f or c):
        head += f"  (Б {p} · Ж {f} · У {c} г)"
    msg = head + "\n" + _progress_line(total, goal, lang, label) + await _macro_progress_line(user, day)
    await update.effective_message.reply_text(
        msg, parse_mode="Markdown", reply_markup=kb.entry_actions(entry_id, backdated, lang))
    await _maybe_advice(update, user, day, total, goal)


async def _reply_after_edit(update, user, entry_id: int, item: str, calories: int, day):
    lang = user["lang"]
    total = await db.day_total(user["user_id"], day)
    goal = user["goal"] or 0
    label = None if day == _today(user) else day.strftime("%d.%m")
    msg = t("fixed", lang, item=item, cal=calories) + "\n" + _progress_line(total, goal, lang, label)
    await update.effective_message.reply_text(
        msg, parse_mode="Markdown", reply_markup=kb.entry_actions(entry_id, False, lang))
    await _maybe_advice(update, user, day, total, goal)


async def _handle_fix_input(update, context, text: str):
    """Пользователь прислал правку для записи: число калорий или уточнение текстом."""
    uid = update.effective_user.id
    entry_id = context.user_data.pop("fix_entry_id", None)
    context.user_data.pop("awaiting", None)
    user = await db.get_user(uid)
    lang = user["lang"]
    entry = await db.get_entry(entry_id, uid) if entry_id else None
    if not entry:
        await update.message.reply_text(t("fix_not_found", lang))
        return

    # вариант 1: новое число калорий (мгновенно, без ИИ)
    m = _NUM_RE.match(text)
    if m:
        new_cal = int(m.group(1))
        await db.update_entry(entry_id, uid, new_cal, entry["item"])
        await _reply_after_edit(update, user, entry_id, entry["item"], new_cal, entry["entry_date"])
        return

    # вариант 2: уточнение текстом — пересчёт через ИИ (лимит НЕ списываем, это правка)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        result = await ai.estimate_food(caption=text, include_macros=payments.macros_enabled(user),
                                        lang=lang)
    except Exception as e:
        log.exception("Ошибка пересчёта правки: %s", e)
        await update.message.reply_text(t("fix_recalc_fail", lang))
        context.user_data["awaiting"] = "fix"
        context.user_data["fix_entry_id"] = entry_id
        return
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or text[:50]
    await db.update_entry(entry_id, uid, result["calories"], item)
    await _reply_after_edit(update, user, entry_id, item, result["calories"], entry["entry_date"])
    note = result.get("note", "")
    if note:
        await update.message.reply_text(t("note_prefix", lang, note=note))


# -------------------------------------------------------------- приём фото

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    # фото как вложение в форму обратной связи
    if context.user_data.get("awaiting") in feedback.MEDIA_STATES:
        await feedback.handle_media(update, context, "photo", update.message.photo[-1].file_id)
        return
    # фото штрих-кода
    if context.user_data.get("awaiting") == "barcode_photo":
        u = await db.get_user(update.effective_user.id)
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()
        img = bytes(await tg_file.download_as_bytearray())
        code = barcode_mod.decode(img)
        if code:
            await _barcode_lookup(update, context, code, u["lang"])
        else:
            await update.message.reply_text(t("bc_not_found", u["lang"]))
        return
    # обычное фото: сначала по-тихому пробуем штрих-код (бесплатно, без ИИ),
    # и только если кода нет или товара нет в базе — оцениваем по картинке ИИ.
    user = await db.get_user(update.effective_user.id)
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    img_bytes = bytes(await tg_file.download_as_bytearray())
    code = barcode_mod.decode(img_bytes)
    if code:
        product = await foodfacts.lookup(code)
        if product:
            await _ask_bc_grams(update, context, product, user["lang"])
            return
    mode, today, user = await _gate(update, context)
    if mode is None:
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    caption = update.message.caption
    result = await _run_estimate(update, user, mode, image_bytes=img_bytes, caption=caption)
    if result is None:
        await update.message.reply_text(t("photo_fail", user["lang"]))
        return
    await payments.consume(update.effective_user.id, mode, today)
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or t("photo_item_default", user["lang"])
    note = result.get("note", "")
    await _log_and_reply(update, context, result["calories"], item, result)
    if note:
        await update.message.reply_text(t("note_prefix", user["lang"], note=note))


# -------------------------------------------------------------- приём текста

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    await db.ensure_user(update.effective_user.id, update.effective_user.username)

    # ожидаем ввод цели / часа и т.п.
    awaiting = context.user_data.get("awaiting")

    # формы обратной связи
    if awaiting in feedback.TEXT_STATES:
        await feedback.handle_text(update, context, text)
        return

    ulang = (await db.get_user(update.effective_user.id))["lang"]

    if awaiting == "goal":
        m = re.search(r"\d{3,5}", text)
        if not m:
            await update.message.reply_text(t("enter_goal_num", ulang))
            return
        goal = int(m.group())
        if not (500 <= goal <= 10000):
            await update.message.reply_text(t("goal_range", ulang))
            return
        await db.set_goal(update.effective_user.id, goal)
        context.user_data.pop("awaiting", None)
        user = await db.get_user(update.effective_user.id)
        reports.schedule_user(context.application, user)
        await update.message.reply_text(t("goal_set", ulang, goal=goal), parse_mode="Markdown")
        await _finish_goal_setup(update, context)
        return

    if awaiting == "promo":
        context.user_data.pop("awaiting", None)
        await payments.apply_promo(update, context, text)
        return

    if awaiting == "fix":
        await _handle_fix_input(update, context, text)
        return

    if awaiting in ("prof_age", "prof_height", "prof_weight"):
        await _handle_profile_input(update, context, text)
        return

    if awaiting == "barcode_photo":  # пользователь прислал цифры штрих-кода текстом
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 8:
            await _barcode_lookup(update, context, digits, ulang)
        else:
            await update.message.reply_text(t("bc_not_found", ulang))
        return

    if awaiting == "bc_grams":
        mm = re.search(r"\d{1,4}", text)
        if not mm:
            await update.message.reply_text(t("enter_num", ulang))
            return
        await _barcode_finish(update, context, int(mm.group()))
        return

    # ручное добавление калорий числом (бесплатно, без лимита)
    m = _NUM_RE.match(text)
    if m:
        await _log_and_reply(update, context, int(m.group(1)), t("manual_item", ulang))
        return

    # иначе — описание блюда, оцениваем через ИИ (под лимитом)
    await _analyze_food_text(update, context, text)


async def _analyze_food_text(update, context, text: str):
    """Общий пайплайн: лимит → ИИ-оценка по тексту → запись. Для текста и голоса."""
    mode, today, user = await _gate(update, context)
    if mode is None:
        return
    lang = user["lang"]
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    result = await _run_estimate(update, user, mode, caption=text)
    if result is None:
        await update.effective_message.reply_text(t("text_fail", lang))
        return
    await payments.consume(update.effective_user.id, mode, today)
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or text[:50]
    await _log_and_reply(update, context, result["calories"], item, result)
    note = result.get("note", "")
    if note:
        await update.effective_message.reply_text(t("note_prefix", lang, note=note))


async def _ask_bc_grams(update, context, product: dict, lang: str):
    """Запомнить найденный продукт и спросить съеденную граммовку."""
    context.user_data["bc_product"] = product
    context.user_data["awaiting"] = "bc_grams"
    await update.effective_message.reply_text(
        t("bc_ask_grams", lang, name=product["name"], kcal=round(product["kcal_100g"])),
        parse_mode="Markdown")


async def _barcode_lookup(update, context, code: str, lang: str):
    """Найти продукт по коду в Open Food Facts и спросить граммовку."""
    product = await foodfacts.lookup(code)
    if not product:
        await update.effective_message.reply_text(t("bc_off_none", lang))
        return
    await _ask_bc_grams(update, context, product, lang)


async def _barcode_finish(update, context, grams: int):
    """Посчитать порцию по граммам и записать."""
    user = await db.get_user(update.effective_user.id)
    p = context.user_data.pop("bc_product", None)
    context.user_data.pop("awaiting", None)
    if not p:
        return
    k = grams / 100.0
    cal = round(p["kcal_100g"] * k)
    res = {"protein_g": round(p["protein_100g"] * k),
           "fat_g": round(p["fat_100g"] * k),
           "carb_g": round(p["carb_100g"] * k)}
    item = f"{p['name']} ({grams} г)"
    await _log_and_reply(update, context, cal, item, res)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Голосовое сообщение → распознавание (Whisper) → анализ как текст."""
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    user = await db.get_user(update.effective_user.id)
    lang = user["lang"]
    # если идёт форма/онбординг — просим завершить текстом
    if context.user_data.get("awaiting"):
        await update.message.reply_text(t("voice_busy", lang))
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    voice = update.message.voice or update.message.audio
    tg_file = await voice.get_file()
    audio = bytes(await tg_file.download_as_bytearray())
    try:
        text = await ai.transcribe(audio)
    except Exception as e:
        log.exception("Ошибка распознавания голоса: %s", e)
        await update.message.reply_text(t("voice_fail", lang))
        return
    if not text:
        await update.message.reply_text(t("voice_empty", lang))
        return
    await update.message.reply_text(t("voice_heard", lang, text=text))
    m = _NUM_RE.match(text.strip())
    if m:
        await _log_and_reply(update, context, int(m.group(1)), t("manual_item", lang))
    else:
        await _analyze_food_text(update, context, text)


# ----------------------------------------------- онбординг: режим цели и профиль

async def _finish_goal_setup(update, context):
    """После установки цели: при онбординге — спросить напоминания, иначе — меню."""
    uid = update.effective_user.id
    await db.update_settings(uid, onboarded=True)
    lang = (await db.get_user(uid))["lang"]
    if context.user_data.pop("onboarding", False):
        await update.effective_message.reply_text(t("rem_q", lang),
                                                   reply_markup=kb.reminders_onboarding(lang))
    else:
        await update.effective_message.reply_text(t("done", lang), reply_markup=kb.main_menu(lang))


async def _handle_profile_input(update, context, text: str):
    """Текстовые шаги мастера профиля: возраст → рост → вес."""
    awaiting = context.user_data.get("awaiting")
    prof = context.user_data.setdefault("prof", {})
    lang = (await db.get_user(update.effective_user.id))["lang"]
    m = re.search(r"\d{2,3}", text)
    if not m:
        await update.message.reply_text(t("enter_num", lang))
        return
    val = int(m.group())
    if awaiting == "prof_age":
        if not (10 <= val <= 100):
            await update.message.reply_text(t("age_range", lang))
            return
        prof["age"] = val
        context.user_data["awaiting"] = "prof_height"
        await update.message.reply_text(t("ask_height", lang))
    elif awaiting == "prof_height":
        if not (120 <= val <= 230):
            await update.message.reply_text(t("height_range", lang))
            return
        prof["height"] = val
        context.user_data["awaiting"] = "prof_weight"
        await update.message.reply_text(t("ask_weight", lang))
    elif awaiting == "prof_weight":
        if not (30 <= val <= 300):
            await update.message.reply_text(t("weight_range", lang))
            return
        prof["weight"] = val
        context.user_data["awaiting"] = "prof_activity"
        await update.message.reply_text(t("ask_activity", lang), reply_markup=kb.activity_menu(lang))


async def _finish_profile(update, context):
    """Все данные профиля собраны: считаем цель и сохраняем."""
    uid = update.effective_user.id
    prof = context.user_data.get("prof", {})
    user = await db.get_user(uid)
    lang = user["lang"]
    mode = user["goal_mode"] or "lose"
    cal = nutrition.calorie_goal(prof.get("sex"), prof["age"], prof["height"],
                                 prof["weight"], prof.get("activity"), mode)
    await db.set_profile(uid, prof.get("sex"), prof["age"], prof["height"],
                         prof["weight"], prof.get("activity"))
    await db.set_goal(uid, cal)
    context.user_data.pop("prof", None)
    context.user_data.pop("awaiting", None)
    user = await db.get_user(uid)
    reports.schedule_user(context.application, user)
    p, f, c = nutrition.goals_for_user(user)
    await update.effective_message.reply_text(
        t("goal_calc", lang, cal=cal, p=p, f=f, c=c),
        parse_mode="Markdown", reply_markup=kb.goal_confirm(lang))


# --------------------------------------------------------- инлайн-кнопки

async def _render_day_view(q, user, day=None):
    """Показать отчёт за день с кнопками правки/удаления (на месте)."""
    today = reports._today(user["timezone"])
    day = day or today
    entries = await db.day_entries(user["user_id"], day)
    text = reports.format_daily(user, day, entries)
    if day != today:
        text += t("day_back_note", user["lang"])
    try:
        await q.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb.day_manage(entries, day != today, user["lang"]))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id
    user = await db.get_user(uid)
    lang = user["lang"]

    async def _settings(u=None):
        u = u or await db.get_user(uid)
        await q.edit_message_text(t("settings_title", lang), reply_markup=kb.settings_menu(u))

    if data == "reset":
        await q.edit_message_text(t("reset_confirm", lang), parse_mode="Markdown",
                                  reply_markup=kb.reset_confirm(lang))
    elif data == "reset_yes":
        await db.reset_user(uid)
        context.user_data.clear()
        await q.edit_message_text(t("reset_done", lang))
        context.user_data["onboarding"] = True
        context.user_data["awaiting"] = "goal_mode"
        await q.message.reply_text(t("choose_goal", lang), parse_mode="Markdown",
                                   reply_markup=kb.goal_mode_menu(lang))

    elif data.startswith("fix:"):
        entry_id = int(data.split(":")[1])
        entry = await db.get_entry(entry_id, uid)
        if not entry:
            await q.message.reply_text(t("entry_missing", lang))
        else:
            context.user_data["awaiting"] = "fix"
            context.user_data["fix_entry_id"] = entry_id
            await q.message.reply_text(
                t("fix_prompt", lang, item=entry['item'], cal=entry['calories']),
                parse_mode="Markdown")

    elif data.startswith("del:"):
        entry_id = int(data.split(":")[1])
        ok = await db.delete_entry(entry_id, uid)
        if ok:
            total = await db.day_total(uid, _today(user))
            await q.edit_message_text(
                t("entry_deleted", lang) + "\n" + _progress_line(total, user["goal"] or 0, lang=lang),
                parse_mode="Markdown")
        else:
            await q.edit_message_text(t("entry_gone", lang))

    elif data == "buy_premium":
        await q.message.reply_text(t("opening_pay", lang))
        await payments.send_premium_invoice(uid, context)
    elif data == "buy_premium_macros":
        await q.message.reply_text(t("opening_pay", lang))
        await payments.send_macros_invoice(uid, context)
    elif data.startswith("buy_pack:"):
        credits = int(data.split(":")[1])
        stars = dict(config.CREDIT_PACKS).get(credits)
        if stars:
            await payments.send_pack_invoice(uid, context, credits, stars)
        else:
            await q.message.reply_text(t("pack_unavailable", lang))

    elif data == "enter_promo":
        context.user_data["awaiting"] = "promo"
        await q.message.reply_text(t("promo_prompt", lang))

    elif data == "premium":
        today = _today(user)
        if payments.is_premium(user):
            await q.edit_message_text(
                t("premium_until_short", lang, date=user["premium_until"].strftime("%d.%m.%Y")),
                parse_mode="Markdown", reply_markup=kb.back_to_menu(lang))
        else:
            await q.edit_message_text(
                t("premium_offer", lang, remaining=payments.remaining_text(user, today),
                  price=config.SUBSCRIPTION_PRICE_STARS),
                parse_mode="Markdown", reply_markup=payments.paywall_keyboard(lang))

    elif data.startswith("favadd:"):
        entry_id = int(data.split(":")[1])
        e = await db.get_entry(entry_id, uid)
        if e:
            await db.add_favorite(uid, e["item"] or "—", e["calories"],
                                  e["protein_g"], e["fat_g"], e["carb_g"])
            await q.message.reply_text(t("fav_added", lang))
        else:
            await q.message.reply_text(t("entry_missing", lang))

    elif data == "favs":
        favs = await db.list_favorites(uid)
        if not favs:
            await q.edit_message_text(t("fav_empty", lang), reply_markup=kb.back_to_menu(lang))
        else:
            await q.edit_message_text(t("fav_title", lang), reply_markup=kb.favorites_menu(favs, lang))

    elif data.startswith("fav:"):
        fv = await db.get_favorite(int(data.split(":")[1]), uid)
        if fv:
            res = {"protein_g": fv["protein_g"], "fat_g": fv["fat_g"], "carb_g": fv["carb_g"]}
            await _log_and_reply(update, context, fv["calories"], fv["name"], res)
        else:
            await q.message.reply_text(t("entry_missing", lang))

    elif data.startswith("favdel:"):
        await db.delete_favorite(int(data.split(":")[1]), uid)
        favs = await db.list_favorites(uid)
        if favs:
            await q.edit_message_text(t("fav_title", lang), reply_markup=kb.favorites_menu(favs, lang))
        else:
            await q.edit_message_text(t("fav_empty", lang), reply_markup=kb.back_to_menu(lang))

    elif data == "barcode":
        context.user_data["awaiting"] = "barcode_photo"
        await q.edit_message_text(t("bc_ask_photo", lang))

    elif data == "invite":
        if payments.referral_enabled():
            await q.message.reply_text(await _invite_text(context, uid, lang), parse_mode="Markdown")
        else:
            await q.message.reply_text(t("invite_off", lang))

    elif data == "feedback":
        await feedback.open_menu(q, lang)
    elif data == "fb_bug":
        await q.edit_message_text(t("fb_bug", lang))
        await feedback.start_bug(update, context, lang)
    elif data == "fb_cal":
        await q.edit_message_text(t("fb_cal", lang))
        await feedback.start_cal(update, context, lang)

    elif data == "menu":
        await q.edit_message_text(t("menu", lang), reply_markup=kb.main_menu(lang))

    elif data == "today":
        context.user_data.pop("entry_date", None)
        await _render_day_view(q, user, _today(user))

    elif data == "pickdate":
        await q.edit_message_text(t("pickdate_q", lang), reply_markup=kb.backdate_menu(_today(user), lang))

    elif data.startswith("setdate:"):
        iso = data.split(":", 1)[1]
        chosen = dt.date.fromisoformat(iso)
        if chosen == _today(user):
            context.user_data.pop("entry_date", None)
        else:
            context.user_data["entry_date"] = iso
        await _render_day_view(q, user, chosen)

    elif data == "date_today":
        context.user_data.pop("entry_date", None)
        await q.edit_message_text(t("back_to_today_msg", lang))
        await q.message.reply_text(t("menu", lang), reply_markup=kb.main_menu(lang))

    elif data.startswith("ddel:"):
        entry_id = int(data.split(":")[1])
        await db.delete_entry(entry_id, uid)
        await _render_day_view(q, user, _active_date(context, user))

    elif data == "week":
        text = await reports.build_weekly_text(user)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb.back_to_menu(lang))

    elif data == "settings":
        await _settings(user)

    elif data == "set_goal":
        context.user_data["awaiting"] = "goal"
        await q.edit_message_text(t("set_goal_prompt", lang))

    # --- язык ---
    elif data == "set_lang":
        await q.edit_message_text(t("lang_q", lang), reply_markup=kb.lang_menu())
    elif data.startswith("setlang:"):
        new_lang = data.split(":")[1]
        await db.update_settings(uid, lang=new_lang)
        await q.edit_message_text(t("lang_set", new_lang))
        await q.message.reply_text(t("menu", new_lang), reply_markup=kb.main_menu(new_lang))

    # --- режим цели и профиль ---
    elif data == "set_mode":
        await q.edit_message_text(t("mode_q", lang), reply_markup=kb.goal_mode_menu(lang))
    elif data.startswith("gm:"):
        await db.update_settings(uid, goal_mode=data.split(":")[1])
        if context.user_data.get("onboarding"):
            context.user_data["awaiting"] = "goal_setup"
            await q.edit_message_text(t("setup_q", lang), reply_markup=kb.setup_method_menu(lang))
        else:
            await _settings()
    elif data in ("calc_profile", "set_profile"):
        context.user_data["prof"] = {}
        context.user_data["awaiting"] = "prof_sex"
        await q.edit_message_text(t("ask_sex", lang), reply_markup=kb.sex_menu(lang))
    elif data == "manual_goal":
        context.user_data["awaiting"] = "goal"
        await q.edit_message_text(t("ask_calories", lang))
    elif data == "goal_ok":
        await q.edit_message_text(t("great", lang))
        await _finish_goal_setup(update, context)
    elif data == "trust_default":
        u = await db.get_user(uid)
        goal = nutrition.default_goal(u["goal_mode"] or "lose")
        await db.set_goal(uid, goal)
        u = await db.get_user(uid)
        reports.schedule_user(context.application, u)
        p, f, c = nutrition.goals_for_user(u)
        await q.edit_message_text(t("trust_set", lang, goal=goal, p=p, f=f, c=c),
                                  parse_mode="Markdown", reply_markup=kb.goal_confirm(lang))
    elif data.startswith("psex:"):
        context.user_data.setdefault("prof", {})["sex"] = data.split(":")[1]
        context.user_data["awaiting"] = "prof_age"
        await q.edit_message_text(t("ask_age", lang))
    elif data.startswith("pact:"):
        context.user_data.setdefault("prof", {})["activity"] = data.split(":")[1]
        await _finish_profile(update, context)

    elif data == "set_hour":
        await q.edit_message_text(t("hour_q", lang), reply_markup=kb.hours_menu(lang))
    elif data.startswith("hour:"):
        await db.update_settings(uid, daily_hour=int(data.split(":")[1]))
        reports.schedule_user(context.application, await db.get_user(uid))
        await _settings()

    elif data == "set_dow":
        await q.edit_message_text(t("dow_q", lang), reply_markup=kb.dow_menu(lang))
    elif data.startswith("dow:"):
        await db.update_settings(uid, weekly_dow=int(data.split(":")[1]))
        await _settings()

    elif data == "set_tz":
        await q.edit_message_text(t("tz_q", lang, v=kb.tz_display(user['timezone'])),
                                  parse_mode="Markdown", reply_markup=kb.tz_menu(lang))
    elif data.startswith("tz:"):
        await db.update_settings(uid, timezone=data.split(":", 1)[1])
        reports.schedule_user(context.application, await db.get_user(uid))
        await _settings()

    elif data == "toggle_daily":
        await db.update_settings(uid, daily_on=not user["daily_on"])
        await _settings()
    elif data == "toggle_weekly":
        await db.update_settings(uid, weekly_on=not user["weekly_on"])
        await _settings()

    # --- напоминания ---
    elif data == "rem_on":
        await db.update_settings(uid, reminders_on=True)
        reminders.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text(t("rem_done_on", lang))
    elif data == "rem_off":
        await db.update_settings(uid, reminders_on=False)
        reminders.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text(t("rem_done_off", lang))
    elif data == "toggle_rem":
        await db.update_settings(uid, reminders_on=not user["reminders_on"])
        reminders.schedule_user(context.application, await db.get_user(uid))
        await _settings()
    elif data == "set_rem_int":
        await q.edit_message_text(t("rem_int_q", lang), reply_markup=kb.rem_interval_menu(lang))
    elif data.startswith("remint:"):
        await db.update_settings(uid, reminder_interval=int(data.split(":")[1]))
        reminders.schedule_user(context.application, await db.get_user(uid))
        await _settings()
