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
import keyboards as kb
import payments
import reports

log = logging.getLogger("calbot.handlers")

# Текст-«число калорий»: «350», «+200», «350 ккал»
_NUM_RE = re.compile(r"^\+?\s*(\d{1,5})\s*(ккал|kcal|кал|cal)?$", re.IGNORECASE)

WELCOME = (
    "👋 Привет! Я *Жиромер* — помогу считать калории.\n\n"
    "Что я умею:\n"
    "• 📷 Пришли *фото еды* — оценю калорийность.\n"
    "• 📷 + подпись — оценю точнее (например: «куриная грудка 200 г»).\n"
    "• ✍️ Просто текст блюда — оценю по описанию.\n"
    "• 🔢 Просто число (напр. `350`) — добавлю столько ккал вручную.\n\n"
    "Ошибся? Под каждой записью кнопки *✏️ Исправить* и *🗑 Удалить*.\n"
    "В конце дня пришлю дневной отчёт, раз в неделю — недельный.\n"
    f"Бесплатно {config.FREE_DAILY_AI} ИИ-анализов в день, дальше — /premium.\n"
    "Меню — /menu, промокод — /promo."
)


def _today(user) -> dt.date:
    return dt.datetime.now(pytz.timezone(user["timezone"])).date()


async def _gate(update, context):
    """Проверка лимита ИИ-анализов. Если лимит исчерпан — шлёт пэйвол и возвращает (None, today).
    Иначе возвращает (mode, today): premium | credit | free."""
    user = await db.get_user(update.effective_user.id)
    today = _today(user)
    mode = payments.access_mode(user, today)
    if mode == "blocked":
        await payments.send_paywall(update)
        return None, today
    return mode, today


# ------------------------------------------------------------------- команды

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await db.ensure_user(u.id, u.username)
    user = await db.get_user(u.id)
    reports.schedule_user(context.application, user)
    await update.message.reply_text(WELCOME, parse_mode="Markdown")
    # Всегда запускаем шаг с целью.
    context.user_data["awaiting"] = "goal"
    if user["goal"]:
        await update.message.reply_text(
            f"🎯 Твоя текущая цель: *{user['goal']} ккал/день*.\n"
            "Пришли новое число, чтобы изменить, или оставь текущую.",
            parse_mode="Markdown",
            reply_markup=kb.keep_goal(user["goal"]),
        )
    else:
        await update.message.reply_text(
            "🎯 Для начала укажи *цель по калориям на день* (число, напр. 2000):",
            parse_mode="Markdown",
        )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text("Главное меню:", reply_markup=kb.main_menu())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


# ----------------------------------------------------- логирование приёма пищи

def _progress_line(total: int, goal: int) -> str:
    """Строка с дневным итогом и прогрессом к цели."""
    if not goal:
        return f"Сегодня всего: *{total}* ккал. Цель не задана — /menu."
    remaining = goal - total
    bar = reports._progress_bar(total, goal)
    line = f"Сегодня: *{total}* / {goal} ккал\n{bar}\n"
    line += (f"Осталось *{remaining}* ккал." if remaining >= 0
             else f"⚠️ Превышение на *{-remaining}* ккал.")
    return line


async def _maybe_advice(update, user, day, total, goal):
    """Совет по диете при ≥80% цели или превышении."""
    if goal and total >= 0.8 * goal:
        entries = await db.day_entries(user["user_id"], day)
        names = [e["item"] for e in entries if e["item"]]
        try:
            advice = await ai.diet_advice(goal, total, names)
            await update.effective_message.reply_text(f"💡 {advice}")
        except Exception:
            pass


async def _log_and_reply(update, context, calories: int, item: str):
    user = await db.get_user(update.effective_user.id)
    day = _today(user)
    entry_id = await db.add_entry(user["user_id"], calories, item, day)
    total = await db.day_total(user["user_id"], day)
    goal = user["goal"] or 0

    msg = f"✅ Записал: *{item}* — {calories} ккал.\n" + _progress_line(total, goal)
    await update.effective_message.reply_text(
        msg, parse_mode="Markdown", reply_markup=kb.entry_actions(entry_id))
    await _maybe_advice(update, user, day, total, goal)


async def _reply_after_edit(update, user, entry_id: int, item: str, calories: int):
    day = _today(user)
    total = await db.day_total(user["user_id"], day)
    goal = user["goal"] or 0
    msg = f"✏️ Обновил: *{item}* — {calories} ккал.\n" + _progress_line(total, goal)
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
        await _reply_after_edit(update, user, entry_id, entry["item"], new_cal)
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
    await _reply_after_edit(update, user, entry_id, item, result["calories"])
    note = result.get("note", "")
    if note:
        await update.message.reply_text(f"🔎 {note}")


# -------------------------------------------------------------- приём фото

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    mode, today = await _gate(update, context)
    if mode is None:
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    img_bytes = bytes(await tg_file.download_as_bytearray())
    caption = update.message.caption
    try:
        result = await ai.estimate_food(image_bytes=img_bytes, caption=caption)
    except Exception as e:
        log.exception("Ошибка распознавания фото: %s", e)
        await update.message.reply_text(
            "Не удалось распознать фото 😕 Попробуй ещё раз или пришли описание текстом.")
        return
    await payments.consume(update.effective_user.id, mode, today)
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or "блюдо с фото"
    note = result.get("note", "")
    await _log_and_reply(update, context, result["calories"], item)
    if note:
        await update.message.reply_text(f"🔎 {note}")


# -------------------------------------------------------------- приём текста

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    await db.ensure_user(update.effective_user.id, update.effective_user.username)

    # ожидаем ввод цели / часа и т.п.
    awaiting = context.user_data.get("awaiting")
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
            f"🎯 Цель установлена: *{goal}* ккal/день.", parse_mode="Markdown",
            reply_markup=kb.main_menu())
        return

    if awaiting == "promo":
        context.user_data.pop("awaiting", None)
        await payments.apply_promo(update, context, text)
        return

    if awaiting == "fix":
        await _handle_fix_input(update, context, text)
        return

    # ручное добавление калорий числом (бесплатно, без лимита)
    m = _NUM_RE.match(text)
    if m:
        await _log_and_reply(update, context, int(m.group(1)), "ручной ввод")
        return

    # иначе — описание блюда, оцениваем через ИИ (под лимитом)
    mode, today = await _gate(update, context)
    if mode is None:
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        result = await ai.estimate_food(caption=text)
    except Exception as e:
        log.exception("Ошибка оценки по тексту: %s", e)
        await update.message.reply_text("Не получилось оценить 😕 Попробуй иначе или пришли фото.")
        return
    await payments.consume(update.effective_user.id, mode, today)
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or text[:50]
    await _log_and_reply(update, context, result["calories"], item)
    note = result.get("note", "")
    if note:
        await update.message.reply_text(f"🔎 {note}")


# --------------------------------------------------------- инлайн-кнопки

async def _render_day_view(q, user):
    """Показать дневной отчёт с кнопками правки/удаления каждой записи (на месте)."""
    day = reports._today(user["timezone"])
    entries = await db.day_entries(user["user_id"], day)
    text = reports.format_daily(user, day, entries)
    try:
        await q.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb.day_manage(entries))
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

    elif data == "menu":
        await q.edit_message_text("Главное меню:", reply_markup=kb.main_menu())

    elif data == "today":
        await _render_day_view(q, user)

    elif data.startswith("ddel:"):
        entry_id = int(data.split(":")[1])
        await db.delete_entry(entry_id, uid)
        await _render_day_view(q, user)

    elif data == "week":
        text = await reports.build_weekly_text(user)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb.back_to_menu())

    elif data == "settings":
        await q.edit_message_text("⚙️ Настройки:", reply_markup=kb.settings_menu(user))

    elif data == "set_goal":
        context.user_data["awaiting"] = "goal"
        await q.edit_message_text("🎯 Пришли новое число цели (ккал/день):")

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
        await q.edit_message_text("🌍 Часовой пояс:", reply_markup=kb.tz_menu())
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
