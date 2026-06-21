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
    """Чистое главное меню: дневник, возможности, профиль, настройки."""
    rows = [
        [InlineKeyboardButton(t("btn_today", lang), callback_data="today"),
         InlineKeyboardButton(t("btn_week", lang), callback_data="week")],
        [InlineKeyboardButton(t("btn_extras", lang), callback_data="extras")],
        [InlineKeyboardButton(t("btn_profile", lang), callback_data="profile"),
         InlineKeyboardButton(t("btn_settings", lang), callback_data="settings")],
    ]
    if payments.monetization_enabled():
        rows.append([InlineKeyboardButton(t("btn_premium", lang), callback_data="premium")])
    if payments.referral_enabled():
        rows.append([InlineKeyboardButton(t("btn_invite", lang), callback_data="invite")])
    return InlineKeyboardMarkup(rows)


def extras_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    """Подменю «Возможности»: продвинутые функции, чтобы не грузить главный экран."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_mealplan", lang), callback_data="mealplan"),
         InlineKeyboardButton(t("btn_diet", lang), callback_data="diet")],
        [InlineKeyboardButton(t("btn_fasting", lang), callback_data="fasting")],
        [InlineKeyboardButton(t("btn_favorites", lang), callback_data="favs"),
         InlineKeyboardButton(t("btn_pickdate", lang), callback_data="pickdate")],
        [InlineKeyboardButton(t("btn_survey", lang), callback_data="survey")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


def profile_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопки под просмотром профиля — правка цели/режима/данных."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("prof_edit_goal", lang), callback_data="set_goal"),
         InlineKeyboardButton(t("prof_edit_mode", lang), callback_data="set_mode")],
        [InlineKeyboardButton(t("prof_edit_profile", lang), callback_data="set_profile")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


import fasting as _fasting


def fasting_choose_kb(idx: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Витрина протоколов: листание ◀ idx/n ▶ + начать выбранный."""
    protos = _fasting.PROTOCOLS
    n = len(protos)
    h = protos[idx]
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"fast_nav:{idx-1}"))
    nav.append(InlineKeyboardButton(f"{idx+1}/{n}", callback_data="fast_noop"))
    if idx < n - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"fast_nav:{idx+1}"))
    return InlineKeyboardMarkup([
        nav,
        [InlineKeyboardButton(t("fast_start_btn", lang, proto=_fasting.proto_label(h)),
                              callback_data=f"fast_start:{h}")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


def fasting_active_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("fast_stop_btn", lang), callback_data="fast_stop"),
         InlineKeyboardButton(t("fast_refresh_btn", lang), callback_data="fast_status")],
        [InlineKeyboardButton(t("fast_history_btn", lang), callback_data="fast_history")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


import diets as _diets


def diet_gallery_kb(idx: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Витрина диет: листание ◀ idx/n ▶ + выбрать текущую."""
    keys = _diets.DIETS
    n = len(keys)
    key = keys[idx]
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"diet_nav:{idx-1}"))
    nav.append(InlineKeyboardButton(f"{idx+1}/{n}", callback_data="diet_noop"))
    if idx < n - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"diet_nav:{idx+1}"))
    return InlineKeyboardMarkup([
        nav,
        [InlineKeyboardButton(t("diet_choose_btn", lang), callback_data=f"diet_pick:{key}")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


def diet_chosen_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """После выбора диеты: составить план / посмотреть другие."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("diet_to_plan", lang), callback_data="diet_to_plan")],
        [InlineKeyboardButton(t("diet_other_btn", lang), callback_data="diet_browse")],
        [InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")],
    ])


MEAL_PATTERNS = ["balanced", "mediterranean", "high_protein", "low_carb", "vegetarian"]


def meal_pattern_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(t(f"mp_pat_{p}", lang), callback_data=f"mp_pat:{p}")]
            for p in MEAL_PATTERNS]
    rows.append([InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def meal_skip_restrict_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("mp_skip", lang), callback_data="mp_gen")]])


def mealplan_day_kb(plan: dict, day_idx: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопки приёмов («съесть») + навигация по дням + список покупок/перегенерация."""
    days = plan.get("days", [])
    n = len(days)
    meals = days[day_idx].get("meals", []) if 0 <= day_idx < n else []
    rows = []
    for i, m in enumerate(meals):
        title = (m.get("title") or "")[:30]
        rows.append([InlineKeyboardButton(
            t("mp_eat_btn", lang, title=title), callback_data=f"mp_eat:{day_idx}:{i}")])
    nav = []
    if day_idx > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"mp_day:{day_idx-1}"))
    nav.append(InlineKeyboardButton(f"{day_idx+1}/{n}", callback_data="mp_noop"))
    if day_idx < n - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"mp_day:{day_idx+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(t("mp_shop_btn", lang), callback_data="mp_shop"),
                 InlineKeyboardButton(t("mp_regen_btn", lang), callback_data="mp_regen")])
    rows.append([InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")])
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
        [InlineKeyboardButton(t("s_daily_time", lang, v=f"{user['daily_hour']:02d}:00"),
                              callback_data="set_hour")],
        [InlineKeyboardButton(t("s_weekly_day", lang, v=i18n.weekday(user['weekly_dow'], lang)),
                              callback_data="set_dow")],
        [InlineKeyboardButton(t("s_tz", lang, v=tz_display(user['timezone'])), callback_data="set_tz")],
        [InlineKeyboardButton(t("s_daily", lang, v=on if user["daily_on"] else off), callback_data="toggle_daily"),
         InlineKeyboardButton(t("s_weekly", lang, v=on if user["weekly_on"] else off), callback_data="toggle_weekly")],
        [InlineKeyboardButton(t("s_reminders", lang, v=on if user["reminders_on"] else off), callback_data="toggle_rem"),
         InlineKeyboardButton(t("s_every", lang, n=user['reminder_interval']), callback_data="set_rem_int")],
        [InlineKeyboardButton(t("btn_lang", lang), callback_data="set_lang"),
         InlineKeyboardButton(t("btn_feedback", lang), callback_data="feedback")],
        [InlineKeyboardButton(t("s_reset", lang), callback_data="reset")],
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
        [InlineKeyboardButton(t("act_vhigh", lang), callback_data="pact:very_active")],
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
             InlineKeyboardButton(t("btn_del", lang), callback_data=f"del:{entry_id}"),
             InlineKeyboardButton(t("btn_fav_add", lang), callback_data=f"favadd:{entry_id}")]]
    if backdated:
        rows.append([InlineKeyboardButton(t("back_today", lang), callback_data="date_today")])
    return InlineKeyboardMarkup(rows)


def favorites_menu(favs, lang: str = "ru") -> InlineKeyboardMarkup:
    """Список избранного: тап по строке — добавить сегодня, 🗑 — удалить."""
    rows = []
    for fv in favs:
        name = (fv["name"] or "—")[:24]
        rows.append([
            InlineKeyboardButton(f"➕ {name} · {fv['calories']}", callback_data=f"fav:{fv['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"favdel:{fv['id']}"),
        ])
    rows.append([InlineKeyboardButton(t("btn_back_menu", lang), callback_data="menu")])
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
