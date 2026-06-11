"""Слой доступа к данным (PostgreSQL через asyncpg).

Таблицы:
  users    — пользователь, его цель по калориям и настройки отчётов
  entries  — отдельные приёмы пищи / добавленные калории за день
"""
import asyncpg
from datetime import date, datetime, timedelta
from typing import Optional

import config

_pool: Optional[asyncpg.Pool] = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      BIGINT PRIMARY KEY,
    username     TEXT,
    goal         INTEGER,                       -- цель ккал/день
    timezone     TEXT    NOT NULL DEFAULT 'Europe/Moscow',
    daily_hour   INTEGER NOT NULL DEFAULT 21,   -- час дневного отчёта (0-23)
    weekly_dow   INTEGER NOT NULL DEFAULT 6,    -- день недельного отчёта (0=пн..6=вс)
    daily_on     BOOLEAN NOT NULL DEFAULT TRUE,
    weekly_on    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entries (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    entry_date DATE   NOT NULL,
    calories   INTEGER NOT NULL,
    item       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_entries_user_date ON entries(user_id, entry_date);
"""


async def init(dsn: str = None) -> None:
    """Создать пул соединений и применить схему."""
    global _pool
    dsn = dsn or config.DATABASE_URL
    # asyncpg не понимает префикс postgres:// от некоторых провайдеров
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def close() -> None:
    if _pool:
        await _pool.close()


# ---------------------------------------------------------------- пользователи

async def ensure_user(user_id: int, username: str = None) -> None:
    """Зарегистрировать пользователя, если его ещё нет."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO users (user_id, username, timezone, daily_hour, weekly_dow)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
            user_id, username, config.DEFAULT_TIMEZONE,
            config.DEFAULT_DAILY_HOUR, config.DEFAULT_WEEKLY_DOW,
        )


async def get_user(user_id: int) -> Optional[asyncpg.Record]:
    async with _pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def all_users() -> list:
    async with _pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users")


async def set_goal(user_id: int, goal: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute("UPDATE users SET goal = $2 WHERE user_id = $1", user_id, goal)


async def update_settings(user_id: int, **fields) -> None:
    """Обновить произвольные поля настроек: timezone, daily_hour, weekly_dow, daily_on, weekly_on."""
    allowed = {"timezone", "daily_hour", "weekly_dow", "daily_on", "weekly_on", "goal"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
    async with _pool.acquire() as conn:
        await conn.execute(
            f"UPDATE users SET {cols} WHERE user_id = $1", user_id, *fields.values()
        )


# ----------------------------------------------------------------- приёмы пищи

async def add_entry(user_id: int, calories: int, item: str, entry_date: date) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO entries (user_id, entry_date, calories, item)
               VALUES ($1, $2, $3, $4)""",
            user_id, entry_date, calories, item,
        )


async def day_total(user_id: int, entry_date: date) -> int:
    async with _pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COALESCE(SUM(calories),0) FROM entries WHERE user_id=$1 AND entry_date=$2",
            user_id, entry_date,
        )
        return int(val)


async def day_entries(user_id: int, entry_date: date) -> list:
    async with _pool.acquire() as conn:
        return await conn.fetch(
            """SELECT item, calories, created_at FROM entries
               WHERE user_id=$1 AND entry_date=$2 ORDER BY created_at""",
            user_id, entry_date,
        )


async def range_daily_totals(user_id: int, start: date, end: date) -> list:
    """Список (дата, сумма) по дням за период [start, end] включительно."""
    async with _pool.acquire() as conn:
        return await conn.fetch(
            """SELECT entry_date, SUM(calories) AS total FROM entries
               WHERE user_id=$1 AND entry_date BETWEEN $2 AND $3
               GROUP BY entry_date ORDER BY entry_date""",
            user_id, start, end,
        )
