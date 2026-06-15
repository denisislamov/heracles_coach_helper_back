"""Поиск продукта по штрих-коду в Open Food Facts (бесплатное открытое API)."""
import logging

import httpx

log = logging.getLogger("calbot.foodfacts")

_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
_FIELDS = "product_name,product_name_ru,brands,nutriments"


async def lookup(barcode: str):
    """Вернуть {name, kcal_100g, protein_100g, fat_100g, carb_100g} или None."""
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(_URL.format(code=barcode), params={"fields": _FIELDS},
                                 headers={"User-Agent": "Zhiromer/1.0"})
        data = r.json()
    except Exception as e:
        log.warning("OFF недоступен для %s: %s", barcode, e)
        return None
    if data.get("status") != 1:
        return None
    p = data.get("product", {})
    n = p.get("nutriments", {})
    kcal = n.get("energy-kcal_100g")
    if kcal is None:
        return None
    name = p.get("product_name_ru") or p.get("product_name") or p.get("brands") or "продукт"
    return {
        "name": name[:80],
        "kcal_100g": float(kcal),
        "protein_100g": float(n.get("proteins_100g") or 0),
        "fat_100g": float(n.get("fat_100g") or 0),
        "carb_100g": float(n.get("carbohydrates_100g") or 0),
    }
