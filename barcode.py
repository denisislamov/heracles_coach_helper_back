"""Декодирование штрих-кода из фото (zxing-cpp, без системных зависимостей)."""
import io
import logging

log = logging.getLogger("calbot.barcode")


def decode(image_bytes: bytes):
    """Вернуть строку цифр штрих-кода (EAN/UPC) или None."""
    try:
        import zxingcpp
        from PIL import Image
    except Exception as e:  # библиотеки не установлены
        log.warning("barcode libs недоступны: %s", e)
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        results = zxingcpp.read_barcodes(img)
        for r in results:
            if r.text and r.text.strip().isdigit() and len(r.text.strip()) >= 8:
                return r.text.strip()
    except Exception as e:
        log.warning("Ошибка декодирования штрих-кода: %s", e)
    return None
