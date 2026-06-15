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
from i18n import t

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
SETTING_REF_ENABLED = "referral_enabled"
SETTING_REF_DAYS = "referral_reward_days"
SETTING_REF_NEEDED = "referral_friends_needed"
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


def referral_enabled() -> bool:
    return _settings.get("ref_enabled", config.REFERRAL_ENABLED)


def referral_reward_days() -> int:
    return _settings.get("ref_days", config.REFERRAL_REWARD_DAYS)


def referral_friends_needed() -> int:
    return max(1, _settings.get("ref_needed", config.REFERRAL_FRIENDS_NEEDED))


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
        re_ = await db.get_setting(SETTING_REF_ENABLED)
        rd = await db.get_setting(SETTING_REF_DAYS)
        rn = await db.get_setting(SETTING_REF_NEEDED)
    except Exception:
        return
    s = {}
    s["mon"] = _truthy(mon) if mon is not None else config.MONETIZATION_ENABLED
    s["free_daily"] = int(fd) if (fd and fd.strip().isdigit()) else config.FREE_DAILY_AI
    s["free_period"] = int(fp) if (fp and fp.strip().isdigit()) else config.FREE_PERIOD_DAYS
    s["macros_tier"] = _truthy(mt) if mt is not None else config.MACROS_TIER_ENABLED
    s["macros_price"] = int(mp) if (mp and mp.strip().isdigit()) else config.SUBSCRIPTION_MACROS_PRICE_STARS
    s["ref_enabled"] = _truthy(re_) if re_ is not None else config.REFERRAL_ENABLED
    s["ref_days"] = int(rd) if (rd and rd.strip().isdigit()) else config.REFERRAL_REWARD_DAYS
    s["ref_needed"] = int(rn) if (rn and rn.strip().isdigit()) else config.REFERRAL_FRIENDS_NEEDED
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
    lang = user["lang"]
    if not monetization_enabled():
        return t("free_all", lang)
    if is_premium(user):
        return t("rem_text_premium", lang)
    suffix = t("credits_suffix", lang, n=user["credits"]) if user["credits"] > 0 else ""
    if not within_free_period(user):
        return t("rem_text_period", lang, n=free_period_days(), credits=suffix)
    left = max(0, free_daily_ai() - free_used(user, today))
    return t("rem_text_left", lang, left=left, total=free_daily_ai(),
             days=free_period_days(), credits=suffix)


def paywall_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        t("buy_premium", lang, price=config.SUBSCRIPTION_PRICE_STARS), callback_data="buy_premium")]]
    if macros_tier_enabled():
        rows.append([InlineKeyboardButton(
            t("buy_macros", lang, price=macros_price()), callback_data="buy_premium_macros")])
    for credits, stars in config.CREDIT_PACKS:
        rows.append([InlineKeyboardButton(
            t("buy_pack", lang, credits=credits, stars=stars), callback_data=f"buy_pack:{credits}")])
    rows.append([InlineKeyboardButton(t("enter_promo", lang), callback_data="enter_promo")])
    return InlineKeyboardMarkup(rows)


async def send_paywall(update: Update, reason: str = "limit") -> None:
    msg = update.effective_message
    u = await db.get_user(update.effective_user.id)
    lang = u["lang"] if u else "ru"
    head = (t("pay_period", lang, n=free_period_days()) if reason == "period"
            else t("pay_limit", lang, n=free_daily_ai()))
    await msg.reply_text(
        head + t("pay_offer", lang, price=config.SUBSCRIPTION_PRICE_STARS),
        parse_mode="Markdown", reply_markup=paywall_keyboard(lang))


# --------------------------------------------------------------- инвойс/оплата

async def _lang(uid):
    u = await db.get_user(uid)
    return u["lang"] if u else "ru"


async def send_premium_invoice(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Нативная продлеваемая подписка Telegram Stars (Telegram сам списывает каждые 30 дней)."""
    lang = await _lang(chat_id)
    price = config.SUBSCRIPTION_PRICE_STARS
    link = await context.bot.create_invoice_link(
        title="Premium",
        description="Unlimited AI food analyses by photo and text. Renews every 30 days.",
        payload=PREMIUM_PAYLOAD, currency="XTR",
        prices=[LabeledPrice(label="Premium / mo", amount=price)],
        subscription_period=config.SUBSCRIPTION_PERIOD_SEC,
    )
    await context.bot.send_message(
        chat_id, t("sub_msg", lang, price=price), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t("sub_btn", lang, price=price), url=link)]]))


async def send_macros_invoice(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подписка Premium+КБЖУ с автопродлением."""
    lang = await _lang(chat_id)
    price = macros_price()
    link = await context.bot.create_invoice_link(
        title="Premium+Macros",
        description="Everything in Premium + protein/fat/carbs per meal and macro goals. Renews every 30 days.",
        payload=MACROS_PAYLOAD, currency="XTR",
        prices=[LabeledPrice(label="Premium+Macros / mo", amount=price)],
        subscription_period=config.SUBSCRIPTION_PERIOD_SEC,
    )
    await context.bot.send_message(
        chat_id, t("sub_macros_msg", lang, price=price), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t("sub_btn", lang, price=price), url=link)]]))


async def send_pack_invoice(chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                            credits: int, stars: int) -> None:
    """Разовый пакет анализов (без автопродления)."""
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=f"{credits} analyses",
        description=f"{credits} AI food analyses. Don't expire; used after the daily free limit.",
        payload=f"{PACK_PREFIX}{credits}", currency="XTR",
        prices=[LabeledPrice(label=f"{credits} analyses", amount=stars)],
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
        lang = user["lang"]
        until = user["premium_until"].strftime("%d.%m.%Y") if user["premium_until"] else "—"
        name = "Premium+КБЖУ" if plan == "premium_plus" else "Premium"
        if getattr(sp, "is_recurring", False) and not getattr(sp, "is_first_recurring", False):
            await update.message.reply_text(t("pay_renewed", lang, name=name, date=until),
                                            parse_mode="Markdown")
        else:
            extra = t("pay_thanks_macros_extra", lang) if plan == "premium_plus" else ""
            await update.message.reply_text(
                t("pay_thanks", lang, name=name, date=until, extra=extra), parse_mode="Markdown")

    elif payload.startswith(PACK_PREFIX):
        n = int(payload[len(PACK_PREFIX):])
        await db.add_credits(uid, n)
        await update.message.reply_text(t("pack_added", await _lang(uid), n=n), parse_mode="Markdown")


# ------------------------------------------------------------------ команды

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await db.ensure_user(uid, update.effective_user.username)
    user = await db.get_user(uid)
    lang = user["lang"]
    if not monetization_enabled():
        await update.message.reply_text(t("pay_off_msg", lang))
        return
    today = dt.datetime.now(dt.timezone.utc).date()
    if is_premium(user):
        until = user["premium_until"].strftime("%d.%m.%Y")
        await update.message.reply_text(t("premium_active", lang, date=until), parse_mode="Markdown")
        return
    await update.message.reply_text(
        t("premium_offer", lang, remaining=remaining_text(user, today),
          price=config.SUBSCRIPTION_PRICE_STARS),
        parse_mode="Markdown", reply_markup=paywall_keyboard(lang))


async def cancelsub_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user = await db.get_user(uid)
    lang = user["lang"] if user else "ru"
    if not user or not user["sub_charge_id"]:
        await update.message.reply_text(t("cancel_none", lang))
        return
    try:
        await context.bot.edit_user_star_subscription(
            user_id=uid, telegram_payment_charge_id=user["sub_charge_id"], is_canceled=True)
        await update.message.reply_text(t("cancel_ok", lang))
    except Exception as e:
        log.exception("cancelsub: %s", e)
        await update.message.reply_text(t("cancel_fail", lang))


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
        f"Активаций промокодов: {s['promo_redemptions']}\n"
        f"Рефералов всего: {s['referrals_total']}",
        parse_mode="Markdown")


SETTING_ALPHA_DONE = "alpha_grant_done"
ALPHA_GIFT_DAYS = 90  # 3 месяца


async def alpha_grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Одноразовая выдача 3 мес Premium+КБЖУ всем текущим юзерам + рассылка благодарности.

    /alpha_grant ДА — подтверждение обязательно. Повторно не сработает.
    """
    import asyncio

    uid = update.effective_user.id
    if uid not in config.ADMIN_IDS:
        await update.message.reply_text("Команда только для администратора.")
        return
    if await db.get_setting(SETTING_ALPHA_DONE) == "1":
        await update.message.reply_text("⚠️ Альфа-подарок уже был разослан ранее. Повторно не выполняю.")
        return
    if not context.args or context.args[0].upper() not in ("ДА", "YES"):
        users = await db.all_users()
        await update.message.reply_text(
            f"Выдать *{ALPHA_GIFT_DAYS // 30} мес Premium+КБЖУ* и разослать благодарность "
            f"*{len(users)}* пользователям?\n\nЭто одноразовое действие. "
            "Подтверди: `/alpha_grant ДА`",
            parse_mode="Markdown")
        return
    # помечаем сразу, чтобы повторный запуск не задвоил при сбое посреди рассылки
    await db.set_setting(SETTING_ALPHA_DONE, "1")
    users = await db.all_users()
    granted = sent = 0
    for u in users:
        try:
            await db.set_plan(u["user_id"], "premium_plus")
            await db.grant_premium_days(u["user_id"], ALPHA_GIFT_DAYS)
            granted += 1
        except Exception as e:
            log.exception("alpha_grant: выдача %s: %s", u["user_id"], e)
            continue
        try:
            await context.bot.send_message(
                u["user_id"], t("alpha_gift", u["lang"] or "ru"), parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)  # ~20 сообщений/сек — в пределах лимитов Telegram
        except Exception:
            pass  # заблокировавшие бота — пропускаем (подарок всё равно начислен)
    await update.message.reply_text(
        f"✅ Готово. Выдано Premium+КБЖУ: {granted}, доставлено сообщений: {sent} из {len(users)}.\n\n"
        "Теперь включи монетизацию в админке (Настройки → тумблер).")


async def setkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(update.effective_user.id)
    if not byok.enabled():
        await update.message.reply_text(t("byok_off", lang))
        return
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    if not context.args:
        await update.message.reply_text(t("byok_usage", lang))
        return
    key = context.args[0].strip()
    # сразу удаляем сообщение с ключом из чата
    try:
        await update.message.delete()
    except Exception:
        pass
    notice = await context.bot.send_message(update.effective_chat.id, t("byok_checking", lang))
    if not await byok.validate_key(key):
        await notice.edit_text(t("byok_bad", lang))
        return
    await db.set_openai_key(update.effective_user.id, byok.encrypt(key))
    await notice.edit_text(t("byok_saved", lang))


async def delkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(update.effective_user.id)
    await db.clear_openai_key(update.effective_user.id)
    await update.message.reply_text(t("byok_deleted", lang))


async def apply_promo(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    uid = update.effective_user.id
    code = code.strip().upper()
    today = dt.datetime.now(dt.timezone.utc).date()
    lang = await _lang(uid)
    res = await db.redeem_promo(uid, code, today)
    if not res["ok"]:
        await update.effective_message.reply_text("❌ " + t(f"promo_err_{res['reason']}", lang))
        return
    if res["kind"] == "premium_days":
        await db.grant_premium_days(uid, res["value"])
        await db.set_plan(uid, "premium")
        await update.effective_message.reply_text(t("promo_premium_days", lang, n=res["value"]))
    elif res["kind"] == "premium_plus_days":
        await db.grant_premium_days(uid, res["value"])
        await db.set_plan(uid, "premium_plus")
        await update.effective_message.reply_text(t("promo_premium_plus_days", lang, n=res["value"]))
    elif res["kind"] == "credits":
        await db.add_credits(uid, res["value"])
        await update.effective_message.reply_text(t("promo_credits", lang, n=res["value"]))


async def promo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.ensure_user(update.effective_user.id, update.effective_user.username)
    if context.args:
        await apply_promo(update, context, context.args[0])
    else:
        context.user_data["awaiting"] = "promo"
        await update.message.reply_text(t("promo_prompt", await _lang(update.effective_user.id)))


async def terms_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(update.effective_user.id)
    await update.message.reply_text(
        t("terms_text", lang, days=config.SUBSCRIPTION_DAYS, support=config.SUPPORT_CONTACT),
        parse_mode="Markdown")


async def addpromo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создать промокод (только для админов).

    /addpromo КОД premium_days|premium_plus_days|credits ЗНАЧЕНИЕ [макс_активаций] [ГГГГ-ММ-ДД]
    Примеры:
      /addpromo WELCOME premium_days 7 100
      /addpromo MACROS30 premium_plus_days 30 50 2026-12-31
      /addpromo BONUS10 credits 10 50 2026-12-31
    """
    uid = update.effective_user.id
    if uid not in config.ADMIN_IDS:
        await update.message.reply_text("Команда доступна только администратору.")
        return
    args = context.args
    if len(args) < 3 or args[1] not in ("premium_days", "premium_plus_days", "credits"):
        await update.message.reply_text(
            "Формат: /addpromo КОД premium_days|premium_plus_days|credits ЗНАЧЕНИЕ "
            "[макс_активаций] [ГГГГ-ММ-ДД]")
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
    lang = await _lang(update.effective_user.id)
    await update.message.reply_text(
        t("paysupport_text", lang, support=config.SUPPORT_CONTACT), parse_mode="Markdown")
