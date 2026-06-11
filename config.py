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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")
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
