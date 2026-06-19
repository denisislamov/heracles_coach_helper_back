"""Чистая логика без БД: доступ, лимиты, тарифы, расчёты, переводы."""
import datetime as dt

import i18n
import nutrition
import payments


def _user(**kw):
    base = dict(premium_until=None, plan="free", goal=2000, goal_mode="lose",
                weight_kg=None, protein_goal=None, fat_goal=None, carb_goal=None,
                credits=0, ai_count_date=dt.date.today(), ai_count_today=0,
                openai_key_enc=None, lang="ru",
                created_at=dt.datetime.now(dt.timezone.utc))
    base.update(kw)
    return base


def setup_function(_):
    # монетизация включена, КБЖУ-тариф включён, лимиты по умолчанию
    payments._settings = {"mon": True, "free_daily": 3, "free_period": 30,
                          "macros_tier": True, "macros_price": 300,
                          "ref_enabled": True, "ref_days": 30, "ref_needed": 1}


def test_access_free_within_period():
    today = dt.date.today()
    assert payments.access_mode(_user(ai_count_today=0), today) == "free"
    assert payments.access_mode(_user(ai_count_today=3), today) == "blocked"  # лимит дня


def test_access_period_expired_blocks():
    today = dt.date.today()
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)
    assert payments.access_mode(_user(ai_count_today=0, created_at=old), today) == "blocked"


def test_access_premium_and_credits():
    today = dt.date.today()
    now = dt.datetime.now(dt.timezone.utc)
    prem = _user(plan="premium", premium_until=now + dt.timedelta(days=5), ai_count_today=99)
    assert payments.access_mode(prem, today) == "premium"
    cred = _user(credits=2, ai_count_today=99)
    assert payments.access_mode(cred, today) == "credit"


def test_monetization_off_unlimited():
    payments._settings["mon"] = False
    today = dt.date.today()
    assert payments.access_mode(_user(ai_count_today=99), today) == "unlimited"


def test_macros_gating():
    now = dt.datetime.now(dt.timezone.utc)
    # монетизация включена: КБЖУ только premium_plus
    assert payments.macros_enabled(_user(plan="free")) is False
    assert payments.macros_enabled(
        _user(plan="premium_plus", premium_until=now + dt.timedelta(days=3))) is True
    # монетизация выключена: КБЖУ всем
    payments._settings["mon"] = False
    assert payments.macros_enabled(_user(plan="free")) is True
    # если тариф КБЖУ выключен — недоступен никому
    payments._settings["macros_tier"] = False
    assert payments.macros_enabled(_user(plan="premium_plus",
                                         premium_until=now + dt.timedelta(days=3))) is False


def test_meal_plan_gating():
    now = dt.datetime.now(dt.timezone.utc)
    # монетизация включена: планы — любой активный Premium (premium или premium_plus)
    assert payments.meal_plan_enabled(_user(plan="free")) is False
    assert payments.meal_plan_enabled(
        _user(plan="premium", premium_until=now + dt.timedelta(days=3))) is True
    assert payments.meal_plan_enabled(
        _user(plan="premium_plus", premium_until=now + dt.timedelta(days=3))) is True
    # монетизация выключена: планы доступны всем
    payments._settings["mon"] = False
    assert payments.meal_plan_enabled(_user(plan="free")) is True


def test_ai_params_model_selection():
    import config
    assert payments.ai_params(_user(), "free")[0] == config.OPENAI_MODEL_FREE
    assert payments.ai_params(_user(), "premium")[0] == config.OPENAI_MODEL


def test_nutrition_calorie_goal_direction():
    base = dict(sex="male", age=30, height_cm=180, weight_kg=80, activity="moderate")
    lose = nutrition.calorie_goal(goal_mode="lose", **base)
    maintain = nutrition.calorie_goal(goal_mode="maintain", **base)
    gain = nutrition.calorie_goal(goal_mode="gain", **base)
    assert lose < maintain < gain  # дефицит < поддержание < профицит


def test_nutrition_macros_consistency():
    # сумма калорий из макросов ~ целевой калорийности (±10%)
    p, f, c = nutrition.macro_goals(2000, "maintain", weight_kg=None)
    kcal = p * 4 + f * 9 + c * 4
    assert abs(kcal - 2000) / 2000 < 0.12


def test_default_goal_by_mode():
    assert nutrition.default_goal("lose") < nutrition.default_goal("gain")


def test_macro_tiers_athlete_vs_general():
    # спортсмен получает больше белка, чем обычный человек при том же весе
    w = 80
    p_ath, _, _ = nutrition.macro_goals(2500, "maintain", weight_kg=w, athlete=True)
    p_gen, _, _ = nutrition.macro_goals(2500, "maintain", weight_kg=w, athlete=False)
    assert p_ath > p_gen
    # обычный режим поддержания ≈ 0,8 г/кг (RDA)
    assert abs(p_gen - round(0.8 * w)) <= 2
    # спортивный режим в диапазоне 1,2–2,0 г/кг
    assert 1.2 * w <= p_ath <= 2.0 * w + 1


def test_macro_goals_sum_matches_calories():
    # при известном весе сумма калорий из Б/Ж/У близка к цели
    p, f, c = nutrition.macro_goals(2500, "maintain", weight_kg=80, athlete=True)
    kcal = p * 4 + f * 9 + c * 4
    assert abs(kcal - 2500) / 2500 < 0.06


def test_macro_ai_params_clamped():
    # значения вне безопасных границ зажимаются
    p, f, c = nutrition.macro_goals(2500, "maintain", weight_kg=80,
                                    protein_per_kg=9.0, fat_pct=99)
    assert p <= round(2.2 * 80) + 1          # белок не выше 2,2 г/кг
    assert f * 9 <= 2500 * 0.35 + 30         # жир не выше ~35% калорий


def test_i18n_key_parity():
    ru = set(i18n._STR["ru"].keys())
    en = set(i18n._STR["en"].keys())
    assert ru == en, f"Несовпадение ключей RU/EN: {ru ^ en}"


def test_i18n_fallback_and_format():
    # неизвестный ключ возвращается как есть
    assert i18n.t("___missing___", "en") == "___missing___"
    # форматирование подставляет параметры на обоих языках
    assert "2000" in i18n.t("goal_set", "ru", goal=2000)
    assert "2000" in i18n.t("goal_set", "en", goal=2000)


def test_norm_lang():
    assert i18n.norm_lang("ru-RU") == "ru"
    assert i18n.norm_lang("en-US") == "en"
    assert i18n.norm_lang("de") == "en"
    assert i18n.norm_lang(None) == "ru"
