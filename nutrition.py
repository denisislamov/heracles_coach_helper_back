"""Расчёт калорийной цели и целей по макронутриентам (Б/Ж/У).

Используется опциональным мастером «Посчитать за меня». Все формулы —
общепринятые приближения, не медицинская рекомендация.
"""

ACTIVITY_FACTORS = {
    "sedentary": 1.2,    # сидячий
    "light": 1.375,      # лёгкая активность 1-3 р/нед
    "moderate": 1.55,    # средняя 3-5 р/нед
    "active": 1.725,     # высокая 6-7 р/нед
}

# Поправка калорий под режим цели.
GOAL_FACTORS = {"lose": 0.85, "maintain": 1.0, "gain": 1.10}


def calorie_goal(sex, age, height_cm, weight_kg, activity, goal_mode) -> int:
    """Mifflin-St Jeor × активность × поправка под режим. Округление до 10 ккал."""
    s = 5 if (sex or "").lower().startswith("m") else -161
    bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + s
    tdee = bmr * ACTIVITY_FACTORS.get(activity, 1.2)
    target = tdee * GOAL_FACTORS.get(goal_mode, 1.0)
    return max(1000, int(round(target / 10) * 10))


def macro_goals(calorie_goal_kcal: int, goal_mode: str, weight_kg: int = None) -> tuple:
    """Возвращает (protein_g, fat_g, carb_g).

    Если задан вес — белок/жиры от массы тела, остальное углеводы.
    Иначе — проценты под режим цели.
    """
    if weight_kg:
        protein_per_kg = {"lose": 2.0, "maintain": 1.6, "gain": 1.8}.get(goal_mode, 1.8)
        protein = round(weight_kg * protein_per_kg)
        fat = round(weight_kg * 0.9)
        carb_kcal = calorie_goal_kcal - (protein * 4 + fat * 9)
        carb = max(0, round(carb_kcal / 4))
        return protein, fat, carb
    # по процентам (Б/Ж/У)
    pct = {"lose": (0.30, 0.25, 0.45),
           "maintain": (0.25, 0.30, 0.45),
           "gain": (0.25, 0.25, 0.50)}.get(goal_mode, (0.25, 0.30, 0.45))
    p, f, c = pct
    return (round(calorie_goal_kcal * p / 4),
            round(calorie_goal_kcal * f / 9),
            round(calorie_goal_kcal * c / 4))


DEFAULT_GOAL_BY_MODE = {"lose": 1800, "maintain": 2200, "gain": 2600}


def default_goal(goal_mode: str) -> int:
    """Стандартная калорийная цель под режим, если пользователь «доверился нам»."""
    return DEFAULT_GOAL_BY_MODE.get(goal_mode, 2000)


def goals_for_user(user) -> tuple:
    """Цели Б/Ж/У для пользователя: явные из профиля или авто из цели/режима/веса."""
    if user.get("protein_goal"):
        return (user["protein_goal"], user.get("fat_goal") or 0, user.get("carb_goal") or 0)
    return macro_goals(user.get("goal") or 2000,
                       user.get("goal_mode") or "lose", user.get("weight_kg"))
