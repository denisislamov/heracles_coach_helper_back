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

-- Монетизация: подписка, дневной счётчик ИИ-анализов, разовые кредиты.
ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_until TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_count_date  DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_count_today INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS credits        INTEGER NOT NULL DEFAULT 0;

-- Промокоды.
CREATE TABLE IF NOT EXISTS promo_codes (
    code        TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,             -- 'premium_days' | 'credits'
    value       INTEGER NOT NULL,          -- дней Premium или штук анализов
    max_uses    INTEGER NOT NULL DEFAULT 1,
    used        INTEGER NOT NULL DEFAULT 0,
    expires_at  DATE,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS redemptions (
    user_id     BIGINT NOT NULL,
    code        TEXT   NOT NULL,
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, code)
);

-- Обратная связь: баг-репорты.
CREATE TABLE IF NOT EXISTS bug_reports (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT,
    username    TEXT,
    description TEXT NOT NULL,
    media_type  TEXT,                       -- 'photo' | 'video' | NULL
    file_id     TEXT,                       -- Telegram file_id
    status      TEXT NOT NULL DEFAULT 'new',-- new | in_progress | done
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Обратная связь: неверный подсчёт калорий.
CREATE TABLE IF NOT EXISTS calorie_feedback (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT,
    username      TEXT,
    dish          TEXT NOT NULL,            -- описание блюда / что не так
    correct_kcal  INTEGER,                  -- правильное значение (если указал)
    media_type    TEXT,
    file_id       TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Учёт платежей (для аналитики выручки).
CREATE TABLE IF NOT EXISTS payments (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT,
    payload      TEXT,
    amount_stars INTEGER NOT NULL,
    charge_id    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Утверждённые правки калорийности (на будущее — для уточнения распознавания).
CREATE TABLE IF NOT EXISTS food_corrections (
    id          BIGSERIAL PRIMARY KEY,
    dish        TEXT NOT NULL,
    kcal        INTEGER NOT NULL,
    source_fb   BIGINT,                     -- id записи calorie_feedback
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
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

async def add_entry(user_id: int, calories: int, item: str, entry_date: date) -> int:
    """Добавить приём пищи, вернуть id созданной записи."""
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO entries (user_id, entry_date, calories, item)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            user_id, entry_date, calories, item,
        )


async def get_entry(entry_id: int, user_id: int) -> Optional[asyncpg.Record]:
    """Запись по id с проверкой владельца (или None)."""
    async with _pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM entries WHERE id=$1 AND user_id=$2", entry_id, user_id)


async def update_entry(entry_id: int, user_id: int, calories: int, item: str) -> bool:
    """Изменить калории/название записи. True — если запись найдена и обновлена."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE entries SET calories=$3, item=$4
               WHERE id=$1 AND user_id=$2 RETURNING id""",
            entry_id, user_id, calories, item)
        return row is not None


async def delete_entry(entry_id: int, user_id: int) -> bool:
    """Удалить запись. True — если была удалена."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM entries WHERE id=$1 AND user_id=$2 RETURNING id",
            entry_id, user_id)
        return row is not None


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
            """SELECT id, item, calories, created_at FROM entries
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


# -------------------------------------------------- монетизация: лимиты/подписка

async def free_used_today(user_id: int, today: date) -> int:
    """Сколько бесплатных ИИ-анализов уже потрачено сегодня (с учётом сброса по дате)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ai_count_date, ai_count_today FROM users WHERE user_id=$1", user_id)
        if not row or row["ai_count_date"] != today:
            return 0
        return row["ai_count_today"]


async def bump_free_usage(user_id: int, today: date) -> None:
    """Засчитать один бесплатный анализ (сбрасывает счётчик при смене даты)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """UPDATE users
               SET ai_count_today = CASE WHEN ai_count_date = $2
                                         THEN ai_count_today + 1 ELSE 1 END,
                   ai_count_date  = $2
               WHERE user_id = $1""",
            user_id, today,
        )


async def consume_credit(user_id: int) -> bool:
    """Списать один разовый кредит. True — если был и списан."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE users SET credits = credits - 1
               WHERE user_id = $1 AND credits > 0 RETURNING credits""",
            user_id)
        return row is not None


async def grant_premium_days(user_id: int, days: int) -> None:
    """Продлить Premium на N дней от max(сейчас, текущей даты окончания)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """UPDATE users
               SET premium_until = GREATEST(COALESCE(premium_until, now()), now())
                                   + ($2 || ' days')::interval
               WHERE user_id = $1""",
            user_id, days,
        )


async def add_credits(user_id: int, n: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET credits = credits + $2 WHERE user_id = $1", user_id, n)


# --------------------------------------------------------------- промокоды

async def redeem_promo(user_id: int, code: str, today: date) -> dict:
    """Активировать промокод. Возвращает {ok, reason, kind, value}.

    Транзакционно: проверяет лимит/срок/повтор и инкрементит счётчик.
    """
    async with _pool.acquire() as conn:
        async with conn.transaction():
            promo = await conn.fetchrow(
                "SELECT * FROM promo_codes WHERE code = $1 FOR UPDATE", code)
            if not promo or not promo["active"]:
                return {"ok": False, "reason": "Код не найден или неактивен."}
            if promo["expires_at"] and promo["expires_at"] < today:
                return {"ok": False, "reason": "Срок действия кода истёк."}
            if promo["used"] >= promo["max_uses"]:
                return {"ok": False, "reason": "Лимит активаций кода исчерпан."}
            already = await conn.fetchval(
                "SELECT 1 FROM redemptions WHERE user_id=$1 AND code=$2", user_id, code)
            if already:
                return {"ok": False, "reason": "Ты уже активировал этот код."}
            await conn.execute(
                "INSERT INTO redemptions (user_id, code) VALUES ($1, $2)", user_id, code)
            await conn.execute(
                "UPDATE promo_codes SET used = used + 1 WHERE code = $1", code)
            return {"ok": True, "kind": promo["kind"], "value": promo["value"]}


async def create_promo(code: str, kind: str, value: int,
                       max_uses: int = 1, expires_at: date = None) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO promo_codes (code, kind, value, max_uses, expires_at)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (code) DO UPDATE
               SET kind=EXCLUDED.kind, value=EXCLUDED.value,
                   max_uses=EXCLUDED.max_uses, expires_at=EXCLUDED.expires_at,
                   active=TRUE""",
            code, kind, value, max_uses, expires_at,
        )


# ---------------------------------------------------- обратная связь / платежи

async def add_bug_report(user_id, username, description, media_type, file_id) -> int:
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO bug_reports (user_id, username, description, media_type, file_id)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            user_id, username, description, media_type, file_id,
        )


async def add_calorie_feedback(user_id, username, dish, correct_kcal,
                               media_type, file_id) -> int:
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO calorie_feedback
                   (user_id, username, dish, correct_kcal, media_type, file_id)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            user_id, username, dish, correct_kcal, media_type, file_id,
        )


async def record_payment(user_id, payload, amount_stars, charge_id) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO payments (user_id, payload, amount_stars, charge_id)
               VALUES ($1, $2, $3, $4)""",
            user_id, payload, amount_stars, charge_id,
        )
