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
# Сколько ИИ-анализов в день бесплатно (до пэйвола).
FREE_DAILY_AI = int(os.environ.get("FREE_DAILY_AI", "5"))
# Цена месячной подписки Premium в звёздах (валюта XTR). 1 ⭐ ≈ пара центов.
SUBSCRIPTION_PRICE_STARS = int(os.environ.get("SUBSCRIPTION_PRICE_STARS", "250"))
# Длительность подписки в днях.
SUBSCRIPTION_DAYS = int(os.environ.get("SUBSCRIPTION_DAYS", "30"))
# Контакт поддержки (для /paysupport и /terms).
SUPPORT_CONTACT = os.environ.get("SUPPORT_CONTACT", "@your_support")

# ID администраторов (через запятую) — кому доступна команда /addpromo.
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Тестовая среда Telegram (бесплатные звёзды, платежи понарошку).
# Включается переменной TELEGRAM_TEST_ENV=1. python-telegram-bot строит URL как
# base_url + token + "/" + endpoint, поэтому для тестовой среды (.../bot<token>/test/<method>)
# достаточно добавить "/test" к токену.
TELEGRAM_TEST_ENV = os.environ.get("TELEGRAM_TEST_ENV", "0").lower() in ("1", "true", "yes")
EFFECTIVE_TOKEN = BOT_TOKEN + "/test" if TELEGRAM_TEST_ENV else BOT_TOKEN
