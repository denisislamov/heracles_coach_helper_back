"""Конфигурация бота. Все значения берутся из переменных окружения."""
import os


def _req(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return val


# --- Telegram ---
BOT_TOKEN = _req("BOT_TOKEN")

# --- OpenAI ---
OPENAI_API_KEY = _req("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
# Дешёвая модель для бесплатного тира (снижает себестоимость, см. МОНЕТИЗАЦИЯ.md §9).
OPENAI_MODEL_FREE = os.environ.get("OPENAI_MODEL_FREE", "gpt-4o-mini")

# --- База данных ---
DATABASE_URL = _req("DATABASE_URL")

# --- Webhook / Render ---
# Render автоматически прокидывает PORT и RENDER_EXTERNAL_URL.
PORT = int(os.environ.get("PORT", "10000"))
# Публичный URL сервиса, напр. https://my-bot.onrender.com
# На Render всегда верно выставлен RENDER_EXTERNAL_URL — берём его в первую
# очередь, чтобы не зависеть от вручную заданного (и возможно неверного) значения.
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_URL")
# Telegram требует https. Если задан только хост — добавим схему.
if WEBHOOK_URL and not WEBHOOK_URL.startswith(("http://", "https://")):
    WEBHOOK_URL = "https://" + WEBHOOK_URL
# Секретный путь вебхука (по умолчанию берём из токена).
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", BOT_TOKEN.split(":")[0])

# Режим запуска: "webhook" (на Render) или "polling" (локально).
RUN_MODE = os.environ.get("RUN_MODE", "webhook").lower()

# Значения по умолчанию для нового пользователя.
DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "Europe/Moscow")
DEFAULT_DAILY_HOUR = int(os.environ.get("DEFAULT_DAILY_HOUR", "21"))   # час дневного отчёта
DEFAULT_WEEKLY_DOW = int(os.environ.get("DEFAULT_WEEKLY_DOW", "6"))    # 0=пн .. 6=вс

# --- Монетизация (Telegram Stars) ---
# Главный выключатель монетизации. При 0 — всё бесплатно, без лимитов и пэйвола,
# кнопка Premium скрыта. Чтобы включить — задай MONETIZATION_ENABLED=1.
MONETIZATION_ENABLED = os.environ.get("MONETIZATION_ENABLED", "1").lower() in ("1", "true", "yes")
# Сколько ИИ-анализов в день бесплатно (в течение бесплатного периода).
FREE_DAILY_AI = int(os.environ.get("FREE_DAILY_AI", "3"))
# Длина бесплатного периода в днях с момента регистрации (потом — только Premium).
FREE_PERIOD_DAYS = int(os.environ.get("FREE_PERIOD_DAYS", "30"))
# Цена месячной подписки Premium в звёздах (валюта XTR). 1 ⭐ ≈ пара центов.
SUBSCRIPTION_PRICE_STARS = int(os.environ.get("SUBSCRIPTION_PRICE_STARS", "200"))
# Длительность подписки в днях. Для нативной подписки Telegram = ровно 30 (2592000 c).
SUBSCRIPTION_DAYS = int(os.environ.get("SUBSCRIPTION_DAYS", "30"))
# Период автопродления подписки Telegram Stars в секундах (Telegram принимает только 2592000).
SUBSCRIPTION_PERIOD_SEC = 2592000
# Контакт поддержки (для /paysupport и /terms).
SUPPORT_CONTACT = os.environ.get("SUPPORT_CONTACT", "@your_support")

# Доп. триал безлимита для новых (0 = выкл). Бесплатная модель уже задана
# параметрами FREE_DAILY_AI + FREE_PERIOD_DAYS, поэтому по умолчанию выключен.
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "0"))

# Пакеты разовых анализов: "кредитов:звёзд" через запятую.
def _parse_packs(raw: str):
    packs = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            credits, stars = part.split(":")
            packs.append((int(credits), int(stars)))
        except ValueError:
            continue
    return packs

CREDIT_PACKS = _parse_packs(os.environ.get("CREDIT_PACKS", "50:70,200:220"))

# BYOK: ключ шифрования (Fernet) для хранения чужих ключей OpenAI. Пусто = фича выключена.
BYOK_ENCRYPTION_KEY = os.environ.get("BYOK_ENCRYPTION_KEY", "").strip()

# ID администраторов (через запятую) — кому доступна команда /addpromo.
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Тестовая среда Telegram (бесплатные звёзды, платежи понарошку).
# Включается переменной TELEGRAM_TEST_ENV=1. python-telegram-bot строит URL как
# base_url + token + "/" + endpoint, поэтому для тестовой среды (.../bot<token>/test/<method>)
# достаточно добавить "/test" к токену.
TELEGRAM_TEST_ENV = os.environ.get("TELEGRAM_TEST_ENV", "0").lower() in ("1", "true", "yes")
EFFECTIVE_TOKEN = BOT_TOKEN + "/test" if TELEGRAM_TEST_ENV else BOT_TOKEN
