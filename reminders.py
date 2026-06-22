"""Напоминания «не забудь записать приём пищи».

Два режима (выбор в настройках):
  * interval — каждые N часов (2–8), как раньше;
  * smart — по предсказанным/заданным временам приёмов пищи: бот учит типичные часы
    из истории записей (гибрид: можно поправить руками) и напоминает к этому времени.
В обоих случаях: только днём (09:00–22:00 по местному), не дёргаем, если недавно была запись.
"""
import datetime as dt
import logging
import random
from collections import Counter

import pytz
from telegram.error import Forbidden

import db
from i18n import t

log = logging.getLogger("calbot.reminders")

DAY_START, DAY_END = 8, 22  # тихие часы вне этого окна (по местному времени)

MESSAGES = [
    "🍽 Возможно, вы забыли добавить последний приём пищи? Пришлите фото или описание.",
    "👋 Как насчёт обновить дневник? Скиньте фото того, что ели — посчитаю калории.",
    "📷 Перекусили? Не теряйте из виду цель — пришлите фото или текст блюда.",
    "⏰ Давно не было записей. Добавим то, что вы съели за это время?",
    "💪 Держим темп! Пришлите фото последнего приёма пищи, чтобы дневник был полным.",
    "🥗 Не забывайте отмечать еду — так отчёты будут точными. Что ели недавно?",
]


def _interval_hours(user) -> int:
    return max(2, min(8, user["reminder_interval"] or 5))


def parse_meal_times(raw) -> list:
    """'8,13,19' / '8 13 19' → [8,13,19] (валидные часы, по возрастанию, без дублей)."""
    if not raw:
        return []
    out = set()
    for tok in str(raw).replace(";", ",").replace(" ", ",").split(","):
        tok = tok.strip().split(":")[0]
        if tok.isdigit() and 0 <= int(tok) <= 23:
            out.add(int(tok))
    return sorted(out)


async def predict_meal_hours(user, min_entries: int = 10, min_days: int = 7) -> list:
    """Предсказать типичные часы приёмов пищи по истории. [] — данных мало (холодный старт)."""
    times = await db.recent_entry_times(user["user_id"], 28)
    if len(times) < min_entries:
        return []
    try:
        tz = pytz.timezone(user["timezone"])
    except Exception:
        tz = pytz.UTC
    hours, days = Counter(), set()
    for ts in times:
        local = ts.astimezone(tz)
        if DAY_START <= local.hour < DAY_END:
            hours[local.hour] += 1
            days.add(local.date())
    if len(days) < min_days:
        return []
    thr = max(3, int(0.3 * len(days)))   # час должен повторяться достаточно часто
    peaks = sorted(h for h, c in hours.items() if c >= thr)
    # схлопываем соседние часы (12 и 13 → один приём), берём до 4 окон
    merged = []
    for h in peaks:
        if not merged or h - merged[-1] >= 2:
            merged.append(h)
    return merged[:4]


def _clear_jobs(jq, uid) -> None:
    interval_name = f"rem_{uid}"
    smart_prefix = f"rem_smart_{uid}_"
    for job in list(jq.jobs()):
        if job.name == interval_name or (job.name or "").startswith(smart_prefix):
            job.schedule_removal()


async def schedule_user(application, user) -> None:
    """(Пере)создать напоминания согласно режиму пользователя."""
    jq = application.job_queue
    uid = user["user_id"]
    _clear_jobs(jq, uid)
    if not user["reminders_on"]:
        return
    mode = (user["reminder_mode"] or "interval") if "reminder_mode" in user else "interval"
    if mode == "smart":
        hours = parse_meal_times(user["meal_times"]) or await predict_meal_hours(user)
        if hours:
            try:
                tz = pytz.timezone(user["timezone"])
            except Exception:
                tz = pytz.UTC
            for h in hours:
                jq.run_daily(_smart_job, time=dt.time(hour=h, minute=0, tzinfo=tz),
                             name=f"rem_smart_{uid}_{h}", chat_id=uid)
            return
        # холодный старт / нет данных — откатываемся на интервальные
    interval = _interval_hours(user) * 3600
    jq.run_repeating(_job, interval=interval, first=interval,
                     name=f"rem_{uid}", chat_id=uid)


async def schedule_all(application) -> None:
    for user in await db.active_users():
        await schedule_user(application, user)


def _within_day(user) -> bool:
    try:
        now_local = dt.datetime.now(pytz.timezone(user["timezone"]))
    except Exception:
        now_local = dt.datetime.utcnow()
    return DAY_START <= now_local.hour < DAY_END


async def _send(context, uid, text) -> None:
    try:
        await context.bot.send_message(uid, text)
    except Forbidden:
        await db.set_blocked(uid, True)
        _clear_jobs(context.job_queue, uid)
    except Exception as e:
        log.warning("Не удалось отправить напоминание %s: %s", uid, e)


async def _job(context) -> None:
    """Интервальный режим."""
    uid = context.job.chat_id
    user = await db.get_user(uid)
    if not user or not user["reminders_on"]:
        return
    if not _within_day(user):
        return
    interval_h = _interval_hours(user)
    last = await db.last_entry_at(uid)
    if last and (dt.datetime.now(dt.timezone.utc) - last) < dt.timedelta(hours=interval_h):
        return
    await _send(context, uid, random.choice(MESSAGES))


async def _smart_job(context) -> None:
    """Умный режим: напоминание к типичному времени приёма пищи."""
    uid = context.job.chat_id
    user = await db.get_user(uid)
    if not user or not user["reminders_on"] or (user["reminder_mode"] or "interval") != "smart":
        return
    if not _within_day(user):
        return
    # не дёргаем, если за последние ~2 часа уже была запись
    last = await db.last_entry_at(uid)
    if last and (dt.datetime.now(dt.timezone.utc) - last) < dt.timedelta(hours=2):
        return
    await _send(context, uid, t("smart_reminder", user["lang"]))
