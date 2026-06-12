"""Монетизация через Telegram Stars: лимиты, подписка, промокоды.

Содержит:
  * access-гейт (сколько ИИ-анализов осталось бесплатно / есть ли Premium);
  * выставление инвойса в звёздах (валюта XTR) и обработку платежа;
  * команды /premium, /promo, /terms, /paysupport.
"""
import datetime as dt
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

import config
import db

log = logging.getLogger("calbot.payments")

PREMIUM_PAYLOAD = "premium_sub"


# ----------------------------------------------------------------- access-гейт

def is_premium(user, now: dt.datetime = None) -> bool:
    now = now or dt.datetime.now(dt.timezone.utc)
    pu = user["premium_until"]
    return bool(pu and pu > now)


def free_used(user, today: dt.date) -> int:
    if user["ai_count_date"] == today:
        return user["ai_count_today"]
    return 0


def access_mode(user, today: dt.date) -> str:
    """Каким способом пройдёт следующий ИИ-анализ: unlimited | premium | credit | free | blocked."""
    if not config.MONETIZATION_ENABLED:
        return "unlimited"
    if is_premium(user):
        return "premium"
    if user["credits"] > 0:
        return "credit"
    if free_used(user, today) < config.FREE_DAILY_AI:
        return "free"
    return "blocked"


async def consume(user_id: int, mode: str, today: dt.date) -> None:
    """Списать ресурс ПОСЛЕ успешного анализа (premium — бесплатно)."""
    if mode == "credit":
        await db.consume_credit(user_id)
    elif mode == "free":
        await db.bump_free_usage(user_id, today)


def remaining_text(user, today: dt.date) -> str:
    if not config.MONETIZATION_ENABLED:
        return "Сейчас все функции бесплатны и без лимитов."
    if is_premium(user):
        return "Premium активен — безлимит."
    left = max(0, config.FREE_DAILY_AI - free_used(user, today))
    extra = f" + {user['credits']} кредитов" if user["credits"] else ""
    return f"Сегодня осталось бесплатных анализов: {left}/{config.FREE_DAILY_AI}{extra}."


def paywall_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"⭐ Premium — {config.SUBSCRIPTION_PRICE_STARS}★/мес", callback_data="buy_premium")],
        [InlineKeyboardButton("🎟 Ввести промокод", callback_data="enter_promo")],
    ])


async def send_paywall(update: Update) -> None:
    msg = update.effective_message
    await msg.reply_text(
        "🚫 Бесплатный дневной лимит исчерпан.\n\n"
        f"Оформи *Premium* за {config.SUBSCRIPTION_PRICE_STARS}★ на "
        f"{config.SUBSCRIPTION_DAYS} дней — безлимитные анализы еды.\n"
        "Или активируй промокод.",
        parse_mode="Markdown",
        reply_markup=paywall_keyboard(),
    )


# --------------------------------------------------------------- инвойс/оплата

async def send_premium_invoice(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=f"Premium — {config.SUBSCRIPTION_DAYS} дней",
        description="Безлимитные ИИ-анализы калорий по фото и описанию, без дневных ограничений.",
        payload=PREMIUM_PAYLOAD,
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=f"Premium {config.SUBSCRIPTION_DAYS} дн.",
                             amount=config.SUBSCRIPTION_PRICE_STARS)],
        # provider_token не нужен для цифровых товаров (оплата звёздами).
    )


async def on_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.pre_checkout_query
    if q.invoice_payload == PREMIUM_PAYLOAD:
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message="Неизвестный товар, оплата отменена.")


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sp = update.message.successful_payment
    uid = update.effective_user.id
    log.info("Оплата получена: user=%s payload=%s charge=%s amount=%s",
             uid, sp.invoice_payload, sp.telegram_payment_charge_id, sp.total_amount)
    try:
        await db.record_payment(uid, sp.invoice_payload, sp.total_amount,
                                sp.telegram_payment_charge_id)
    except Exception:
        log.exception("Не удалось записать платёж в БД")
    if sp.invoice_payload == PREMIUM_PAYLOAD:
        await db.grant_premium_days(uid, config.SUBSCRIPTION_DAYS)
        user = await db.get_user(uid)
        until = user["premium_until"].strftime("%d.%m.%Y")
        await update.message.reply_text(
            f"✅ Спасибо! *Premium* активен до *{until}*. Анализы теперь без лимита 🎉",
            parse_mode="Markdown")


# ------------------------------------------------------------------ команды

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await db.ensure_user(uid, update.effective_user.username)
    if not config.MONETIZATION_ENABLED:
        await update.message.reply_text("Сейчас все функции бесплатны 🎉 Оплата отключена.")
        return
    user = await db.get_user(uid)
    today = dt.datetime.now(dt.timezone.utc).date()
    if is_premium(user):
        until = user["premium_until"].strftime("%d.%m.%Y")
        await update.message.reply_text(
            f"⭐ Premium активен до *{until}*.", parse_mode="Markdown")
        return
    await update.message.reply_text(
        f"{remaining_text(user, today)}\n\n"
        f"*Premium* — {config.SUBSCRIPTION_PRICE_STARS}★ на {config.SUBSCRIPTION_DAYS} дней, "
        "безлимитные ИИ-анализы.",
        parse_mode="Markdown",
        reply_markup=paywall_keyboard(),
    )


async def apply_promo(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    uid = update.effective_user.id
    code = code.strip().upper()
    today = dt.datetime.now(dt.timezone.utc).date()
    res = await db.redeem_promo(uid, code, today)
    if not res["ok"]:
        await update.effective_message.reply_text(f"❌ {res['reason']}")
        return
    if res["kind"] == "premium_days":
        await db.grant_premium_days(uid, res["value"])
        await update.effective_message.reply_text(
            f"🎉 Промокод активирован: +{res['value']} дней Premium!")
    elif res["kind"] == "credits":
        await db.add_credits(uid, res["value"])
        await update.effective_message.reply_text(
            f"🎉 Промокод активирован: +{res['value']} анализов!")


async def promo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    if context.args:
        await apply_promo(update, context, context.args[0])
    else:
        context.user_data["awaiting"] = "promo"
        await update.message.reply_text("🎟 Пришли промокод одним сообщением:")


async def terms_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📄 *Условия использования*\n\n"
        "Бот оценивает калорийность по фото/описанию с помощью ИИ — это приблизительная "
        "оценка, не медицинская рекомендация. Premium даёт безлимитные ИИ-анализы на "
        f"{config.SUBSCRIPTION_DAYS} дней. Оплата — Telegram Stars. Возврат возможен через "
        "поддержку. Оформляя покупку, вы соглашаетесь с этими условиями.\n\n"
        f"Поддержка: {config.SUPPORT_CONTACT} или /paysupport.",
        parse_mode="Markdown")


async def addpromo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создать промокод (только для админов).

    /addpromo КОД premium_days|credits ЗНАЧЕНИЕ [макс_активаций] [ГГГГ-ММ-ДД]
    Примеры:
      /addpromo WELCOME premium_days 7 100
      /addpromo BONUS10 credits 10 50 2026-12-31
    """
    uid = update.effective_user.id
    if uid not in config.ADMIN_IDS:
        await update.message.reply_text("Команда доступна только администратору.")
        return
    args = context.args
    if len(args) < 3 or args[1] not in ("premium_days", "credits"):
        await update.message.reply_text(
            "Формат: /addpromo КОД premium_days|credits ЗНАЧЕНИЕ [макс_активаций] [ГГГГ-ММ-ДД]")
        return
    code = args[0].strip().upper()
    kind = args[1]
    try:
        value = int(args[2])
        max_uses = int(args[3]) if len(args) >= 4 else 1
        expires = dt.date.fromisoformat(args[4]) if len(args) >= 5 else None
    except ValueError:
        await update.message.reply_text("Числа/дата заданы неверно.")
        return
    await db.create_promo(code, kind, value, max_uses, expires)
    exp = f", до {expires}" if expires else ""
    await update.message.reply_text(
        f"✅ Промокод *{code}* создан: {kind}={value}, активаций {max_uses}{exp}.",
        parse_mode="Markdown")


async def paysupport_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛟 *Поддержка по платежам*\n\n"
        "Если есть вопрос по оплате или нужен возврат — напиши "
        f"{config.SUPPORT_CONTACT}, укажи дату и сумму платежа. Ответим как можно скорее.\n\n"
        "_Поддержка Telegram не помогает с покупками внутри бота._",
        parse_mode="Markdown")
