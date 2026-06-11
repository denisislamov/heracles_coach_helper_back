"""Инлайн-клавиатуры и тексты меню."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Сегодня", callback_data="today"),
         InlineKeyboardButton("📅 Неделя", callback_data="week")],
        [InlineKeyboardButton("🎯 Изменить цель", callback_data="set_goal")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
    ])


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


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В меню", callback_data="menu")]])
