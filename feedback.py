"""Формы обратной связи в боте: баг-репорт и «неверные калории».

Правила: в текстовых полях запрещены ссылки; из вложений принимаются только
фото и видео (файлы/документы нельзя).

Состояния (хранятся в context.user_data["awaiting"]):
  bug_desc → bug_media
  cal_desc → cal_value → cal_media
Собранные данные — в context.user_data["fb"].
"""
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db

log = logging.getLogger("calbot.feedback")

TEXT_STATES = {"bug_desc", "bug_media", "cal_desc", "cal_value", "cal_media"}
MEDIA_STATES = {"bug_media", "cal_media"}

_LINK_RE = re.compile(r"(https?://|www\.|t\.me/|@[A-Za-z0-9_]{3,})", re.IGNORECASE)
_SKIP_WORDS = {"пропустить", "скип", "skip", "нет", "-", "не знаю", "незнаю"}


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐞 Сообщить о баге", callback_data="fb_bug")],
        [InlineKeyboardButton("🍽 Неверные калории", callback_data="fb_cal")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="menu")],
    ])


# ----------------------------------------------------------------- запуск

async def open_menu(q) -> None:
    await q.edit_message_text(
        "🛟 *Обратная связь*\n\nВыбери, о чём сообщить:",
        parse_mode="Markdown", reply_markup=menu_keyboard())


async def start_bug(update, context) -> None:
    context.user_data["awaiting"] = "bug_desc"
    context.user_data["fb"] = {}
    await update.effective_message.reply_text(
        "🐞 Опиши проблему текстом: что произошло и что ожидалось.\n"
        "_Ссылки и файлы отправлять нельзя — только текст, а затем фото/видео._",
        parse_mode="Markdown")


async def start_cal(update, context) -> None:
    context.user_data["awaiting"] = "cal_desc"
    context.user_data["fb"] = {}
    await update.effective_message.reply_text(
        "🍽 Опиши блюдо и что не так с калориями (например: «бот посчитал салат как "
        "800 ккал, это слишком много»).\n_Без ссылок и файлов._",
        parse_mode="Markdown")


# --------------------------------------------------------------- обработка

def _has_link(text: str) -> bool:
    return bool(_LINK_RE.search(text))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    awaiting = context.user_data.get("awaiting")
    fb = context.user_data.setdefault("fb", {})
    text = text.strip()

    # --- баг-репорт ---
    if awaiting == "bug_desc":
        if _has_link(text):
            await update.message.reply_text("🚫 Ссылки нельзя. Опиши проблему словами.")
            return
        if len(text) < 5:
            await update.message.reply_text("Слишком коротко — опиши подробнее.")
            return
        fb["description"] = text[:2000]
        context.user_data["awaiting"] = "bug_media"
        await update.message.reply_text(
            "📎 Прикрепи скриншот или видео проблемы — или напиши «пропустить».")
        return

    if awaiting == "bug_media":
        if text.lower() in _SKIP_WORDS:
            await _save_bug(update, context, None, None)
            return
        await update.message.reply_text(
            "Пришли *фото* или *видео* проблемы, либо напиши «пропустить». "
            "Файлы и ссылки не принимаются.", parse_mode="Markdown")
        return

    # --- неверные калории ---
    if awaiting == "cal_desc":
        if _has_link(text):
            await update.message.reply_text("🚫 Ссылки нельзя. Опиши словами.")
            return
        if len(text) < 5:
            await update.message.reply_text("Слишком коротко — опиши подробнее.")
            return
        fb["dish"] = text[:2000]
        context.user_data["awaiting"] = "cal_value"
        await update.message.reply_text(
            "Сколько калорий должно быть на самом деле? Пришли число или «не знаю».")
        return

    if awaiting == "cal_value":
        if text.lower() in _SKIP_WORDS:
            fb["correct_kcal"] = None
        else:
            m = re.search(r"\d{1,5}", text)
            if not m:
                await update.message.reply_text("Введи число калорий или «не знаю».")
                return
            fb["correct_kcal"] = int(m.group())
        context.user_data["awaiting"] = "cal_media"
        await update.message.reply_text(
            "📎 Можешь приложить фото блюда — или напиши «пропустить».")
        return

    if awaiting == "cal_media":
        if text.lower() in _SKIP_WORDS:
            await _save_cal(update, context, None, None)
            return
        await update.message.reply_text(
            "Пришли *фото* блюда либо напиши «пропустить».", parse_mode="Markdown")
        return


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       media_type: str, file_id: str) -> None:
    awaiting = context.user_data.get("awaiting")
    if awaiting == "bug_media":
        await _save_bug(update, context, media_type, file_id)
    elif awaiting == "cal_media":
        await _save_cal(update, context, media_type, file_id)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Документы/файлы запрещены в формах обратной связи."""
    if context.user_data.get("awaiting") in MEDIA_STATES:
        await update.message.reply_text(
            "🚫 Файлы отправлять нельзя. Пришли фото/видео или напиши «пропустить».")


# ------------------------------------------------------------------ сохранение

async def _save_bug(update, context, media_type, file_id) -> None:
    fb = context.user_data.get("fb", {})
    u = update.effective_user
    rid = await db.add_bug_report(u.id, u.username, fb.get("description", ""),
                                  media_type, file_id)
    context.user_data.pop("awaiting", None)
    context.user_data.pop("fb", None)
    await update.effective_message.reply_text(
        f"✅ Спасибо! Баг-репорт #{rid} принят. Мы разберёмся.")


async def _save_cal(update, context, media_type, file_id) -> None:
    fb = context.user_data.get("fb", {})
    u = update.effective_user
    rid = await db.add_calorie_feedback(u.id, u.username, fb.get("dish", ""),
                                        fb.get("correct_kcal"), media_type, file_id)
    context.user_data.pop("awaiting", None)
    context.user_data.pop("fb", None)
    await update.effective_message.reply_text(
        f"✅ Спасибо! Замечание #{rid} принято — поможет улучшить распознавание.")
