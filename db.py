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

-- Учёт платежей (для аналитики выручки и возвратов).
CREATE TABLE IF NOT EXISTS payments (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT,
    payload      TEXT,
    amount_stars INTEGER NOT NULL,
    charge_id    TEXT,
    is_refunded  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS is_refunded BOOLEAN NOT NULL DEFAULT FALSE;
-- Идемпотентность доставки платежей: один charge_id — одна запись.
CREATE UNIQUE INDEX IF NOT EXISTS payments_charge_id_uniq ON payments(charge_id);

-- Подписка: id первого платежа (для отмены) и ключ OpenAI пользователя (BYOK, шифрованный).
ALTER TABLE users ADD COLUMN IF NOT EXISTS sub_charge_id  TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS openai_key_enc TEXT;

-- Напоминания «не забудь записать приём пищи».
ALTER TABLE users ADD COLUMN IF NOT EXISTS reminders_on      BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_interval INTEGER NOT NULL DEFAULT 5;

-- КБЖУ: макросы по приёмам, план тарифа, режим цели, профиль и макро-цели.
ALTER TABLE entries ADD COLUMN IF NOT EXISTS protein_g INTEGER;
ALTER TABLE entries ADD COLUMN IF NOT EXISTS fat_g     INTEGER;
ALTER TABLE entries ADD COLUMN IF NOT EXISTS carb_g    INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan       TEXT NOT NULL DEFAULT 'free';   -- free|premium|premium_plus
ALTER TABLE users ADD COLUMN IF NOT EXISTS goal_mode  TEXT NOT NULL DEFAULT 'lose';   -- lose|maintain|gain
ALTER TABLE users ADD COLUMN IF NOT EXISTS sex        TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS age        INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS height_cm  INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS weight_kg  INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS activity   TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS protein_goal INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS fat_goal     INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS carb_goal    INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by  BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lang         TEXT NOT NULL DEFAULT 'ru';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_alpha     BOOLEAN NOT NULL DEFAULT FALSE;  -- участник альфа-теста
ALTER TABLE users ADD COLUMN IF NOT EXISTS sport        TEXT;  -- вид спорта (ручной ввод) для подбора норм КБЖУ

-- Рефералы: кто кого привёл (один реферал на нового пользователя).
CREATE TABLE IF NOT EXISTS referrals (
    referrer_id BIGINT NOT NULL,
    referred_id BIGINT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Избранные блюда для быстрого повтора в один тап.
CREATE TABLE IF NOT EXISTS favorites (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    name       TEXT NOT NULL,
    calories   INTEGER NOT NULL,
    protein_g  INTEGER, fat_g INTEGER, carb_g INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);

-- Утверждённые правки калорийности (на будущее — для уточнения распознавания).
CREATE TABLE IF NOT EXISTS food_corrections (
    id          BIGSERIAL PRIMARY KEY,
    dish        TEXT NOT NULL,
    kcal        INTEGER NOT NULL,
    source_fb   BIGINT,                     -- id записи calorie_feedback
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Рантайм-настройки (меняются из админки без передеплоя). Напр. monetization_enabled.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Новости для публичного лендинга (создаются в админке / генерируются ИИ).
CREATE TABLE IF NOT EXISTS news (
    id           BIGSERIAL PRIMARY KEY,
    slug         TEXT UNIQUE NOT NULL,
    title_ru     TEXT NOT NULL,
    body_ru      TEXT NOT NULL,
    title_en     TEXT,
    body_en      TEXT,
    published    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_news_pub ON news(published, published_at DESC);

-- Недельный план питания (Premium). Один активный план на пользователя, JSON в тексте.
CREATE TABLE IF NOT EXISTS meal_plans (
    user_id    BIGINT PRIMARY KEY,
    data       TEXT NOT NULL,           -- JSON: {"days":[...], "shopping":[...]}
    pattern    TEXT,                    -- выбранный паттерн (mediterranean и т.п.)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

async def ensure_user(user_id: int, username: str = None) -> bool:
    """Зарегистрировать пользователя, если его ещё нет.

    Возвращает True, если пользователь только что создан (для выдачи триала).
    """
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (user_id, username, timezone, daily_hour, weekly_dow)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
               RETURNING (xmax = 0) AS inserted""",
            user_id, username, config.DEFAULT_TIMEZONE,
            config.DEFAULT_DAILY_HOUR, config.DEFAULT_WEEKLY_DOW,
        )
        return bool(row["inserted"])


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
    allowed = {"timezone", "daily_hour", "weekly_dow", "daily_on", "weekly_on", "goal",
               "reminders_on", "reminder_interval", "goal_mode",
               "protein_goal", "fat_goal", "carb_goal", "onboarded", "lang", "sport"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    cols = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
    async with _pool.acquire() as conn:
        await conn.execute(
            f"UPDATE users SET {cols} WHERE user_id = $1", user_id, *fields.values()
        )


# ----------------------------------------------------------------- приёмы пищи

async def add_entry(user_id: int, calories: int, item: str, entry_date: date,
                    protein_g: int = None, fat_g: int = None, carb_g: int = None) -> int:
    """Добавить приём пищи (с опциональными макросами), вернуть id записи."""
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO entries (user_id, entry_date, calories, item, protein_g, fat_g, carb_g)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
            user_id, entry_date, calories, item, protein_g, fat_g, carb_g,
        )


async def day_macros(user_id: int, entry_date: date) -> dict:
    """Сумма Б/Ж/У за день (нули, если не задано)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COALESCE(SUM(protein_g),0) p, COALESCE(SUM(fat_g),0) f,
                      COALESCE(SUM(carb_g),0) c
               FROM entries WHERE user_id=$1 AND entry_date=$2""",
            user_id, entry_date)
        return {"protein": int(row["p"]), "fat": int(row["f"]), "carb": int(row["c"])}


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
            """SELECT id, item, calories, protein_g, fat_g, carb_g, created_at FROM entries
               WHERE user_id=$1 AND entry_date=$2 ORDER BY created_at""",
            user_id, entry_date,
        )


async def last_entry_at(user_id: int):
    """Время последнего приёма пищи (timestamptz) или None."""
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT max(created_at) FROM entries WHERE user_id=$1", user_id)


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
                                   + make_interval(days => $2)
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
                return {"ok": False, "reason": "not_found"}
            if promo["expires_at"] and promo["expires_at"] < today:
                return {"ok": False, "reason": "expired"}
            if promo["used"] >= promo["max_uses"]:
                return {"ok": False, "reason": "limit"}
            already = await conn.fetchval(
                "SELECT 1 FROM redemptions WHERE user_id=$1 AND code=$2", user_id, code)
            if already:
                return {"ok": False, "reason": "already"}
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


async def lookup_correction(name: str):
    """Выверенная калорийность для известного блюда (точное совпадение, без регистра) или None."""
    if not name or not name.strip():
        return None
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """SELECT kcal FROM food_corrections
               WHERE lower(dish) = lower($1) ORDER BY created_at DESC LIMIT 1""",
            name.strip())


async def record_payment(user_id, payload, amount_stars, charge_id) -> bool:
    """Сохранить платёж идемпотентно. True — если запись новая (не дубль доставки)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO payments (user_id, payload, amount_stars, charge_id)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (charge_id) DO NOTHING RETURNING id""",
            user_id, payload, amount_stars, charge_id,
        )
        return row is not None


async def get_payment(charge_id: str) -> Optional[asyncpg.Record]:
    async with _pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM payments WHERE charge_id=$1", charge_id)


async def mark_refunded(charge_id: str) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE payments SET is_refunded=TRUE WHERE charge_id=$1", charge_id)


# ----------------------------------------------------- подписка / Premium / BYOK

async def set_premium_until(user_id: int, until) -> None:
    """Установить точную дату окончания Premium (для нативной подписки)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET premium_until=$2 WHERE user_id=$1", user_id, until)


async def set_sub_charge_id(user_id: int, charge_id: str) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET sub_charge_id=$2 WHERE user_id=$1", user_id, charge_id)


async def revoke_premium(user_id: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET premium_until=now() WHERE user_id=$1", user_id)


async def set_openai_key(user_id: int, enc: str) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET openai_key_enc=$2 WHERE user_id=$1", user_id, enc)


async def clear_openai_key(user_id: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET openai_key_enc=NULL WHERE user_id=$1", user_id)


async def set_plan(user_id: int, plan: str) -> None:
    async with _pool.acquire() as conn:
        await conn.execute("UPDATE users SET plan=$2 WHERE user_id=$1", user_id, plan)


async def mark_alpha(user_id: int) -> None:
    """Пометить пользователя как участника альфа-теста."""
    async with _pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_alpha=TRUE WHERE user_id=$1", user_id)


async def save_meal_plan(user_id: int, data_json: str, pattern: str = None) -> None:
    """Сохранить (заменить) недельный план питания пользователя."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO meal_plans (user_id, data, pattern) VALUES ($1, $2, $3)
               ON CONFLICT (user_id) DO UPDATE
               SET data = EXCLUDED.data, pattern = EXCLUDED.pattern, created_at = now()""",
            user_id, data_json, pattern)


async def get_meal_plan(user_id: int):
    """Вернуть запись плана (data — JSON-текст) или None."""
    async with _pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM meal_plans WHERE user_id=$1", user_id)


async def set_profile(user_id: int, sex, age, height_cm, weight_kg, activity, sport=None) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            """UPDATE users SET sex=$2, age=$3, height_cm=$4, weight_kg=$5, activity=$6, sport=$7
               WHERE user_id=$1""",
            user_id, sex, age, height_cm, weight_kg, activity, sport)


async def set_macro_goals(user_id: int, protein: int, fat: int, carb: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET protein_goal=$2, fat_goal=$3, carb_goal=$4 WHERE user_id=$1",
            user_id, protein, fat, carb)


async def grant_referral_reward(user_id: int, days: int) -> None:
    """Начислить реферальный бонус: продлить Premium и поднять план до premium (не понижая)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """UPDATE users
               SET premium_until = GREATEST(COALESCE(premium_until, now()), now())
                                   + make_interval(days => $2),
                   plan = CASE WHEN plan = 'free' THEN 'premium' ELSE plan END
               WHERE user_id = $1""",
            user_id, days)


async def add_referral(referrer_id: int, referred_id: int) -> bool:
    """Записать реферала. True — если запись новая (этот новичок ещё не был чьим-то рефералом)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO referrals (referrer_id, referred_id) VALUES ($1, $2)
               ON CONFLICT (referred_id) DO NOTHING RETURNING referred_id""",
            referrer_id, referred_id)
        if row is not None:
            await conn.execute(
                "UPDATE users SET referred_by=$2 WHERE user_id=$1", referred_id, referrer_id)
        return row is not None


async def add_favorite(user_id, name, calories, protein_g, fat_g, carb_g) -> int:
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO favorites (user_id, name, calories, protein_g, fat_g, carb_g)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
            user_id, name[:80], calories, protein_g, fat_g, carb_g)


async def list_favorites(user_id: int, limit: int = 12) -> list:
    async with _pool.acquire() as conn:
        return await conn.fetch(
            """SELECT * FROM favorites WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2""",
            user_id, limit)


async def get_favorite(fav_id: int, user_id: int):
    async with _pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM favorites WHERE id=$1 AND user_id=$2", fav_id, user_id)


async def delete_favorite(fav_id: int, user_id: int) -> bool:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM favorites WHERE id=$1 AND user_id=$2 RETURNING id", fav_id, user_id)
        return row is not None


async def count_referrals(referrer_id: int) -> int:
    async with _pool.acquire() as conn:
        return int(await conn.fetchval(
            "SELECT count(*) FROM referrals WHERE referrer_id=$1", referrer_id))


async def reset_user(user_id: int) -> None:
    """Стереть историю питания и сбросить цель/профиль/онбординг.
    Подписка, план и кредиты сохраняются (это оплаченное)."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM entries WHERE user_id=$1", user_id)
            await conn.execute(
                """UPDATE users SET goal=NULL, goal_mode='lose',
                       sex=NULL, age=NULL, height_cm=NULL, weight_kg=NULL, activity=NULL,
                       protein_goal=NULL, fat_goal=NULL, carb_goal=NULL,
                       ai_count_date=NULL, ai_count_today=0, onboarded=FALSE
                   WHERE user_id=$1""",
                user_id)


async def get_setting(key: str) -> Optional[str]:
    async with _pool.acquire() as conn:
        return await conn.fetchval("SELECT value FROM settings WHERE key=$1", key)


async def set_setting(key: str, value: str) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO settings (key, value) VALUES ($1, $2)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            key, value)


async def admin_stats() -> dict:
    """Сводка для /stats."""
    async with _pool.acquire() as conn:
        return dict(await conn.fetchrow(
            """SELECT
                 (SELECT count(*) FROM users) AS total_users,
                 (SELECT count(*) FROM users WHERE created_at >= now() - interval '7 days') AS new_7d,
                 (SELECT count(*) FROM users WHERE premium_until > now()) AS premium_active,
                 (SELECT count(*) FROM users WHERE premium_until > now() AND plan='premium') AS premium_basic_active,
                 (SELECT count(*) FROM users WHERE premium_until > now() AND plan='premium_plus') AS premium_plus_active,
                 (SELECT count(*) FROM payments WHERE created_at >= now() - interval '30 days' AND NOT is_refunded) AS payments_30d,
                 (SELECT COALESCE(SUM(amount_stars),0) FROM payments WHERE created_at >= now() - interval '30 days' AND NOT is_refunded) AS stars_30d,
                 (SELECT COALESCE(SUM(amount_stars),0) FROM payments WHERE created_at >= now() - interval '30 days' AND NOT is_refunded AND payload='premium_sub') AS stars_30d_basic,
                 (SELECT COALESCE(SUM(amount_stars),0) FROM payments WHERE created_at >= now() - interval '30 days' AND NOT is_refunded AND payload='premium_macros_sub') AS stars_30d_plus,
                 (SELECT count(*) FROM redemptions) AS promo_redemptions,
                 (SELECT count(*) FROM referrals) AS referrals_total
            """))
