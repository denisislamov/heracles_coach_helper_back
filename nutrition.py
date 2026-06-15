"""Расчёт калорийной цели и целей по макронутриентам (Б/Ж/У).

Нормы опираются на действующие референсы:
  • Энергия: DRI for Energy (NASEM, 2023) — здесь приближается уравнением Mifflin-St Jeor.
  • Обычные нормы Б/Ж/У: DRI 2002/2005 (белок 0,8 г/кг RDA; жиры 20–35%; углеводы 45–65%,
    минимум 130 г) и ВОЗ 2023 (общий жир ≤30%).
  • Спортивные нормы: ACSM/AND/DC «Nutrition and Athletic Performance» (2016) и ISSN
    (Jäger 2017, Kerksick 2018): белок 1,2–2,0 г/кг, углеводы 3–12 г/кг.
Это общепринятые приближения, не медицинская рекомендация.
"""

ACTIVITY_FACTORS = {
    "sedentary": 1.2,    # сидячий
    "light": 1.375,      # лёгкая активность 1-3 р/нед
    "moderate": 1.55,    # средняя 3-5 р/нед
    "active": 1.725,     # высокая 6-7 р/нед
    "very_active": 1.9,  # очень высокая / 2 тренировки в день
}

# Уровни активности, при которых по умолчанию берём «спортивные» нормы.
ATHLETE_ACTIVITIES = {"active", "very_active"}

# Поправка калорий под режим цели.
GOAL_FACTORS = {"lose": 0.85, "maintain": 1.0, "gain": 1.10}

# Безопасные границы для значений, приходящих от ИИ.
PROTEIN_PER_KG_RANGE = (0.8, 2.2)
FAT_PCT_RANGE = (20, 35)
CARB_MIN_G = 130   # минимум углеводов в день (DRI)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def calorie_goal(sex, age, height_cm, weight_kg, activity, goal_mode) -> int:
    """Mifflin-St Jeor × активность × поправка под режим. Округление до 10 ккал."""
    s = 5 if (sex or "").lower().startswith("m") else -161
    bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + s
    tdee = bmr * ACTIVITY_FACTORS.get(activity, 1.2)
    target = tdee * GOAL_FACTORS.get(goal_mode, 1.0)
    return max(1000, int(round(target / 10) * 10))


def is_athlete_activity(activity: str) -> bool:
    return (activity or "") in ATHLETE_ACTIVITIES


def default_macro_params(activity: str, goal_mode: str) -> tuple:
    """Дефолтные параметры макросов без ИИ: (athlete, protein_per_kg, fat_pct).

    Спортивные нормы — для высокой активности; иначе обычные (DRI/ВОЗ).
    """
    if is_athlete_activity(activity):
        protein = {"lose": 2.0, "maintain": 1.6, "gain": 1.8}.get(goal_mode, 1.6)
        return True, protein, 25
    # обычные: белок ~0,8 г/кг (RDA), при похудении чуть выше для сохранения мышц (в пределах AMDR)
    protein = {"lose": 1.2, "maintain": 0.8, "gain": 1.0}.get(goal_mode, 0.8)
    return False, protein, 30


def macro_goals(calorie_goal_kcal: int, goal_mode: str, weight_kg: int = None,
                athlete: bool = None, protein_per_kg: float = None,
                fat_pct: float = None) -> tuple:
    """Возвращает (protein_g, fat_g, carb_g).

    Если задан вес — белок от массы тела (г/кг), жиры — % калорийности (с полом 0,8 г/кг),
    углеводы — остаток (не ниже разумного минимума). Параметры protein_per_kg/fat_pct,
    если переданы (напр. от ИИ под вид спорта), имеют приоритет; иначе берутся дефолты
    по уровню активности (через athlete) и режиму цели.
    Без веса — проценты под режим цели (DRI AMDR).
    """
    if weight_kg:
        if protein_per_kg is None or fat_pct is None:
            d_athlete, d_protein, d_fat = default_macro_params(
                "active" if athlete else "", goal_mode)
            protein_per_kg = protein_per_kg if protein_per_kg is not None else d_protein
            fat_pct = fat_pct if fat_pct is not None else d_fat
        protein_per_kg = _clamp(float(protein_per_kg), *PROTEIN_PER_KG_RANGE)
        fat_pct = _clamp(float(fat_pct), *FAT_PCT_RANGE)
        protein = round(weight_kg * protein_per_kg)
        fat = round(calorie_goal_kcal * (fat_pct / 100.0) / 9)
        fat = max(fat, round(weight_kg * 0.8))  # пол по жиру (≈0,8 г/кг)
        carb_kcal = calorie_goal_kcal - (protein * 4 + fat * 9)
        carb = round(carb_kcal / 4)
        # минимум углеводов (DRI 130 г), но только если калорий хватает
        if carb < CARB_MIN_G and (protein * 4 + fat * 9 + CARB_MIN_G * 4) <= calorie_goal_kcal:
            carb = CARB_MIN_G
        carb = max(0, carb)
        return protein, fat, carb
    # без веса — по процентам (Б/Ж/У), DRI AMDR
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
    """Цели Б/Ж/У для пользователя: явные из профиля или авто из цели/режима/веса.

    Сохранённые protein_goal/fat_goal/carb_goal (в т.ч. подобранные ИИ под вид спорта)
    имеют приоритет. Иначе считаем на лету, выбирая спортивные/обычные нормы по активности.
    """
    if user.get("protein_goal"):
        return (user["protein_goal"], user.get("fat_goal") or 0, user.get("carb_goal") or 0)
    return macro_goals(user.get("goal") or 2000,
                       user.get("goal_mode") or "lose", user.get("weight_kg"),
                       athlete=is_athlete_activity(user.get("activity")))
