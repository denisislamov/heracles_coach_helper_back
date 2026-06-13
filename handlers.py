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
import config
import db
import feedback
import keyboards as kb
import nutrition
import payments
import reminders
import reports
import version

log = logging.getLogger("calbot.handlers")

# Текст-«число калорий»: «350», «+200», «350 ккал»
_NUM_RE = re.compile(r"^\+?\s*(\d{1,5})\s*(ккал|kcal|кал|cal)?$", re.IGNORECASE)

def _plans_table() -> str:
    """Компактная таблица тарифов (моноширинный блок)."""
    fd = payments.free_daily_ai()
    fp = payments.free_period_days()
    price = config.SUBSCRIPTION_PRICE_STARS
    if payments.macros_tier_enabled():
        body = (
            "                 Free   Premium  +КБЖУ\n"
            f"Анализов в день  {str(fd):<6} ∞        ∞\n"
            f"Доступ           {str(fp)+'д':<6} всегда   всегда\n"
            "Точность ИИ      базов. высокая высокая\n"
            "Б/Ж/У            —      —        ✅\n"
        )
        tail = (f"Premium — {price}★/мес, Premium+КБЖУ — {payments.macros_price()}★/мес. "
                "Подробнее: /premium\n")
    else:
        body = (
            "                 Free        Premium\n"
            f"Анализов в день  {str(fd):<11} без лимита\n"
            f"Доступ           {str(fp)+' дн.':<11} всегда\n"
            "Точность ИИ      базовая     высокая\n"
        )
        tail = f"Premium — {price}★/мес. Подробнее: /premium\n"
    return "\nТарифы:\n```\n" + body + "```" + tail


def welcome_text() -> str:
    base = (
        "👋 Привет! Я *Жиромер* — помогу считать калории.\n\n"
        "Что я умею:\n"
        "• 📷 Пришли *фото еды* — оценю калорийность.\n"
        "• 📷 + подпись — оценю точнее (например: «куриная грудка 200 г»).\n"
        "• ✍️ Просто текст блюда — оценю по описанию.\n"
        "• 🔢 Просто число (напр. `350`) — добавлю столько ккал вручную.\n\n"
        "Ошибся? Под каждой записью кнопки *✏️ Исправить* и *🗑 Удалить*.\n"
        "В конце дня пришлю дневной отчёт, раз в неделю — недельный.\n\n"
        "⚙️ *Цель, режим* (похудение / поддержание / набор) *и профиль* "
        "(рост, вес — для авто-расчёта) — в /menu → Настройки.\n"
        "Меню — /menu."
    )
    if payments.monetization_enabled():
        base += "\n" + _plans_table()
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
    try:
        result = await ai.estimate_food(image_bytes=image_bytes, caption=caption,
                                        model=model, api_key=api_key, detail=detail,
                                        include_macros=macros)
    except Exception as e:
        if mode == "byok":
            log.warning("BYOK-ключ не сработал, фолбэк на общий: %s", e)
            await update.effective_message.reply_text(
                "⚠️ Твой ключ OpenAI не сработал — считаю на общем. Проверь ключ или /delkey.")
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    context.user_data.pop("entry_date", None)  # сбрасываем «другой день»
    inserted = await db.ensure_user(u.id, u.username)
    trial_note = None
    if inserted and payments.monetization_enabled() and config.TRIAL_DAYS > 0:
        await db.grant_premium_days(u.id, config.TRIAL_DAYS)
        trial_note = f"🎁 Первые {config.TRIAL_DAYS} дня — безлимитный доступ!"
    user = await db.get_user(u.id)
    reports.schedule_user(context.application, user)
    await update.message.reply_text(welcome_text(), parse_mode="Markdown")
    if trial_note:
        await update.message.reply_text(trial_note)
    if not user["onboarded"]:
        # Онбординг: сначала режим цели, затем способ задать калории.
        context.user_data["onboarding"] = True
        context.user_data["awaiting"] = "goal_mode"
        await update.message.reply_text(
            "Для начала выбери свою *цель*:", parse_mode="Markdown",
            reply_markup=kb.goal_mode_menu())
    else:
        await update.message.reply_text("Главное меню:", reply_markup=kb.main_menu())


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text("Главное меню:", reply_markup=kb.main_menu())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(welcome_text(), parse_mode="Markdown")


async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = version.latest_notes()
    txt = f"🤖 *Жиромер* v{version.VERSION}"
    if notes:
        txt += "\n\nПоследние изменения:\n" + "\n".join(f"• {n}" for n in notes)
    await update.message.reply_text(txt, parse_mode="Markdown")


async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text(
        "🛟 *Обратная связь*\n\nВыбери, о чём сообщить:",
        parse_mode="Markdown", reply_markup=feedback.menu_keyboard())


async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    if context.user_data.get("awaiting") in feedback.MEDIA_STATES:
        await feedback.handle_media(update, context, "video", update.message.video.file_id)
    else:
        await update.message.reply_text("Видео я пока не распознаю. Пришли фото блюда 📷")


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


def _progress_line(total: int, goal: int, label: str = "Сегодня") -> str:
    """Строка с итогом дня и прогрессом к цели."""
    if not goal:
        return f"{label} всего: *{total}* ккал. Цель не задана — /menu."
    remaining = goal - total
    bar = reports._progress_bar(total, goal)
    line = f"{label}: *{total}* / {goal} ккал\n{bar}\n"
    line += (f"Осталось *{remaining}* ккал." if remaining >= 0
             else f"⚠️ Превышение на *{-remaining}* ккал.")
    return line


async def _macro_progress_line(user, day) -> str:
    """Строка прогресса по Б/Ж/У за день (только если КБЖУ доступен)."""
    if not payments.macros_enabled(user):
        return ""
    m = await db.day_macros(user["user_id"], day)
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
                                      macros=macros, macro_goals=macro_goals)
        await update.effective_message.reply_text(f"💡 {advice}")
    except Exception:
        pass


async def _log_and_reply(update, context, calories: int, item: str, result: dict = None):
    user = await db.get_user(update.effective_user.id)
    day = _active_date(context, user)
    backdated = day != _today(user)
    p = f = c = None
    if result and payments.macros_enabled(user):
        p, f, c = result.get("protein_g"), result.get("fat_g"), result.get("carb_g")
    entry_id = await db.add_entry(user["user_id"], calories, item, day, p, f, c)
    total = await db.day_total(user["user_id"], day)
    goal = user["goal"] or 0

    label = "Сегодня" if not backdated else day.strftime("%d.%m")
    head = (f"✅ Записал: *{item}* — {calories} ккал.\n" if not backdated
            else f"✅ Записал за *{day.strftime('%d.%m.%Y')}*: *{item}* — {calories} ккал.\n")
    if p is not None:
        head = head.rstrip("\n") + f"  (Б {p} · Ж {f} · У {c} г)\n"
    msg = head + _progress_line(total, goal, label) + await _macro_progress_line(user, day)
    await update.effective_message.reply_text(
        msg, parse_mode="Markdown", reply_markup=kb.entry_actions(entry_id, backdated))
    await _maybe_advice(update, user, day, total, goal)


async def _reply_after_edit(update, user, entry_id: int, item: str, calories: int, day):
    total = await db.day_total(user["user_id"], day)
    goal = user["goal"] or 0
    label = "Сегодня" if day == _today(user) else day.strftime("%d.%m")
    msg = f"✏️ Обновил: *{item}* — {calories} ккал.\n" + _progress_line(total, goal, label)
    await update.effective_message.reply_text(
        msg, parse_mode="Markdown", reply_markup=kb.entry_actions(entry_id))
    await _maybe_advice(update, user, day, total, goal)


async def _handle_fix_input(update, context, text: str):
    """Пользователь прислал правку для записи: число калорий или уточнение текстом."""
    uid = update.effective_user.id
    entry_id = context.user_data.pop("fix_entry_id", None)
    context.user_data.pop("awaiting", None)
    user = await db.get_user(uid)
    entry = await db.get_entry(entry_id, uid) if entry_id else None
    if not entry:
        await update.message.reply_text("Не нашёл запись для правки — возможно, она удалена.")
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
        result = await ai.estimate_food(caption=text)
    except Exception as e:
        log.exception("Ошибка пересчёта правки: %s", e)
        await update.message.reply_text(
            "Не получилось пересчитать 😕 Пришли правильное число калорий.")
        context.user_data["awaiting"] = "fix"
        context.user_data["fix_entry_id"] = entry_id
        return
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or text[:50]
    await db.update_entry(entry_id, uid, result["calories"], item)
    await _reply_after_edit(update, user, entry_id, item, result["calories"], entry["entry_date"])
    note = result.get("note", "")
    if note:
        await update.message.reply_text(f"🔎 {note}")


# -------------------------------------------------------------- приём фото

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    # фото как вложение в форму обратной связи
    if context.user_data.get("awaiting") in feedback.MEDIA_STATES:
        await feedback.handle_media(update, context, "photo", update.message.photo[-1].file_id)
        return
    mode, today, user = await _gate(update, context)
    if mode is None:
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    img_bytes = bytes(await tg_file.download_as_bytearray())
    caption = update.message.caption
    result = await _run_estimate(update, user, mode, image_bytes=img_bytes, caption=caption)
    if result is None:
        await update.message.reply_text(
            "Не удалось распознать фото 😕 Попробуй ещё раз или пришли описание текстом.")
        return
    await payments.consume(update.effective_user.id, mode, today)
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or "блюдо с фото"
    note = result.get("note", "")
    await _log_and_reply(update, context, result["calories"], item, result)
    if note:
        await update.message.reply_text(f"🔎 {note}")


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

    if awaiting == "goal":
        m = re.search(r"\d{3,5}", text)
        if not m:
            await update.message.reply_text("Введи число, например 2000.")
            return
        goal = int(m.group())
        if not (500 <= goal <= 10000):
            await update.message.reply_text("Цель должна быть в диапазоне 500–10000 ккал.")
            return
        await db.set_goal(update.effective_user.id, goal)
        context.user_data.pop("awaiting", None)
        user = await db.get_user(update.effective_user.id)
        reports.schedule_user(context.application, user)
        await update.message.reply_text(
            f"🎯 Цель установлена: *{goal}* ккал/день.", parse_mode="Markdown")
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

    # ручное добавление калорий числом (бесплатно, без лимита)
    m = _NUM_RE.match(text)
    if m:
        await _log_and_reply(update, context, int(m.group(1)), "ручной ввод")
        return

    # иначе — описание блюда, оцениваем через ИИ (под лимитом)
    mode, today, user = await _gate(update, context)
    if mode is None:
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    result = await _run_estimate(update, user, mode, caption=text)
    if result is None:
        await update.message.reply_text("Не получилось оценить 😕 Попробуй иначе или пришли фото.")
        return
    await payments.consume(update.effective_user.id, mode, today)
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or text[:50]
    await _log_and_reply(update, context, result["calories"], item, result)
    note = result.get("note", "")
    if note:
        await update.message.reply_text(f"🔎 {note}")


# ----------------------------------------------- онбординг: режим цели и профиль

async def _finish_goal_setup(update, context):
    """После установки цели: при онбординге — спросить напоминания, иначе — меню."""
    await db.update_settings(update.effective_user.id, onboarded=True)
    if context.user_data.pop("onboarding", False):
        await update.effective_message.reply_text(
            "🔔 Включить напоминания? Если засидишься, бот мягко напомнит "
            "записать приём пищи (по умолчанию раз в 5 часов, только днём).",
            reply_markup=kb.reminders_onboarding())
    else:
        await update.effective_message.reply_text(
            "Готово. Главное меню:", reply_markup=kb.main_menu())


async def _handle_profile_input(update, context, text: str):
    """Текстовые шаги мастера профиля: возраст → рост → вес."""
    awaiting = context.user_data.get("awaiting")
    prof = context.user_data.setdefault("prof", {})
    m = re.search(r"\d{2,3}", text)
    if not m:
        await update.message.reply_text("Введи число.")
        return
    val = int(m.group())
    if awaiting == "prof_age":
        if not (10 <= val <= 100):
            await update.message.reply_text("Возраст должен быть 10–100.")
            return
        prof["age"] = val
        context.user_data["awaiting"] = "prof_height"
        await update.message.reply_text("Рост в см? (напр. 175)")
    elif awaiting == "prof_height":
        if not (120 <= val <= 230):
            await update.message.reply_text("Рост должен быть 120–230 см.")
            return
        prof["height"] = val
        context.user_data["awaiting"] = "prof_weight"
        await update.message.reply_text("Вес в кг? (напр. 70)")
    elif awaiting == "prof_weight":
        if not (30 <= val <= 300):
            await update.message.reply_text("Вес должен быть 30–300 кг.")
            return
        prof["weight"] = val
        context.user_data["awaiting"] = "prof_activity"
        await update.message.reply_text("Уровень активности?", reply_markup=kb.activity_menu())


async def _finish_profile(update, context):
    """Все данные профиля собраны: считаем цель и сохраняем."""
    uid = update.effective_user.id
    prof = context.user_data.get("prof", {})
    user = await db.get_user(uid)
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
        f"📊 Готово! Рассчитал под твою цель:\n"
        f"*{cal} ккал/день* · Б {p} · Ж {f} · У {c} г.",
        parse_mode="Markdown")
    await _finish_goal_setup(update, context)


# --------------------------------------------------------- инлайн-кнопки

async def _render_day_view(q, user, day=None):
    """Показать отчёт за день с кнопками правки/удаления (на месте)."""
    today = reports._today(user["timezone"])
    day = day or today
    entries = await db.day_entries(user["user_id"], day)
    text = reports.format_daily(user, day, entries)
    if day != today:
        text += ("\n\n🗓 Это прошлый день. Фото/текст/число, отправленные сейчас, "
                 "добавятся в эту дату. Чтобы вернуться к сегодня — кнопка ниже.")
    try:
        await q.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb.day_manage(entries, day != today))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id
    user = await db.get_user(uid)

    if data == "keep_goal":
        context.user_data.pop("awaiting", None)
        await q.edit_message_text(
            f"🎯 Оставил цель: *{user['goal']} ккал/день*.", parse_mode="Markdown")
        await q.message.reply_text("Главное меню:", reply_markup=kb.main_menu())

    elif data.startswith("fix:"):
        entry_id = int(data.split(":")[1])
        entry = await db.get_entry(entry_id, uid)
        if not entry:
            await q.message.reply_text("Эта запись уже удалена.")
        else:
            context.user_data["awaiting"] = "fix"
            context.user_data["fix_entry_id"] = entry_id
            await q.message.reply_text(
                f"✏️ Правлю «{entry['item']}» ({entry['calories']} ккал).\n"
                "Пришли *правильное число калорий* или *уточни блюдо текстом* "
                "(напр. «это хачапури, порция 300 г») — пересчитаю без списания лимита.",
                parse_mode="Markdown")

    elif data.startswith("del:"):
        entry_id = int(data.split(":")[1])
        ok = await db.delete_entry(entry_id, uid)
        if ok:
            day = _today(user)
            total = await db.day_total(uid, day)
            await q.edit_message_text(
                "🗑 Запись удалена.\n" + _progress_line(total, user["goal"] or 0),
                parse_mode="Markdown")
        else:
            await q.edit_message_text("🗑 Запись уже была удалена.")

    elif data == "buy_premium":
        await q.message.reply_text("Открываю оплату звёздами…")
        await payments.send_premium_invoice(uid, context)

    elif data == "buy_premium_macros":
        await q.message.reply_text("Открываю оплату звёздами…")
        await payments.send_macros_invoice(uid, context)

    elif data.startswith("buy_pack:"):
        credits = int(data.split(":")[1])
        stars = dict(config.CREDIT_PACKS).get(credits)
        if stars:
            await payments.send_pack_invoice(uid, context, credits, stars)
        else:
            await q.message.reply_text("Пакет недоступен.")

    elif data == "enter_promo":
        context.user_data["awaiting"] = "promo"
        await q.message.reply_text("🎟 Пришли промокод одним сообщением:")

    elif data == "premium":
        today = _today(user)
        if payments.is_premium(user):
            until = user["premium_until"].strftime("%d.%m.%Y")
            await q.edit_message_text(
                f"⭐ Premium активен до *{until}*.", parse_mode="Markdown",
                reply_markup=kb.back_to_menu())
        else:
            await q.edit_message_text(
                f"{payments.remaining_text(user, today)}\n\n"
                f"*Premium* — {config.SUBSCRIPTION_PRICE_STARS}★ на "
                f"{config.SUBSCRIPTION_DAYS} дней, безлимитные анализы.",
                parse_mode="Markdown", reply_markup=payments.paywall_keyboard())

    elif data == "feedback":
        await feedback.open_menu(q)
    elif data == "fb_bug":
        await q.edit_message_text("🐞 Баг-репорт")
        await feedback.start_bug(update, context)
    elif data == "fb_cal":
        await q.edit_message_text("🍽 Неверные калории")
        await feedback.start_cal(update, context)

    elif data == "menu":
        await q.edit_message_text("Главное меню:", reply_markup=kb.main_menu())

    elif data == "today":
        context.user_data.pop("entry_date", None)
        await _render_day_view(q, user, _today(user))

    elif data == "pickdate":
        await q.edit_message_text(
            "🗓 За какой день добавить? Выбери дату — следующие фото/текст пойдут в неё:",
            reply_markup=kb.backdate_menu(_today(user)))

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
        await q.edit_message_text("↩️ Снова работаем с сегодняшней датой.")
        await q.message.reply_text("Главное меню:", reply_markup=kb.main_menu())

    elif data.startswith("ddel:"):
        entry_id = int(data.split(":")[1])
        await db.delete_entry(entry_id, uid)
        await _render_day_view(q, user, _active_date(context, user))

    elif data == "week":
        text = await reports.build_weekly_text(user)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb.back_to_menu())

    elif data == "settings":
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(user))

    elif data == "set_goal":
        context.user_data["awaiting"] = "goal"
        await q.edit_message_text("🎯 Пришли новое число цели (ккал/день):")

    # --- режим цели и профиль ---
    elif data == "set_mode":
        await q.edit_message_text("🏃 Выбери режим цели:", reply_markup=kb.goal_mode_menu())
    elif data.startswith("gm:"):
        await db.update_settings(uid, goal_mode=data.split(":")[1])
        if context.user_data.get("onboarding"):
            context.user_data["awaiting"] = "goal_setup"
            await q.edit_message_text(
                "Как зададим дневную цель по калориям?", reply_markup=kb.setup_method_menu())
        else:
            await q.edit_message_text("⚙️ Настройки:",
                                      reply_markup=kb.settings_menu(await db.get_user(uid)))
    elif data == "calc_profile":
        context.user_data["prof"] = {}
        context.user_data["awaiting"] = "prof_sex"
        await q.edit_message_text("Укажи пол:", reply_markup=kb.sex_menu())
    elif data == "manual_goal":
        context.user_data["awaiting"] = "goal"
        await q.edit_message_text("🎯 Пришли число дневной цели (ккал, напр. 2000):")
    elif data == "trust_default":
        u = await db.get_user(uid)
        goal = nutrition.default_goal(u["goal_mode"] or "lose")
        await db.set_goal(uid, goal)
        u = await db.get_user(uid)
        reports.schedule_user(context.application, u)
        p, f, c = nutrition.goals_for_user(u)
        await q.edit_message_text(
            f"🤝 Поставил стандартную цель под твой режим: *{goal} ккал/день* "
            f"(Б {p} · Ж {f} · У {c} г). Изменить можно в /menu → Настройки.",
            parse_mode="Markdown")
        await _finish_goal_setup(update, context)
    elif data == "set_profile":
        context.user_data["prof"] = {}
        context.user_data["awaiting"] = "prof_sex"
        await q.edit_message_text("Укажи пол:", reply_markup=kb.sex_menu())
    elif data.startswith("psex:"):
        context.user_data.setdefault("prof", {})["sex"] = data.split(":")[1]
        context.user_data["awaiting"] = "prof_age"
        await q.edit_message_text("Сколько тебе лет? (напр. 30)")
    elif data.startswith("pact:"):
        context.user_data.setdefault("prof", {})["activity"] = data.split(":")[1]
        await _finish_profile(update, context)

    elif data == "set_hour":
        await q.edit_message_text("🕘 Час дневного отчёта:", reply_markup=kb.hours_menu())
    elif data.startswith("hour:"):
        await db.update_settings(uid, daily_hour=int(data.split(":")[1]))
        reports.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(await db.get_user(uid)))

    elif data == "set_dow":
        await q.edit_message_text("📆 День недельного отчёта:", reply_markup=kb.dow_menu())
    elif data.startswith("dow:"):
        await db.update_settings(uid, weekly_dow=int(data.split(":")[1]))
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(await db.get_user(uid)))

    elif data == "set_tz":
        await q.edit_message_text(
            f"🌍 Текущий пояс: *{kb.tz_display(user['timezone'])}*.\n"
            "Выбери смещение от UTC — по нему бот считает «день» и шлёт отчёты:",
            parse_mode="Markdown", reply_markup=kb.tz_menu())
    elif data.startswith("tz:"):
        await db.update_settings(uid, timezone=data.split(":", 1)[1])
        reports.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(await db.get_user(uid)))

    elif data == "toggle_daily":
        await db.update_settings(uid, daily_on=not user["daily_on"])
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(await db.get_user(uid)))
    elif data == "toggle_weekly":
        await db.update_settings(uid, weekly_on=not user["weekly_on"])
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(await db.get_user(uid)))

    # --- напоминания ---
    elif data == "rem_on":
        await db.update_settings(uid, reminders_on=True)
        reminders.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text("🔔 Напоминания включены. Поехали!")
        await q.message.reply_text("Главное меню:", reply_markup=kb.main_menu())
    elif data == "rem_off":
        await db.update_settings(uid, reminders_on=False)
        reminders.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text("🔕 Хорошо, без напоминаний. Включить можно в /menu → Настройки.")
        await q.message.reply_text("Главное меню:", reply_markup=kb.main_menu())
    elif data == "toggle_rem":
        await db.update_settings(uid, reminders_on=not user["reminders_on"])
        reminders.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(await db.get_user(uid)))
    elif data == "set_rem_int":
        await q.edit_message_text("⏰ Как часто напоминать?", reply_markup=kb.rem_interval_menu())
    elif data.startswith("remint:"):
        await db.update_settings(uid, reminder_interval=int(data.split(":")[1]))
        reminders.schedule_user(context.application, await db.get_user(uid))
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(await db.get_user(uid)))
