"""Инлайн-клавиатуры и тексты меню."""
import datetime as _dt

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import payments

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Часовые пояса: целые смещения UTC от −12 до +14 — уникальны, покрывают весь мир.
_TZ_OFFSETS = list(range(-12, 15))


def _etc_name(h: int) -> str:
    # POSIX-нотация инвертирует знак: Etc/GMT-3 == UTC+3.
    return "Etc/GMT" if h == 0 else f"Etc/GMT{-h:+d}"


def _offset_label(h: int) -> str:
    return "UTC+0" if h == 0 else (f"UTC+{h}" if h > 0 else f"UTC{h}")


def tz_display(tzname: str) -> str:
    """Человеко-понятное смещение для любого хранимого имени пояса (UTC+3 и т.п.)."""
    try:
        off = pytz.timezone(tzname).utcoffset(_dt.datetime.utcnow())
        mins = int(off.total_seconds() // 60)
        h, m = divmod(abs(mins), 60)
        sign = "+" if mins >= 0 else "-"
        return f"UTC{sign}{h}:{m:02d}" if m else f"UTC{sign}{h}"
    except Exception:
        return tzname


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📊 Сегодня", callback_data="today"),
         InlineKeyboardButton("📅 Неделя", callback_data="week")],
        [InlineKeyboardButton("🎯 Изменить цель", callback_data="set_goal")],
    ]
    if payments.monetization_enabled():
        rows.append([InlineKeyboardButton("⭐ Premium", callback_data="premium")])
    rows.append([InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
                 InlineKeyboardButton("🛟 Обратная связь", callback_data="feedback")])
    return InlineKeyboardMarkup(rows)


def settings_menu(user) -> InlineKeyboardMarkup:
    daily = "🔔 вкл" if user["daily_on"] else "🔕 выкл"
    weekly = "🔔 вкл" if user["weekly_on"] else "🔕 выкл"
    rem = "🔔 вкл" if user["reminders_on"] else "🔕 выкл"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎯 Цель: {user['goal'] or '—'} ккал", callback_data="set_goal")],
        [InlineKeyboardButton(f"🕘 Время дн. отчёта: {user['daily_hour']:02d}:00",
                              callback_data="set_hour")],
        [InlineKeyboardButton(f"📆 День нед. отчёта: {WEEKDAYS[user['weekly_dow']]}",
                              callback_data="set_dow")],
        [InlineKeyboardButton(f"🌍 Часовой пояс: {tz_display(user['timezone'])}", callback_data="set_tz")],
        [InlineKeyboardButton(f"Дневной отчёт: {daily}", callback_data="toggle_daily"),
         InlineKeyboardButton(f"Недельный: {weekly}", callback_data="toggle_weekly")],
        [InlineKeyboardButton(f"⏰ Напоминания: {rem}", callback_data="toggle_rem"),
         InlineKeyboardButton(f"каждые {user['reminder_interval']}ч", callback_data="set_rem_int")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
    ])


def rem_interval_menu() -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in range(2, 9):
        row.append(InlineKeyboardButton(f"{h}ч", callback_data=f"remint:{h}"))
    rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def reminders_onboarding() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Включить напоминания", callback_data="rem_on")],
        [InlineKeyboardButton("🔕 Без напоминаний", callback_data="rem_off")],
    ])


def hours_menu() -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in range(24):
        row.append(InlineKeyboardButton(f"{h:02d}", callback_data=f"hour:{h}"))
        if len(row) == 6:
            rows.append(row); row = []
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def dow_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(WEEKDAYS[i], callback_data=f"dow:{i}")] for i in range(7)]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def tz_menu() -> InlineKeyboardMarkup:
    """Сетка смещений UTC: уникальные, весь мир, по 4 в ряд — аккуратно."""
    rows, row = [], []
    for h in _TZ_OFFSETS:
        row.append(InlineKeyboardButton(_offset_label(h), callback_data=f"tz:{_etc_name(h)}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def entry_actions(entry_id: int) -> InlineKeyboardMarkup:
    """Кнопки под залогированным приёмом пищи — исправить или удалить."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Исправить", callback_data=f"fix:{entry_id}"),
         InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{entry_id}")],
    ])


def day_manage(entries) -> InlineKeyboardMarkup:
    """Клавиатура управления записями за день: у каждой — правка и удаление."""
    rows = []
    for i, e in enumerate(entries, 1):
        name = (e["item"] or "приём")[:18]
        rows.append([
            InlineKeyboardButton(f"✏️ {i}. {name}", callback_data=f"fix:{e['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"ddel:{e['id']}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def keep_goal(goal: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Оставить {goal} ккал", callback_data="keep_goal")],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В меню", callback_data="menu")]])
