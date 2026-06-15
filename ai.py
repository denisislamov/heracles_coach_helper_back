"""ИИ-слой: распознавание еды и оценка калорий через OpenAI GPT-4o (vision).

Возвращает структурированный JSON, чтобы бот мог надёжно достать число калорий.
"""
import base64
import json
from typing import Optional

from openai import AsyncOpenAI

import config

_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)


def _client_for(api_key: Optional[str]):
    """Клиент с ключом пользователя (BYOK) или общий клиент бота."""
    return AsyncOpenAI(api_key=api_key) if api_key else _client

_RULES = (
    "Ты — нутрициолог-ассистент, оцениваешь калорийность съеденного по фото и/или "
    "описанию. Важно: люди и модели систематически ЗАНИЖАЮТ калории. Поэтому:\n"
    "• учитывай скрытые калории: масло для жарки, сливочное масло, заправки, соусы, "
    "майонез, сахар, сливки, панировку, сироп;\n"
    "• оцени массу порции в граммах, опираясь на тарелку, столовые приборы и обычные "
    "размеры порций; НЕ занижай порцию;\n"
    "• считай для обычного приготовления, не предполагай «диетическое» без явных причин;\n"
    "• при неопределённости выбирай оценку ближе к ВЕРХНЕЙ границе разумного диапазона.\n"
)

# Схема ответа без макросов и с макросами (поля Б/Ж/У встроены прямо в схему!).
_SCHEMA_BASE = (
    "Всегда отвечай ТОЛЬКО валидным JSON без markdown по схеме:\n"
    '{"calories": <int итог>, '
    '"items": [{"name": <str>, "calories": <int>, "grams": <int>}], '
    '"note": <str кратко по-русски>}'
)
_SCHEMA_MACROS = (
    "Всегда отвечай ТОЛЬКО валидным JSON без markdown по схеме (ОБЯЗАТЕЛЬНО заполни "
    "protein_g/fat_g/carb_g для каждой позиции и итог, в граммах, ~4/9/4 ккал на грамм):\n"
    '{"calories": <int итог>, "protein_g": <int>, "fat_g": <int>, "carb_g": <int>, '
    '"items": [{"name": <str>, "calories": <int>, "grams": <int>, '
    '"protein_g": <int>, "fat_g": <int>, "carb_g": <int>}], '
    '"note": <str кратко по-русски>}'
)


_LANG_NAME = {"ru": "русском", "en": "English"}


def _system_prompt(include_macros: bool, lang: str = "ru") -> str:
    lang_line = f"\nОтвечай (поля name и note) на языке: {_LANG_NAME.get(lang, 'русском')}.\n"
    return _RULES + lang_line + (_SCHEMA_MACROS if include_macros else _SCHEMA_BASE)


async def estimate_food(image_bytes: Optional[bytes] = None,
                        caption: Optional[str] = None,
                        model: Optional[str] = None,
                        api_key: Optional[str] = None,
                        detail: str = "low",
                        include_macros: bool = False,
                        lang: str = "ru") -> dict:
    """Оценить калорийность (и опц. КБЖУ) по фото и/или тексту.

    model   — какую модель использовать (по умолчанию config.OPENAI_MODEL);
    api_key — ключ пользователя (BYOK); если задан — запрос идёт через него;
    detail  — детализация фото: "high" точнее (дороже), "low" дешевле;
    include_macros — просить также белки/жиры/углеводы.
    Возвращает dict: {calories:int, items:list, note:str[, protein_g, fat_g, carb_g]}.
    """
    system = _system_prompt(include_macros, lang)
    content = []
    user_text = caption.strip() if caption else ""
    if user_text:
        content.append({"type": "text",
                        "text": f"Описание от пользователя: {user_text}"})
    else:
        content.append({"type": "text",
                        "text": "Оцени калорийность блюда на фото."})

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}",
                          "detail": "high" if detail == "high" else "low"},
        })

    resp = await _client_for(api_key).chat.completions.create(
        model=model or config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        max_tokens=600,
        temperature=0.2,
    )
    data = json.loads(resp.choices[0].message.content)
    # нормализация
    data["calories"] = int(round(float(data.get("calories", 0))))
    data.setdefault("items", [])
    data.setdefault("note", "")
    if include_macros:
        items = data.get("items") or []
        for key in ("protein_g", "fat_g", "carb_g"):
            def _num(v):
                try:
                    return int(round(float(v or 0)))
                except (TypeError, ValueError):
                    return 0
            items_sum = sum(_num(it.get(key)) for it in items)
            # берём сумму по позициям, если она есть; иначе — итог верхнего уровня
            data[key] = items_sum if items_sum > 0 else _num(data.get(key))
    return data


_GOAL_MODE_HINT = {
    "lose": "Цель — похудение (дефицит калорий). Если близко к лимиту или превышение — "
            "посоветуй, что урезать/чем заменить.",
    "maintain": "Цель — поддержание веса. Помоги держаться в коридоре калорий.",
    "gain": "Цель — набор массы (профицит). Если калорий/белка не добирает — посоветуй, "
            "что добавить (сложные углеводы, белок).",
}


async def transcribe(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Распознать речь из голосового сообщения (Whisper). Возвращает текст."""
    resp = await _client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, audio_bytes),
    )
    return (resp.text or "").strip()


_MACRO_PROFILE_SYSTEM = (
    "Ты — спортивный нутрициолог. По профилю и виду спорта подбираешь дневные нормы "
    "макронутриентов, опираясь на действующие референсы:\n"
    "• ACSM/AND/DC 'Nutrition and Athletic Performance' (2016) и ISSN (Jäger 2017, "
    "Kerksick 2018): для регулярно тренирующихся белок 1,2–2,0 г/кг, углеводы 3–12 г/кг "
    "(выносливость/большой объём — выше углеводы; сила/телосложение — выше белок).\n"
    "• Для нетренирующихся / лёгкой активности — обычные нормы (DRI/ВОЗ): белок ~0,8–1,0 г/кг, "
    "жиры 20–35% калорий, углеводы 45–65%.\n"
    "Учитывай цель: похудение → выше белок (сохранить мышцы), набор → выше углеводы.\n"
    "Поле athlete=true только если человек реально часто/интенсивно тренируется."
)


async def suggest_macro_profile(sex, age, height_cm, weight_kg, activity, goal_mode,
                                sport: str, lang: str = "ru") -> Optional[dict]:
    """По виду спорта и профилю вернуть рекомендованные нормы макросов.

    Возвращает {"athlete": bool, "protein_per_kg": float, "fat_pct": int, "note": str}
    или None при сбое/невалидном ответе. Значения вызывающий код дополнительно зажимает
    в безопасные границы (nutrition.macro_goals).
    """
    goal_map = {"lose": "похудение (дефицит)", "maintain": "поддержание", "gain": "набор массы"}
    prompt = (
        f"Профиль: пол {sex}, возраст {age}, рост {height_cm} см, вес {weight_kg} кг, "
        f"уровень активности '{activity}', цель — {goal_map.get(goal_mode, goal_mode)}. "
        f"Вид спорта (со слов пользователя): «{sport}». "
        "Подбери дневные нормы. Ответь ТОЛЬКО валидным JSON без markdown по схеме:\n"
        '{"athlete": <bool>, "protein_per_kg": <float 0.8-2.2>, "fat_pct": <int 20-35>, '
        '"note": <строка до 100 символов, кратко на языке пользователя>}'
    )
    try:
        resp = await _client.chat.completions.create(
            model=config.OPENAI_MODEL_FREE,
            messages=[
                {"role": "system", "content": _MACRO_PROFILE_SYSTEM
                 + f"\nПоле note пиши на языке: {_LANG_NAME.get(lang, 'русском')}."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.2,
        )
        data = json.loads(resp.choices[0].message.content)
        return {
            "athlete": bool(data.get("athlete")),
            "protein_per_kg": float(data.get("protein_per_kg")),
            "fat_pct": int(round(float(data.get("fat_pct")))),
            "note": (data.get("note") or "").strip()[:200],
        }
    except Exception:
        return None


async def diet_advice(goal: int, consumed: int, items_today: list,
                      goal_mode: str = "lose", macros: dict = None,
                      macro_goals: dict = None, lang: str = "ru") -> str:
    """Совет по питанию с учётом режима цели и (опц.) дефицита макросов."""
    remaining = goal - consumed
    items_str = ", ".join(items_today[-10:]) if items_today else "нет данных"
    macro_line = ""
    if macros and macro_goals:
        macro_line = (
            f" Макросы за день: белки {macros.get('protein',0)}/{macro_goals.get('protein','?')} г, "
            f"жиры {macros.get('fat',0)}/{macro_goals.get('fat','?')} г, "
            f"углеводы {macros.get('carb',0)}/{macro_goals.get('carb','?')} г. "
            "Если какого-то нутриента сильно не хватает — подскажи продукты."
        )
    prompt = (
        f"{_GOAL_MODE_HINT.get(goal_mode, _GOAL_MODE_HINT['lose'])} "
        f"Дневная цель: {goal} ккал. Уже съедено: {consumed} ккал (остаток {remaining}). "
        f"Что ел сегодня: {items_str}.{macro_line} "
        f"Дай 1–2 коротких практичных совета на языке: {_LANG_NAME.get(lang, 'русском')}, в духе цели. "
        "Без вступлений, дружелюбно, до 400 символов."
    )
    resp = await _client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system",
             "content": f"Ты дружелюбный нутрициолог. Пиши кратко на языке: {_LANG_NAME.get(lang, 'русском')}."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=250,
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()
