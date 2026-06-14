"""Формы обратной связи в боте: баг-репорт и «неверные калории».

Правила: в текстовых полях запрещены ссылки; из вложений принимаются только
фото и видео (файлы/документы нельзя). Тексты — через i18n (RU/EN).
"""
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
from i18n import t

log = logging.getLogger("calbot.feedback")

TEXT_STATES = {"bug_desc", "bug_media", "cal_desc", "cal_value", "cal_media"}
MEDIA_STATES = {"bug_media", "cal_media"}

_LINK_RE = re.compile(r"(https?://|www\.|t\.me/|@[A-Za-z0-9_]{3,})", re.IGNORECASE)
_SKIP_WORDS = {"пропустить", "скип", "skip", "нет", "no", "-", "не знаю", "незнаю",
               "don't know", "dont know", "idk"}


async def _lang(uid) -> str:
    u = await db.get_user(uid)
    return u["lang"] if u else "ru"


def menu_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("fb_bug", lang), callback_data="fb_bug")],
        [InlineKeyboardButton(t("fb_cal", lang), callback_data="fb_cal")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


# ----------------------------------------------------------------- запуск

async def open_menu(q, lang: str = "ru") -> None:
    await q.edit_message_text(t("fb_title", lang), parse_mode="Markdown",
                              reply_markup=menu_keyboard(lang))


async def start_bug(update, context, lang: str = "ru") -> None:
    context.user_data["awaiting"] = "bug_desc"
    context.user_data["fb"] = {}
    await update.effective_message.reply_text(t("fb_bug_desc", lang), parse_mode="Markdown")


async def start_cal(update, context, lang: str = "ru") -> None:
    context.user_data["awaiting"] = "cal_desc"
    context.user_data["fb"] = {}
    await update.effective_message.reply_text(t("fb_cal_desc", lang), parse_mode="Markdown")


# --------------------------------------------------------------- обработка

def _has_link(text: str) -> bool:
    return bool(_LINK_RE.search(text))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    awaiting = context.user_data.get("awaiting")
    fb = context.user_data.setdefault("fb", {})
    text = text.strip()
    lang = await _lang(update.effective_user.id)

    if awaiting == "bug_desc":
        if _has_link(text):
            await update.message.reply_text(t("fb_no_links", lang)); return
        if len(text) < 5:
            await update.message.reply_text(t("fb_short", lang)); return
        fb["description"] = text[:2000]
        context.user_data["awaiting"] = "bug_media"
        await update.message.reply_text(t("fb_bug_media", lang))
        return

    if awaiting == "bug_media":
        if text.lower() in _SKIP_WORDS:
            await _save_bug(update, context, None, None, lang)
        else:
            await update.message.reply_text(t("fb_need_photo", lang))
        return

    if awaiting == "cal_desc":
        if _has_link(text):
            await update.message.reply_text(t("fb_no_links", lang)); return
        if len(text) < 5:
            await update.message.reply_text(t("fb_short", lang)); return
        fb["dish"] = text[:2000]
        context.user_data["awaiting"] = "cal_value"
        await update.message.reply_text(t("fb_cal_value", lang))
        return

    if awaiting == "cal_value":
        if text.lower() in _SKIP_WORDS:
            fb["correct_kcal"] = None
        else:
            m = re.search(r"\d{1,5}", text)
            if not m:
                await update.message.reply_text(t("fb_cal_value", lang)); return
            fb["correct_kcal"] = int(m.group())
        context.user_data["awaiting"] = "cal_media"
        await update.message.reply_text(t("fb_cal_media", lang))
        return

    if awaiting == "cal_media":
        if text.lower() in _SKIP_WORDS:
            await _save_cal(update, context, None, None, lang)
        else:
            await update.message.reply_text(t("fb_need_photo", lang))
        return


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       media_type: str, file_id: str) -> None:
    awaiting = context.user_data.get("awaiting")
    lang = await _lang(update.effective_user.id)
    if awaiting == "bug_media":
        await _save_bug(update, context, media_type, file_id, lang)
    elif awaiting == "cal_media":
        await _save_cal(update, context, media_type, file_id, lang)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Документы/файлы запрещены в формах обратной связи."""
    if context.user_data.get("awaiting") in MEDIA_STATES:
        lang = await _lang(update.effective_user.id)
        await update.message.reply_text(t("fb_no_files", lang))


# ------------------------------------------------------------------ сохранение

async def _save_bug(update, context, media_type, file_id, lang="ru") -> None:
    fb = context.user_data.get("fb", {})
    u = update.effective_user
    rid = await db.add_bug_report(u.id, u.username, fb.get("description", ""),
                                  media_type, file_id)
    context.user_data.pop("awaiting", None)
    context.user_data.pop("fb", None)
    await update.effective_message.reply_text(t("fb_bug_done", lang, id=rid))


async def _save_cal(update, context, media_type, file_id, lang="ru") -> None:
    fb = context.user_data.get("fb", {})
    u = update.effective_user
    rid = await db.add_calorie_feedback(u.id, u.username, fb.get("dish", ""),
                                        fb.get("correct_kcal"), media_type, file_id)
    context.user_data.pop("awaiting", None)
    context.user_data.pop("fb", None)
    await update.effective_message.reply_text(t("fb_cal_done", lang, id=rid))
