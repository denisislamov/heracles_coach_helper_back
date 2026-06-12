"""BYOK — хранение собственного ключа OpenAI пользователя (Bring Your Own Key).

Ключ шифруется (Fernet) перед записью в БД и НИКОГДА не логируется и не
показывается обратно. Фича включается переменной BYOK_ENCRYPTION_KEY.
"""
import logging
from typing import Optional

from openai import AsyncOpenAI

import config

log = logging.getLogger("calbot.byok")

_fernet = None
if config.BYOK_ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(config.BYOK_ENCRYPTION_KEY.encode())
    except Exception as e:  # неверный ключ шифрования — фича останется выключенной
        log.error("BYOK выключен: некорректный BYOK_ENCRYPTION_KEY (%s)", e)


def enabled() -> bool:
    return _fernet is not None


def encrypt(api_key: str) -> str:
    return _fernet.encrypt(api_key.encode()).decode()


def decrypt(enc: Optional[str]) -> Optional[str]:
    if not enc or not _fernet:
        return None
    try:
        return _fernet.decrypt(enc.encode()).decode()
    except Exception:
        return None


async def validate_key(api_key: str) -> bool:
    """Дешёвая проверка ключа (список моделей)."""
    try:
        await AsyncOpenAI(api_key=api_key).models.list()
        return True
    except Exception:
        return False
