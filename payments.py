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

import byok
import config
import db

log = logging.getLogger("calbot.payments")

PREMIUM_PAYLOAD = "premium_sub"
MACROS_PAYLOAD = "premium_macros_sub"   # подписка Premium+КБЖУ
PACK_PREFIX = "credits:"   # payload пакета кредитов: "credits:<n>"

# Рантайм-настройки (settings в БД), меняются из админки и кэшируются в процессе.
SETTING_MONETIZATION = "monetization_enabled"
SETTING_FREE_DAILY = "free_daily_ai"
SETTING_FREE_PERIOD = "free_period_days"
SETTING_MACROS_TIER = "macros_tier_enabled"
SETTING_MACROS_PRICE = "macros_price"
_settings: dict = {}  # пустой → используем дефолты из ENV


def monetization_enabled() -> bool:
    return _settings.get("mon", config.MONETIZATION_ENABLED)


def free_daily_ai() -> int:
    return _settings.get("free_daily", config.FREE_DAILY_AI)


def free_period_days() -> int:
    return _settings.get("free_period", config.FREE_PERIOD_DAYS)


def macros_tier_enabled() -> bool:
    return _settings.get("macros_tier", config.MACROS_TIER_ENABLED)


def macros_price() -> int:
    return _settings.get("macros_price", config.SUBSCRIPTION_MACROS_PRICE_STARS)


def _truthy(v):
    return v is not None and v.strip() in ("1", "true", "yes", "on")


async def refresh_settings() -> None:
    """Подтянуть настройки из БД в кэш (старт + по таймеру)."""
    global _settings
    try:
        mon = await db.get_setting(SETTING_MONETIZATION)
        fd = await db.get_setting(SETTING_FREE_DAILY)
        fp = await db.get_setting(SETTING_FREE_PERIOD)
        mt = await db.get_setting(SETTING_MACROS_TIER)
        mp = await db.get_setting(SETTING_MACROS_PRICE)
    except Exception:
        return
    s = {}
    s["mon"] = _truthy(mon) if mon is not None else config.MONETIZATION_ENABLED
    s["free_daily"] = int(fd) if (fd and fd.strip().isdigit()) else config.FREE_DAILY_AI
    s["free_period"] = int(fp) if (fp and fp.strip().isdigit()) else config.FREE_PERIOD_DAYS
    s["macros_tier"] = _truthy(mt) if mt is not None else config.MACROS_TIER_ENABLED
    s["macros_price"] = int(mp) if (mp and mp.strip().isdigit()) else config.SUBSCRIPTION_MACROS_PRICE_STARS
    _settings = s


async def refresh_settings_job(context) -> None:
    await refresh_settings()


# ----------------------------------------------------------------- access-гейт

def is_premium(user, now: dt.datetime = None) -> bool:
    now = now or dt.datetime.now(dt.timezone.utc)
    pu = user["premium_until"]
    return bool(pu and pu > now)


def free_used(user, today: dt.date) -> int:
    if user["ai_count_date"] == today:
        return user["ai_count_today"]
    return 0


def within_free_period(user, now: dt.datetime = None) -> bool:
    """В пределах ли бесплатного периода (N дней с регистрации)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    created = user.get("created_at")
    if not created:
        return True
    return (now - created) <= dt.timedelta(days=free_period_days())


def user_plan(user) -> str:
    """Текущий активный план: free | premium | premium_plus."""
    if is_premium(user) and (user.get("plan") in ("premium", "premium_plus")):
        return user["plan"]
    return "free"


def macros_enabled(user) -> bool:
    """Доступен ли КБЖУ: при выключенной монетизации — всем; иначе — только premium_plus."""
    if not macros_tier_enabled():
        return False
    if not monetization_enabled():
        return True
    return user_plan(user) == "premium_plus"


def access_mode(user, today: dt.date) -> str:
    """Каким способом пройдёт следующий ИИ-анализ:
    byok | unlimited | premium | credit | free | blocked.

    Бесплатный тариф: до free_daily_ai() анализов в день и только в течение
    первых free_period_days() дней с регистрации. Дальше — Premium/кредиты.
    """
    # Свой ключ OpenAI — всегда безлимит и за счёт пользователя.
    if byok.enabled() and user.get("openai_key_enc"):
        return "byok"
    if not monetization_enabled():
        return "unlimited"
    if is_premium(user):
        return "premium"
    if user["credits"] > 0:
        return "credit"
    if within_free_period(user) and free_used(user, today) < free_daily_ai():
        return "free"
    return "blocked"


async def consume(user_id: int, mode: str, today: dt.date) -> None:
    """Списать ресурс ПОСЛЕ успешного анализа (premium/byok/unlimited — бесплатно)."""
    if mode == "credit":
        await db.consume_credit(user_id)
    elif mode == "free":
        await db.bump_free_usage(user_id, today)


def ai_params(user, mode: str):
    """(model, api_key) для ai.estimate_food в зависимости от режима доступа."""
    if mode == "byok":
        return config.OPENAI_MODEL, byok.decrypt(user.get("openai_key_enc"))
    if mode == "free":
        return config.OPENAI_MODEL_FREE, None
    return config.OPENAI_MODEL, None   # premium | credit | unlimited


def remaining_text(user, today: dt.date) -> str:
    if not monetization_enabled():
        return "Сейчас все функции бесплатны и без лимитов."
    if is_premium(user):
        return "Premium активен — безлимит."
    if user["credits"] > 0:
        suffix = f" Доступно кредитов: {user['credits']}."
    else:
        suffix = ""
    if not within_free_period(user):
        return (f"Бесплатный период ({free_period_days()} дн.) закончился — "
                f"оформи Premium для продолжения.{suffix}")
    left = max(0, free_daily_ai() - free_used(user, today))
    return (f"Сегодня осталось бесплатных анализов: {left}/{free_daily_ai()}."
            f" Бесплатно — первые {free_period_days()} дней.{suffix}")


def paywall_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"⭐ Premium — {config.SUBSCRIPTION_PRICE_STARS}★/мес", callback_data="buy_premium")]]
    if macros_tier_enabled():
        rows.append([InlineKeyboardButton(
            f"🥗 Premium+КБЖУ — {macros_price()}★/мес", callback_data="buy_premium_macros")])
    for credits, stars in config.CREDIT_PACKS:
        rows.append([InlineKeyboardButton(
            f"📦 {credits} анализов — {stars}★", callback_data=f"buy_pack:{credits}")])
    rows.append([InlineKeyboardButton("🎟 Ввести промокод", callback_data="enter_promo")])
    return InlineKeyboardMarkup(rows)


async def send_paywall(update: Update, reason: str = "limit") -> None:
    msg = update.effective_message
    if reason == "period":
        head = (f"🚫 Бесплатный период ({free_period_days()} дн.) закончился.\n\n")
    else:
        head = (f"🚫 Дневной лимит бесплатных анализов исчерпан "
                f"({free_daily_ai()}/день).\n\n")
    await msg.reply_text(
        head +
        f"Оформи *Premium* за {config.SUBSCRIPTION_PRICE_STARS}★/мес — безлимитные "
        "анализы еды. Или возьми пакет анализов / активируй промокод.",
        parse_mode="Markdown",
        reply_markup=paywall_keyboard(),
    )


# --------------------------------------------------------------- инвойс/оплата

async def send_premium_invoice(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Нативная продлеваемая подписка Telegram Stars (Telegram сам списывает каждые 30 дней)."""
    link = await context.bot.create_invoice_link(
        title="Premium (автопродление)",
        description="Безлимитные ИИ-анализы калорий по фото и описанию. "
                    "Списывается раз в 30 дней, отменить можно в любой момент.",
        payload=PREMIUM_PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice(label="Premium / мес", amount=config.SUBSCRIPTION_PRICE_STARS)],
        subscription_period=config.SUBSCRIPTION_PERIOD_SEC,  # ровно 30 дней
    )
    await context.bot.send_message(
        chat_id,
        f"⭐ *Premium* — {config.SUBSCRIPTION_PRICE_STARS}★ в месяц, автопродление.\n"
        "Отменить можно в Telegram → Настройки → Подписки или командой /cancelsub.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
            f"Оформить за {config.SUBSCRIPTION_PRICE_STARS}★/мес", url=link)]]),
    )


async def send_macros_invoice(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подписка Premium+КБЖУ с автопродлением."""
    price = macros_price()
    link = await context.bot.create_invoice_link(
        title="Premium+КБЖУ (автопродление)",
        description="Всё из Premium + белки/жиры/углеводы по каждому приёму, цели по "
                    "макросам и советы по их дефициту. Списывается раз в 30 дней.",
        payload=MACROS_PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice(label="Premium+КБЖУ / мес", amount=price)],
        subscription_period=config.SUBSCRIPTION_PERIOD_SEC,
    )
    await context.bot.send_message(
        chat_id,
        f"🥗 *Premium+КБЖУ* — {price}★ в месяц, автопродление.\n"
        "Отменить можно в Telegram → Настройки → Подписки или командой /cancelsub.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
            f"Оформить за {price}★/мес", url=link)]]),
    )


async def send_pack_invoice(chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                            credits: int, stars: int) -> None:
    """Разовый пакет анализов (без автопродления)."""
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=f"Пакет {credits} анализов",
        description=f"{credits} ИИ-анализов еды. Не сгорают по времени, тратятся "
                    "после бесплатного дневного лимита.",
        payload=f"{PACK_PREFIX}{credits}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{credits} анализов", amount=stars)],
    )


async def on_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.pre_checkout_query
    p = q.invoice_payload
    if p in (PREMIUM_PAYLOAD, MACROS_PAYLOAD) or p.startswith(PACK_PREFIX):
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message="Неизвестный товар, оплата отменена.")


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sp = update.message.successful_payment
    uid = update.effective_user.id
    payload = sp.invoice_payload
    charge_id = sp.telegram_payment_charge_id
    log.info("Оплата: user=%s payload=%s charge=%s amount=%s recurring=%s",
             uid, payload, charge_id, sp.total_amount, getattr(sp, "is_recurring", None))

    # идемпотентность: один charge_id обрабатываем один раз
    is_new = await db.record_payment(uid, payload, sp.total_amount, charge_id)
    if not is_new:
        return

    if payload in (PREMIUM_PAYLOAD, MACROS_PAYLOAD):
        plan = "premium_plus" if payload == MACROS_PAYLOAD else "premium"
        await db.set_plan(uid, plan)
        exp = getattr(sp, "subscription_expiration_date", None)
        if exp:
            await db.set_premium_until(uid, exp)
        else:
            await db.grant_premium_days(uid, config.SUBSCRIPTION_DAYS)
        # запоминаем charge_id первого платежа (нужен для отмены)
        user = await db.get_user(uid)
        if getattr(sp, "is_first_recurring", False) or not user["sub_charge_id"]:
            await db.set_sub_charge_id(uid, charge_id)
        user = await db.get_user(uid)
        until = user["premium_until"].strftime("%d.%m.%Y") if user["premium_until"] else "—"
        name = "Premium+КБЖУ" if plan == "premium_plus" else "Premium"
        if getattr(sp, "is_recurring", False) and not getattr(sp, "is_first_recurring", False):
            await update.message.reply_text(
                f"🔄 Подписка продлена. *{name}* активен до *{until}*.", parse_mode="Markdown")
        else:
            extra = " Теперь в анализах и отчётах есть Б/Ж/У 🥗" if plan == "premium_plus" else ""
            await update.message.reply_text(
                f"✅ Спасибо! *{name}* активен до *{until}* (автопродление). "
                f"Анализы без лимита 🎉{extra}", parse_mode="Markdown")

    elif payload.startswith(PACK_PREFIX):
        n = int(payload[len(PACK_PREFIX):])
        await db.add_credits(uid, n)
        await update.message.reply_text(
            f"✅ Спасибо! Начислено *{n}* анализов. Тратятся после дневного лимита.",
            parse_mode="Markdown")


# ------------------------------------------------------------------ команды

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await db.ensure_user(uid, update.effective_user.username)
    if not monetization_enabled():
        await update.message.reply_text("Сейчас все функции бесплатны 🎉 Оплата отключена.")
        return
    user = await db.get_user(uid)
    today = dt.datetime.now(dt.timezone.utc).date()
    if is_premium(user):
        until = user["premium_until"].strftime("%d.%m.%Y")
        await update.message.reply_text(
            f"⭐ Premium активен до *{until}* (автопродление).\n"
            "Отменить автосписание — /cancelsub.", parse_mode="Markdown")
        return
    await update.message.reply_text(
        f"{remaining_text(user, today)}\n\n"
        f"*Premium* — {config.SUBSCRIPTION_PRICE_STARS}★/мес (автопродление), безлимитные "
        "ИИ-анализы. Или разовый пакет анализов.",
        parse_mode="Markdown",
        reply_markup=paywall_keyboard(),
    )


async def cancelsub_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user = await db.get_user(uid)
    if not user or not user["sub_charge_id"]:
        await update.message.reply_text("Активной автоподписки нет.")
        return
    try:
        await context.bot.edit_user_star_subscription(
            user_id=uid, telegram_payment_charge_id=user["sub_charge_id"], is_canceled=True)
        await update.message.reply_text(
            "✅ Автопродление отменено. Premium действует до конца оплаченного периода.")
    except Exception as e:
        log.exception("cancelsub: %s", e)
        await update.message.reply_text(
            "Не получилось отменить через бота. Открой Telegram → Настройки → Подписки.")


async def refund_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.message.reply_text("Команда только для администратора.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /refund <user_id> <charge_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id должен быть числом.")
        return
    charge = context.args[1]
    try:
        await context.bot.refund_star_payment(
            user_id=target, telegram_payment_charge_id=charge)
    except Exception as e:
        await update.message.reply_text(f"Возврат не выполнен: {e}")
        return
    await db.mark_refunded(charge)
    p = await db.get_payment(charge)
    if p and p["payload"] == PREMIUM_PAYLOAD:
        await db.revoke_premium(target)
    await update.message.reply_text(f"✅ Возврат по {charge} выполнен (user {target}).")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.message.reply_text("Команда только для администратора.")
        return
    s = await db.admin_stats()
    usd = round(s["stars_30d"] * 0.013, 2)
    await update.message.reply_text(
        "📈 *Статистика*\n"
        f"Пользователей всего: {s['total_users']}\n"
        f"Новых за 7 дней: {s['new_7d']}\n"
        f"Активных Premium: {s['premium_active']} "
        f"(базовый {s['premium_basic_active']} / +КБЖУ {s['premium_plus_active']})\n"
        f"Платежей за 30 дней: {s['payments_30d']}\n"
        f"Выручка за 30 дней: {s['stars_30d']}★ (≈ ${usd})\n"
        f"  • Premium: {s['stars_30d_basic']}★ · Premium+КБЖУ: {s['stars_30d_plus']}★\n"
        f"Активаций промокодов: {s['promo_redemptions']}",
        parse_mode="Markdown")


async def setkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not byok.enabled():
        await update.message.reply_text("Свой ключ сейчас не поддерживается.")
        return
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    if not context.args:
        await update.message.reply_text("Использование: /setkey sk-...")
        return
    key = context.args[0].strip()
    # сразу удаляем сообщение с ключом из чата
    try:
        await update.message.delete()
    except Exception:
        pass
    notice = await context.bot.send_message(update.effective_chat.id, "Проверяю ключ…")
    if not await byok.validate_key(key):
        await notice.edit_text("❌ Ключ не прошёл проверку. Убедись, что он рабочий.")
        return
    await db.set_openai_key(update.effective_user.id, byok.encrypt(key))
    await notice.edit_text(
        "✅ Ключ сохранён (шифрованно). Анализы теперь безлимитны и за твой счёт OpenAI.\n"
        "Удалить ключ — /delkey.")


async def delkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.clear_openai_key(update.effective_user.id)
    await update.message.reply_text("Ключ удалён. Бот снова работает на общих условиях.")


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
        await db.set_plan(uid, "premium")
        await update.effective_message.reply_text(
            f"🎉 Промокод активирован: +{res['value']} дней Premium!")
    elif res["kind"] == "premium_plus_days":
        await db.grant_premium_days(uid, res["value"])
        await db.set_plan(uid, "premium_plus")
        await update.effective_message.reply_text(
            f"🎉 Промокод активирован: +{res['value']} дней Premium+КБЖУ!")
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
