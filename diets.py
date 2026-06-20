"""Каталог доказанных стилей питания для витрины «Моя диета».

Контент курируемый (без ИИ): быстро, точно, образовательно. Двуязычный.
Это не медицинская рекомендация.
"""

# Порядок показа в витрине (средиземноморская первой — самый доказанный паттерн).
DIETS = ["mediterranean", "balanced", "high_protein", "low_carb", "vegetarian", "dash"]

EMOJI = {"mediterranean": "🫒", "balanced": "🥗", "high_protein": "🍗",
         "low_carb": "🥑", "vegetarian": "🌱", "dash": "🥬"}

_CAT = {
    "mediterranean": {
        "ru": {"name": "Средиземноморская",
               "essence": "овощи, фрукты, рыба, оливковое масло, орехи, цельные злаки; мало красного мяса и сахара.",
               "best": "здоровье сердца, долголетие, мягкое снижение веса. Универсальный выбор.",
               "level": "низкая",
               "note": "Самый изученный и доказанный паттерн (исследование PREDIMED)."},
        "en": {"name": "Mediterranean",
               "essence": "vegetables, fruit, fish, olive oil, nuts, whole grains; little red meat and sugar.",
               "best": "heart health, longevity, gentle weight loss. A universal choice.",
               "level": "low",
               "note": "The most studied, evidence-based pattern (PREDIMED trial)."},
    },
    "balanced": {
        "ru": {"name": "Сбалансированная",
               "essence": "всего понемногу без жёстких запретов; баланс белков, жиров и углеводов.",
               "best": "если не хочешь ограничений и просто питаешься нормально.",
               "level": "низкая", "note": ""},
        "en": {"name": "Balanced",
               "essence": "a bit of everything, no hard bans; a balance of protein, fat and carbs.",
               "best": "if you don't want restrictions and just eat normally.",
               "level": "low", "note": ""},
    },
    "high_protein": {
        "ru": {"name": "Высокобелковая",
               "essence": "повышенная доля белка (мясо, рыба, яйца, творог, бобовые), умеренные углеводы.",
               "best": "снижение веса с сохранением мышц и набор массы; для тренирующихся.",
               "level": "средняя", "note": ""},
        "en": {"name": "High-protein",
               "essence": "more protein (meat, fish, eggs, dairy, legumes), moderate carbs.",
               "best": "losing weight while keeping muscle, or gaining mass; for people who train.",
               "level": "medium", "note": ""},
    },
    "low_carb": {
        "ru": {"name": "Низкоуглеводная",
               "essence": "меньше углеводов (хлеб, сахар, крупы), больше белка и полезных жиров.",
               "best": "контроль аппетита и сахара в крови; быстрый старт похудения.",
               "level": "средняя", "note": ""},
        "en": {"name": "Low-carb",
               "essence": "fewer carbs (bread, sugar, grains), more protein and healthy fats.",
               "best": "appetite and blood-sugar control; a quick start to weight loss.",
               "level": "medium", "note": ""},
    },
    "vegetarian": {
        "ru": {"name": "Вегетарианская",
               "essence": "без мяса и рыбы; упор на бобовые, тофу, яйца/молочное, овощи и злаки.",
               "best": "растительный выбор; следи за белком и витамином B12.",
               "level": "средняя", "note": ""},
        "en": {"name": "Vegetarian",
               "essence": "no meat or fish; focus on legumes, tofu, eggs/dairy, veg and grains.",
               "best": "a plant-forward choice; watch protein and vitamin B12.",
               "level": "medium", "note": ""},
    },
    "dash": {
        "ru": {"name": "DASH",
               "essence": "много овощей, фруктов и цельных злаков; мало соли, сахара и насыщенных жиров.",
               "best": "снижение давления и здоровье сердца.",
               "level": "низкая", "note": "Доказанно снижает артериальное давление."},
        "en": {"name": "DASH",
               "essence": "lots of vegetables, fruit and whole grains; low salt, sugar and saturated fat.",
               "best": "lowering blood pressure and heart health.",
               "level": "low", "note": "Proven to lower blood pressure."},
    },
}

_LBL = {
    "ru": {"essence": "Суть", "best": "Кому подходит", "level": "Сложность"},
    "en": {"essence": "What it is", "best": "Best for", "level": "Difficulty"},
}


def name(key: str, lang: str) -> str:
    d = _CAT.get(key, _CAT["balanced"]).get(lang, _CAT["balanced"]["ru"])
    return f"{EMOJI.get(key, '🍽')} {d['name']}"


def card(key: str, lang: str, idx: int = None, total: int = None) -> str:
    d = _CAT.get(key, _CAT["balanced"]).get(lang, _CAT["balanced"]["ru"])
    lbl = _LBL.get(lang, _LBL["ru"])
    counter = f"  ({idx + 1}/{total})" if idx is not None and total else ""
    text = (f"{EMOJI.get(key, '🍽')} *{d['name']}*{counter}\n\n"
            f"*{lbl['essence']}:* {d['essence']}\n"
            f"*{lbl['best']}:* {d['best']}\n"
            f"*{lbl['level']}:* {d['level']}")
    if d.get("note"):
        text += f"\n\n_{d['note']}_"
    return text
