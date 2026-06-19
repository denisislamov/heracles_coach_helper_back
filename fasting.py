"""Интервальное голодание (Premium): протоколы, стадии, статус и уведомление о цели.

Формулировки про «стадии» намеренно осторожные («ориентировочно», «у разных людей
по-разному») — это не медицинская рекомендация.
"""
import datetime as dt
import logging

import db
from i18n import t

log = logging.getLogger("calbot.fasting")

# Протоколы: часы голодания (окно еды = 24 - N).
PROTOCOLS = [14, 16, 18, 20, 23]

# Стадии по часам голодания: (порог_часов, ключ_текста). Берём наибольший достигнутый.
STAGES = [
    (0, "fast_stage_eat"),
    (4, "fast_stage_sugar"),
    (12, "fast_stage_glycogen"),
    (16, "fast_stage_fat"),
    (18, "fast_stage_ketosis"),
    (24, "fast_stage_autophagy"),
]


def proto_label(hours: int) -> str:
    return f"{hours}:{24 - hours}"


def stage_text(elapsed_hours: float, lang: str) -> str:
    key = STAGES[0][1]
    for thr, k in STAGES:
        if elapsed_hours >= thr:
            key = k
    return t(key, lang)


def _bar(frac: float, width: int = 10) -> str:
    frac = max(0.0, min(1.0, frac))
    full = int(round(frac * width))
    return "▓" * full + "░" * (width - full)


def _fmt_hm(td: dt.timedelta) -> str:
    secs = max(0, int(td.total_seconds()))
    h, m = divmod(secs // 60, 60)
    return f"{h}ч {m:02d}м"


def status_text(fast, lang: str) -> str:
    """Текст статуса активного поста: протокол, прошло/цель, прогресс, осталось, стадия."""
    now = dt.datetime.now(dt.timezone.utc)
    start = fast["start_at"]
    target_h = fast["target_hours"]
    elapsed = now - start
    elapsed_h = elapsed.total_seconds() / 3600.0
    target_td = dt.timedelta(hours=target_h)
    frac = elapsed.total_seconds() / target_td.total_seconds() if target_h else 0
    remaining = target_td - elapsed
    if remaining.total_seconds() <= 0:
        rem_line = t("fast_goal_done", lang)
    else:
        rem_line = t("fast_remaining", lang, time=_fmt_hm(remaining))
    return t("fast_status", lang,
             proto=proto_label(target_h), elapsed=_fmt_hm(elapsed),
             target=target_h, bar=_bar(frac), pct=int(min(100, frac * 100)),
             rem=rem_line, stage=stage_text(elapsed_h, lang))


# ----------------------------------------------------------- уведомление о цели

async def _notify_goal(context) -> None:
    uid = context.job.data["user_id"]
    fast_id = context.job.data["fast_id"]
    fast = await db.get_active_fast(uid)
    # шлём только если этот же пост всё ещё активен
    if not fast or fast["id"] != fast_id:
        return
    user = await db.get_user(uid)
    lang = user["lang"] if user else "ru"
    try:
        await context.bot.send_message(
            uid, t("fast_goal_reached", lang, proto=proto_label(fast["target_hours"])),
            parse_mode="Markdown")
    except Exception as e:
        log.warning("fast notify %s: %s", uid, e)


def schedule_goal(job_queue, user_id: int, fast_id: int, when_seconds: float) -> None:
    if when_seconds <= 0:
        return
    job_queue.run_once(_notify_goal, when=when_seconds,
                       data={"user_id": user_id, "fast_id": fast_id},
                       name=f"fast_goal_{user_id}")


async def reschedule_all(application) -> None:
    """На старте бота заново ставим уведомления для активных постов."""
    now = dt.datetime.now(dt.timezone.utc)
    for f in await db.all_active_fasts():
        goal_at = f["start_at"] + dt.timedelta(hours=f["target_hours"])
        secs = (goal_at - now).total_seconds()
        if secs > 0:
            schedule_goal(application.job_queue, f["user_id"], f["id"], secs)
