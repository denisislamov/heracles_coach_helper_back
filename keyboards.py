"""Инлайн-клавиатуры и тексты меню."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import payments

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎯 Цель: {user['goal'] or '—'} ккал", callback_data="set_goal")],
        [InlineKeyboardButton(f"🕘 Время дн. отчёта: {user['daily_hour']:02d}:00",
                              callback_data="set_hour")],
        [InlineKeyboardButton(f"📆 День нед. отчёта: {WEEKDAYS[user['weekly_dow']]}",
                              callback_data="set_dow")],
        [InlineKeyboardButton(f"🌍 Часовой пояс: {user['timezone']}", callback_data="set_tz")],
        [InlineKeyboardButton(f"Дневной отчёт: {daily}", callback_data="toggle_daily"),
         InlineKeyboardButton(f"Недельный: {weekly}", callback_data="toggle_weekly")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
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
    zones = [
        "Europe/Moscow", "Europe/Kaliningrad", "Europe/Samara",
        "Asia/Yekaterinburg", "Asia/Tbilisi", "Asia/Almaty",
        "Europe/Kyiv", "Europe/Minsk", "Asia/Yerevan", "UTC",
    ]
    rows = [[InlineKeyboardButton(z, callback_data=f"tz:{z}")] for z in zones]
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
