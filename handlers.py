"""Хендлеры Telegram: онбординг, приём еды (фото/текст/число), меню, настройки."""
import datetime as dt
import re

import pytz
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

import ai
import db
import keyboards as kb
import reports

# Текст-«число калорий»: «350», «+200», «350 ккал»
_NUM_RE = re.compile(r"^\+?\s*(\d{1,5})\s*(ккал|kcal|кал|cal)?$", re.IGNORECASE)

WELCOME = (
    "👋 Привет! Я *Жиромер* — помогу считать калории.\n\n"
    "Что я умею:\n"
    "• 📷 Пришли *фото еды* — оценю калорийность.\n"
    "• 📷 + подпись — оценю точнее (например: «куриная грудка 200 г»).\n"
    "• ✍️ Просто текст блюда — оценю по описанию.\n"
    "• 🔢 Просто число (напр. `350`) — добавлю столько ккал вручную.\n\n"
    "В конце дня пришлю дневной отчёт, раз в неделю — недельный.\n"
    "Меню настроек — /menu."
)


def _today(user) -> dt.date:
    return dt.datetime.now(pytz.timezone(user["timezone"])).date()


# ------------------------------------------------------------------- команды

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await db.ensure_user(u.id, u.username)
    user = await db.get_user(u.id)
    reports.schedule_user(context.application, user)
    await update.message.reply_text(WELCOME, parse_mode="Markdown")
    if not user["goal"]:
        context.user_data["awaiting"] = "goal"
        await update.message.reply_text(
            "🎯 Для начала укажи *цель по калориям на день* (число, напр. 2000):",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Главное меню:", reply_markup=kb.main_menu())


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text("Главное меню:", reply_markup=kb.main_menu())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


# ----------------------------------------------------- логирование приёма пищи

async def _log_and_reply(update, context, calories: int, item: str):
    user = await db.get_user(update.effective_user.id)
    day = _today(user)
    await db.add_entry(user["user_id"], calories, item, day)
    total = await db.day_total(user["user_id"], day)
    goal = user["goal"] or 0

    msg = f"✅ Записал: *{item}* — {calories} ккал.\n"
    if goal:
        remaining = goal - total
        bar = reports._progress_bar(total, goal)
        msg += f"Сегодня: *{total}* / {goal} ккал\n{bar}\n"
        if remaining >= 0:
            msg += f"Осталось *{remaining}* ккал."
        else:
            msg += f"⚠️ Превышение на *{-remaining}* ккал."
    else:
        msg += f"Сегодня всего: *{total}* ккал. Цель не задана — /menu."
    await update.message.reply_text(msg, parse_mode="Markdown")

    # совет, если близко к цели (≥80%) или превышение
    if goal and total >= 0.8 * goal:
        entries = await db.day_entries(user["user_id"], day)
        names = [e["item"] for e in entries if e["item"]]
        try:
            advice = await ai.diet_advice(goal, total, names)
            await update.message.reply_text(f"💡 {advice}")
        except Exception:
            pass


# -------------------------------------------------------------- приём фото

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    img_bytes = bytes(await tg_file.download_as_bytearray())
    caption = update.message.caption
    try:
        result = await ai.estimate_food(image_bytes=img_bytes, caption=caption)
    except Exception:
        await update.message.reply_text(
            "Не удалось распознать фото 😕 Попробуй ещё раз или пришли описание текстом.")
        return
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

    # ручное добавление калорий числом
    m = _NUM_RE.match(text)
    if m:
        await _log_and_reply(update, context, int(m.group(1)), "ручной ввод")
        return

    # иначе — описание блюда, оцениваем через ИИ
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        result = await ai.estimate_food(caption=text)
    except Exception:
        await update.message.reply_text("Не получилось оценить 😕 Попробуй иначе или пришли фото.")
        return
    item = ", ".join(i.get("name", "") for i in result.get("items", [])) or text[:50]
    await _log_and_reply(update, context, result["calories"], item)
    note = result.get("note", "")
    if note:
        await update.message.reply_text(f"🔎 {note}")


# --------------------------------------------------------- инлайн-кнопки

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id
    user = await db.get_user(uid)

    if data == "menu":
        await q.edit_message_text("Главное меню:", reply_markup=kb.main_menu())

    elif data == "today":
        text = await reports.build_daily_text(user)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb.back_to_menu())

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
