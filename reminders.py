"""Дружелюбные напоминания «не забудь записать приём пищи».

Каждые N часов (2–8, по умолчанию 5) бот шлёт мотивирующее сообщение, но:
  * только днём в часовом поясе пользователя (09:00–22:00) — не беспокоим ночью;
  * только если за последние N часов не было ни одного приёма (активных не дёргаем).
"""
import datetime as dt
import logging
import random

import pytz
from telegram.error import Forbidden

import db

log = logging.getLogger("calbot.reminders")

DAY_START, DAY_END = 9, 22  # тихие часы вне этого окна (по местному времени)

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


def schedule_user(application, user) -> None:
    """(Пере)создать повторяющееся напоминание для пользователя."""
    jq = application.job_queue
    name = f"rem_{user['user_id']}"
    for job in jq.get_jobs_by_name(name):
        job.schedule_removal()
    if not user["reminders_on"]:
        return
    interval = _interval_hours(user) * 3600
    jq.run_repeating(_job, interval=interval, first=interval,
                     name=name, chat_id=user["user_id"])


async def schedule_all(application) -> None:
    for user in await db.active_users():
        schedule_user(application, user)


async def _job(context) -> None:
    uid = context.job.chat_id
    user = await db.get_user(uid)
    if not user or not user["reminders_on"]:
        return
    # тихие часы по местному времени
    try:
        now_local = dt.datetime.now(pytz.timezone(user["timezone"]))
    except Exception:
        now_local = dt.datetime.utcnow()
    if not (DAY_START <= now_local.hour < DAY_END):
        return
    # не беспокоим, если приём был недавно
    interval_h = _interval_hours(user)
    last = await db.last_entry_at(uid)
    if last and (dt.datetime.now(dt.timezone.utc) - last) < dt.timedelta(hours=interval_h):
        return
    try:
        await context.bot.send_message(uid, random.choice(MESSAGES))
    except Forbidden:
        await db.set_blocked(uid, True)
        for job in context.job_queue.get_jobs_by_name(f"rem_{uid}"):
            job.schedule_removal()
    except Exception as e:
        log.warning("Не удалось отправить напоминание %s: %s", uid, e)
