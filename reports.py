"""Дневной и недельный отчёты + планирование их рассылки.

Используем JobQueue из python-telegram-bot. На каждого пользователя создаётся
ОДНА ежедневная задача в его часовом поясе и в выбранный им час. Внутри:
  * всегда (если включён) шлём дневной отчёт;
  * если сегодня — выбранный день недели и включён недельный отчёт, шлём ещё и его.
Это избавляет от зависимости от внутренней нумерации дней в JobQueue.
"""
import datetime as dt

import pytz

import db


def _today(tz_name: str) -> dt.date:
    return dt.datetime.now(pytz.timezone(tz_name)).date()


def _progress_bar(consumed: int, goal: int, width: int = 10) -> str:
    if not goal:
        return ""
    ratio = max(0.0, min(consumed / goal, 1.0))
    filled = round(ratio * width)
    return "▓" * filled + "░" * (width - filled)


async def build_daily_text(user) -> str:
    tz = user["timezone"]
    day = _today(tz)
    entries = await db.day_entries(user["user_id"], day)
    total = sum(e["calories"] for e in entries)
    goal = user["goal"] or 0

    lines = [f"📊 *Дневной отчёт за {day.strftime('%d.%m.%Y')}*", ""]
    if entries:
        for e in entries:
            name = e["item"] or "приём пищи"
            lines.append(f"• {name} — {e['calories']} ккал")
    else:
        lines.append("_Записей за день нет._")
    lines.append("")
    if goal:
        bar = _progress_bar(total, goal)
        diff = total - goal
        status = (f"превышение на {diff} ккал ⚠️" if diff > 0
                  else f"остаток {-diff} ккал ✅")
        lines.append(f"Итого: *{total}* / {goal} ккал")
        lines.append(f"{bar}  {status}")
    else:
        lines.append(f"Итого: *{total}* ккал (цель не задана)")
    return "\n".join(lines)


async def build_weekly_text(user) -> str:
    tz = user["timezone"]
    end = _today(tz)
    start = end - dt.timedelta(days=6)
    rows = await db.range_daily_totals(user["user_id"], start, end)
    by_date = {r["entry_date"]: int(r["total"]) for r in rows}
    goal = user["goal"] or 0

    lines = [f"📅 *Недельный отчёт* ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})", ""]
    week_total = 0
    days_with_data = 0
    names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i in range(7):
        d = start + dt.timedelta(days=i)
        val = by_date.get(d, 0)
        week_total += val
        if val:
            days_with_data += 1
        mark = ""
        if goal and val:
            mark = " ⚠️" if val > goal else " ✅"
        lines.append(f"{names[d.weekday()]} {d.strftime('%d.%m')}: {val} ккал{mark}")
    lines.append("")
    avg = round(week_total / days_with_data) if days_with_data else 0
    lines.append(f"Сумма за неделю: *{week_total}* ккал")
    lines.append(f"Среднее в день (по дням с записями): *{avg}* ккал")
    if goal:
        within = sum(1 for i in range(7)
                     if 0 < by_date.get(start + dt.timedelta(days=i), 0) <= goal)
        lines.append(f"Дней в пределах цели: {within}/{days_with_data or 0}")
    return "\n".join(lines)


# --------------------------------------------------------------- задачи планировщика

async def _daily_job(context):
    """Вызывается раз в день в час пользователя."""
    user_id = context.job.chat_id
    user = await db.get_user(user_id)
    if not user:
        return
    if user["daily_on"]:
        text = await build_daily_text(user)
        await context.bot.send_message(user_id, text, parse_mode="Markdown")
    # недельный — в выбранный день недели
    if user["weekly_on"]:
        today = _today(user["timezone"])
        if today.weekday() == user["weekly_dow"]:
            text = await build_weekly_text(user)
            await context.bot.send_message(user_id, text, parse_mode="Markdown")


def schedule_user(application, user) -> None:
    """(Пере)создать ежедневную задачу для пользователя."""
    jq = application.job_queue
    name = f"report_{user['user_id']}"
    for job in jq.get_jobs_by_name(name):
        job.schedule_removal()
    tz = pytz.timezone(user["timezone"])
    run_at = dt.time(hour=user["daily_hour"], minute=0, tzinfo=tz)
    jq.run_daily(_daily_job, time=run_at, name=name, chat_id=user["user_id"])


async def schedule_all(application) -> None:
    for user in await db.all_users():
        schedule_user(application, user)
