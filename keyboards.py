"""Инлайн-клавиатуры и тексты меню."""
import datetime as _dt

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import i18n
from i18n import t
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


def main_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(t("btn_today", lang), callback_data="today"),
         InlineKeyboardButton(t("btn_week", lang), callback_data="week")],
        [InlineKeyboardButton(t("btn_pickdate", lang), callback_data="pickdate")],
        [InlineKeyboardButton(t("btn_set_goal", lang), callback_data="set_goal")],
        [InlineKeyboardButton(t("btn_mode", lang), callback_data="set_mode"),
         InlineKeyboardButton(t("btn_profile", lang), callback_data="set_profile")],
    ]
    if payments.monetization_enabled():
        rows.append([InlineKeyboardButton(t("btn_premium", lang), callback_data="premium")])
    if payments.referral_enabled():
        rows.append([InlineKeyboardButton(t("btn_invite", lang), callback_data="invite")])
    rows.append([InlineKeyboardButton(t("btn_settings", lang), callback_data="settings"),
                 InlineKeyboardButton(t("btn_feedback", lang), callback_data="feedback")])
    return InlineKeyboardMarkup(rows)


def goal_mode_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("mode_lose", lang), callback_data="gm:lose")],
        [InlineKeyboardButton(t("mode_maintain", lang), callback_data="gm:maintain")],
        [InlineKeyboardButton(t("mode_gain", lang), callback_data="gm:gain")],
    ])


def lang_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in i18n.lang_menu_keyboard()])


GOAL_MODE_LABELS = {"lose": "Похудение", "maintain": "Поддержание", "gain": "Набор массы"}
_MODE_KEY = {"lose": "m_lose", "maintain": "m_maintain", "gain": "m_gain"}


def settings_menu(user) -> InlineKeyboardMarkup:
    lang = user["lang"]
    on, off = t("on", lang), t("off", lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("s_goal", lang, v=user['goal'] or '—'), callback_data="set_goal")],
        [InlineKeyboardButton(t("s_daily_time", lang, v=f"{user['daily_hour']:02d}:00"),
                              callback_data="set_hour")],
        [InlineKeyboardButton(t("s_weekly_day", lang, v=i18n.weekday(user['weekly_dow'], lang)),
                              callback_data="set_dow")],
        [InlineKeyboardButton(t("s_tz", lang, v=tz_display(user['timezone'])), callback_data="set_tz")],
        [InlineKeyboardButton(t("s_daily", lang, v=on if user["daily_on"] else off), callback_data="toggle_daily"),
         InlineKeyboardButton(t("s_weekly", lang, v=on if user["weekly_on"] else off), callback_data="toggle_weekly")],
        [InlineKeyboardButton(t("s_reminders", lang, v=on if user["reminders_on"] else off), callback_data="toggle_rem"),
         InlineKeyboardButton(t("s_every", lang, n=user['reminder_interval']), callback_data="set_rem_int")],
        [InlineKeyboardButton(t("s_mode", lang, v=t(_MODE_KEY.get(user['goal_mode'], 'm_lose'), lang)),
                              callback_data="set_mode"),
         InlineKeyboardButton(t("s_profile", lang), callback_data="set_profile")],
        [InlineKeyboardButton(t("btn_lang", lang), callback_data="set_lang"),
         InlineKeyboardButton(t("s_reset", lang), callback_data="reset")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu")],
    ])


def rem_interval_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{h}ч", callback_data=f"remint:{h}") for h in range(2, 9)]]
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def reminders_onboarding(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("rem_on_btn", lang), callback_data="rem_on")],
        [InlineKeyboardButton(t("rem_off_btn", lang), callback_data="rem_off")],
    ])


def reset_confirm(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("reset_yes", lang), callback_data="reset_yes")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


def goal_confirm(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("goal_ok", lang), callback_data="goal_ok")],
        [InlineKeyboardButton(t("goal_edit", lang), callback_data="set_goal")],
    ])


def setup_method_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("setup_profile", lang), callback_data="calc_profile")],
        [InlineKeyboardButton(t("setup_trust", lang), callback_data="trust_default")],
        [InlineKeyboardButton(t("setup_manual", lang), callback_data="manual_goal")],
    ])


def sex_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("sex_male", lang), callback_data="psex:male"),
         InlineKeyboardButton(t("sex_female", lang), callback_data="psex:female")],
    ])


def activity_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("act_sed", lang), callback_data="pact:sedentary")],
        [InlineKeyboardButton(t("act_light", lang), callback_data="pact:light")],
        [InlineKeyboardButton(t("act_mod", lang), callback_data="pact:moderate")],
        [InlineKeyboardButton(t("act_active", lang), callback_data="pact:active")],
    ])


def hours_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in range(24):
        row.append(InlineKeyboardButton(f"{h:02d}", callback_data=f"hour:{h}"))
        if len(row) == 6:
            rows.append(row); row = []
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def dow_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(i18n.weekday(i, lang), callback_data=f"dow:{i}")] for i in range(7)]
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def tz_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    """Сетка смещений UTC: уникальные, весь мир, по 4 в ряд."""
    rows, row = [], []
    for h in _TZ_OFFSETS:
        row.append(InlineKeyboardButton(_offset_label(h), callback_data=f"tz:{_etc_name(h)}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def entry_actions(entry_id: int, backdated: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(t("btn_fix", lang), callback_data=f"fix:{entry_id}"),
             InlineKeyboardButton(t("btn_del", lang), callback_data=f"del:{entry_id}")]]
    if backdated:
        rows.append([InlineKeyboardButton(t("back_today", lang), callback_data="date_today")])
    return InlineKeyboardMarkup(rows)


def backdate_menu(today, lang: str = "ru") -> InlineKeyboardMarkup:
    def cb(d):
        return f"setdate:{d.isoformat()}"
    rows = [[
        InlineKeyboardButton(t("btn_today", lang).replace("📊 ", ""), callback_data=cb(today)),
        InlineKeyboardButton("−1", callback_data=cb(today - _dt.timedelta(days=1))),
        InlineKeyboardButton("−2", callback_data=cb(today - _dt.timedelta(days=2))),
    ]]
    row = [InlineKeyboardButton((today - _dt.timedelta(days=i)).strftime("%d.%m"),
                                callback_data=cb(today - _dt.timedelta(days=i))) for i in range(3, 8)]
    rows.append(row)
    rows.append([InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def day_manage(entries, backdated: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = []
    for i, e in enumerate(entries, 1):
        name = (e["item"] or "—")[:18]
        rows.append([
            InlineKeyboardButton(f"✏️ {i}. {name}", callback_data=f"fix:{e['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"ddel:{e['id']}"),
        ])
    if backdated:
        rows.append([InlineKeyboardButton(t("back_today", lang), callback_data="date_today")])
    rows.append([InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def back_to_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")]])
