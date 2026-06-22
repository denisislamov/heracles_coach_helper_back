"""Дневной и недельный отчёты + планирование их рассылки.

Используем JobQueue из python-telegram-bot. На каждого пользователя создаётся
ОДНА ежедневная задача в его часовом поясе и в выбранный им час. Внутри:
  * всегда (если включён) шлём дневной отчёт;
  * если сегодня — выбранный день недели и включён недельный отчёт, шлём ещё и его.
Это избавляет от зависимости от внутренней нумерации дней в JobQueue.
"""
import datetime as dt
import json

import pytz
from telegram.error import Forbidden

import db
import nutrition
from i18n import t, weekday as _i18n_weekday


def _today(tz_name: str) -> dt.date:
    return dt.datetime.now(pytz.timezone(tz_name)).date()


def _progress_bar(consumed: int, goal: int, width: int = 10) -> str:
    if not goal:
        return ""
    ratio = max(0.0, min(consumed / goal, 1.0))
    filled = round(ratio * width)
    return "▓" * filled + "░" * (width - filled)


def _entry_dishes(entry) -> list:
    """Разбивка приёма по блюдам из items_json (или []), безопасно."""
    raw = entry["items_json"] if "items_json" in entry.keys() else None
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def format_daily(user, day, entries) -> str:
    """Текст дневного отчёта по уже загруженным записям (с нумерацией)."""
    total = sum(e["calories"] for e in entries)
    goal = user["goal"] or 0

    try:
        lang = user["lang"]
    except (KeyError, TypeError):
        lang = "ru"
    lines = [t("daily_title", lang, date=day.strftime('%d.%m.%Y')), ""]
    if entries:
        for i, e in enumerate(entries, 1):
            name = e["item"] or "—"
            lines.append(f"{i}. {name} — {e['calories']} ккал")
            # декомпозиция по блюдам, если у приёма сохранена разбивка
            for dish in _entry_dishes(e):
                dn = dish.get("n") or "—"
                dk = dish.get("k") or 0
                grams = f" ({dish['g']} г)" if dish.get("g") else ""
                macro = ""
                if dish.get("p") is not None and (dish.get("p") or dish.get("f") or dish.get("c")):
                    macro = f" · Б{dish['p']} Ж{dish['f']} У{dish['c']}"
                lines.append(f"    • {dn}{grams} — {dk} ккал{macro}")
    else:
        lines.append(t("no_records", lang))
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

    # Б/Ж/У — показываем, если по дню есть данные макросов (т.е. у КБЖУ-пользователей)
    mp = sum((e["protein_g"] or 0) for e in entries)
    mf = sum((e["fat_g"] or 0) for e in entries)
    mc = sum((e["carb_g"] or 0) for e in entries)
    if (mp or mf or mc):
        pg, fg, cg = nutrition.goals_for_user(user)
        lines.append(f"Б/Ж/У: {mp}/{pg} · {mf}/{fg} · {mc}/{cg} г")
    return "\n".join(lines)


async def build_daily_text(user) -> str:
    day = _today(user["timezone"])
    entries = await db.day_entries(user["user_id"], day)
    return format_daily(user, day, entries)


async def build_weekly_text(user) -> str:
    tz = user["timezone"]
    end = _today(tz)
    start = end - dt.timedelta(days=6)
    rows = await db.range_daily_totals(user["user_id"], start, end)
    by_date = {r["entry_date"]: int(r["total"]) for r in rows}
    goal = user["goal"] or 0
    try:
        lang = user["lang"]
    except (KeyError, TypeError):
        lang = "ru"

    lines = [t("weekly_title", lang) + f" ({start.strftime('%d.%m')}–{end.strftime('%d.%m')})", ""]
    week_total = 0
    days_with_data = 0
    for i in range(7):
        d = start + dt.timedelta(days=i)
        val = by_date.get(d, 0)
        week_total += val
        if val:
            days_with_data += 1
        mark = ""
        if goal and val:
            mark = " ⚠️" if val > goal else " ✅"
        lines.append(f"{_i18n_weekday(d.weekday(), lang)} {d.strftime('%d.%m')}: {val}{mark}")
    lines.append("")
    avg = round(week_total / days_with_data) if days_with_data else 0
    lines.append(t("week_total", lang, v=week_total))
    lines.append(t("week_avg", lang, v=avg))
    if goal:
        within = sum(1 for i in range(7)
                     if 0 < by_date.get(start + dt.timedelta(days=i), 0) <= goal)
        lines.append(t("week_within", lang, a=within, b=days_with_data or 0))
    return "\n".join(lines)


# --------------------------------------------------------------- задачи планировщика

async def _daily_job(context):
    """Вызывается раз в день в час пользователя."""
    user_id = context.job.chat_id
    user = await db.get_user(user_id)
    if not user:
        return
    try:
        if user["daily_on"]:
            text = await build_daily_text(user)
            await context.bot.send_message(user_id, text, parse_mode="Markdown")
        # недельный — в выбранный день недели
        if user["weekly_on"]:
            today = _today(user["timezone"])
            if today.weekday() == user["weekly_dow"]:
                text = await build_weekly_text(user)
                await context.bot.send_message(user_id, text, parse_mode="Markdown")
    except Forbidden:
        # пользователь заблокировал бота — помечаем и снимаем его задачи
        await db.set_blocked(user_id, True)
        for job in context.job_queue.get_jobs_by_name(f"report_{user_id}"):
            job.schedule_removal()


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
    for user in await db.active_users():
        schedule_user(application, user)
