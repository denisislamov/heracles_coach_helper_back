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

_SYSTEM = (
    "Ты — нутрициолог-ассистент, оцениваешь калорийность съеденного по фото и/или "
    "описанию. Важно: люди и модели систематически ЗАНИЖАЮТ калории. Поэтому:\n"
    "• учитывай скрытые калории: масло для жарки, сливочное масло, заправки, соусы, "
    "майонез, сахар, сливки, панировку, сироп;\n"
    "• оцени массу порции в граммах, опираясь на тарелку, столовые приборы и обычные "
    "размеры порций; НЕ занижай порцию;\n"
    "• считай для обычного приготовления, не предполагай «диетическое» без явных причин;\n"
    "• при неопределённости выбирай оценку ближе к ВЕРХНЕЙ границе разумного диапазона.\n"
    "Всегда отвечай ТОЛЬКО валидным JSON без markdown по схеме:\n"
    '{"calories": <int итог, ближе к верхней границе>, '
    '"items": [{"name": <str>, "calories": <int>, "grams": <int примерная масса>}], '
    '"note": <str кратко по-русски: можно указать диапазон и ключевые допущения>}'
)


async def estimate_food(image_bytes: Optional[bytes] = None,
                        caption: Optional[str] = None,
                        model: Optional[str] = None,
                        api_key: Optional[str] = None,
                        detail: str = "low") -> dict:
    """Оценить калорийность по фото и/или тексту.

    model   — какую модель использовать (по умолчанию config.OPENAI_MODEL);
    api_key — ключ пользователя (BYOK); если задан — запрос идёт через него;
    detail  — детализация фото: "high" точнее (дороже), "low" дешевле.
    Возвращает dict: {calories:int, items:list, note:str}.
    """
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
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
        temperature=0.2,
    )
    data = json.loads(resp.choices[0].message.content)
    # нормализация
    data["calories"] = int(round(float(data.get("calories", 0))))
    data.setdefault("items", [])
    data.setdefault("note", "")
    return data


async def diet_advice(goal: int, consumed: int, items_today: list) -> str:
    """Совет по диете, когда пользователь близок к цели или превысил её."""
    remaining = goal - consumed
    items_str = ", ".join(items_today[-10:]) if items_today else "нет данных"
    prompt = (
        f"Дневная цель: {goal} ккал. Уже съедено: {consumed} ккал "
        f"(остаток {remaining}). Что ел сегодня: {items_str}. "
        "Дай 1–2 коротких практичных совета по-русски: чем заменить или что "
        "скорректировать (например, сладкое — фруктами), чтобы остаться в рамках цели. "
        "Без вступлений, дружелюбно, до 400 символов."
    )
    resp = await _client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Ты дружелюбный нутрициолог. Пиши кратко по-русски."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=250,
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()
