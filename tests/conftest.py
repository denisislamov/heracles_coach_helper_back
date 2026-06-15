"""Общая настройка тестов: переменные окружения и путь к проекту."""
import os
import sys

# Обязательные ENV до импорта модулей бота (config их требует).
os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/test")
os.environ.setdefault("RUN_MODE", "polling")

# Корень проекта в путь импорта.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
