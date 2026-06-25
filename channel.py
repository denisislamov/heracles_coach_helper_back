"""Автогенерация новостей: случайный SEO-промт → ИИ-новость + картинка →
публикация на сайт (таблица news) и в Telegram-канал.

Настройки в админке (таблица settings):
  * channel_enabled — вкл/выкл;
  * channel_per_day — сколько новостей в сутки (2–4 и т.п.);
  * channel_topics — набор шаблонных промтов с SEO-словами (по одному на строку),
    выбирается случайный.
Бот должен быть админом канала (config.CHANNEL_ID). Картинка обязательна.
"""
import datetime as dt
import logging
import random
import re

import ai
import config
import db

log = logging.getLogger("calbot.channel")

# Рубрика «Миф ❌ / Правда ✅» про КБЖУ (калории, белки/жиры/углеводы). SEO-ключи вшиты.
# Формат поста: заголовок «Миф vs правда: …», в тексте «❌ Миф: …» и «✅ Правда: …».
_FMT = ("Рубрика «Миф vs правда» про КБЖУ. В заголовке начни со слов «Миф vs правда:». "
        "В тексте чётко раздели: строка «❌ Миф: …» и строка «✅ Правда: …» (по ВОЗ/доказательной "
        "базе). Обязательно про калории и/или белки-жиры-углеводы. Тема и ключи: ")
DEFAULT_PROMPTS = [
    _FMT + "«жиры — это вредно, их надо убрать». Ключи: жиры, КБЖУ, калории, здоровое питание.",
    _FMT + "«считать калории бесполезно». Ключи: подсчёт калорий, счётчик калорий, КБЖУ, дневник питания.",
    _FMT + "«углеводы вечером превращаются в жир». Ключи: углеводы, КБЖУ, калории.",
    _FMT + "«белок можно есть сколько угодно без вреда». Ключи: белок, норма белка, КБЖУ.",
    _FMT + "«обезжиренные продукты помогают похудеть». Ключи: жиры, калории, КБЖУ, похудение.",
    _FMT + "«фрукты можно есть без ограничений». Ключи: углеводы, сахар, калории, КБЖУ.",
    _FMT + "«главное — не калории, а время приёма пищи». Ключи: калории, КБЖУ, дефицит калорий.",
    _FMT + "«чтобы похудеть, надо просто меньше есть». Ключи: КБЖУ, белок, калории, похудение.",
    _FMT + "«после 18:00 есть нельзя». Ключи: калории, КБЖУ, дефицит калорий, похудение.",
    _FMT + "«сахар нужно полностью исключить». Ключи: сахар, углеводы, калории, КБЖУ.",
    _FMT + "«орехи и авокадо — ПП, можно без счёта». Ключи: жиры, калории, КБЖУ.",
    _FMT + "«салат всегда низкокалориен». Ключи: калории, жиры, заправка, КБЖУ.",
    _FMT + "«есть жиросжигающие продукты». Ключи: калории, КБЖУ, похудение, дефицит калорий.",
    _FMT + "«чем больше белка, тем больше мышц — автоматически». Ключи: белок, КБЖУ, норма белка.",
    _FMT + "«калории из «чистой» еды можно не считать». Ключи: калории, КБЖУ, подсчёт калорий.",
    _FMT + "«кето/безуглеводка — единственный путь похудеть». Ключи: углеводы, КБЖУ, калории, похудение.",
    _FMT + "«детокс и вода с лимоном сжигают жир». Ключи: калории, КБЖУ, похудение.",
    _FMT + "«дефицит калорий замедляет метаболизм навсегда». Ключи: калории, дефицит калорий, КБЖУ.",
]

CHECK_INTERVAL = 1800   # как часто проверять, не пора ли публиковать (сек)
ACTIVE_HOURS = 14       # окно, на которое равномерно «размазываем» публикации


def _truthy(v):
    return v is not None and str(v).strip().lower() in ("1", "true", "yes", "on")


async def _prompts() -> list:
    raw = await db.get_setting("channel_topics")
    items = [s.strip() for s in (raw or "").splitlines() if s.strip()]
    return items or DEFAULT_PROMPTS


def _slug(title: str) -> str:
    translit = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i',
                'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
                'у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'',
                'э':'e','ю':'yu','я':'ya'}
    s = "".join(translit.get(ch, ch) for ch in (title or "").lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50] or "news"
    return f"{s}-{dt.datetime.now().strftime('%m%d%H%M')}"


async def _bot_link(context) -> str:
    me = await context.bot.get_me()
    return f"https://t.me/{me.username}?start=channel"


async def _job(context) -> None:
    if not _truthy(await db.get_setting("channel_enabled")):
        return
    try:
        per_day = max(1, int(await db.get_setting("channel_per_day") or 2))
    except (TypeError, ValueError):
        per_day = 2
    if await db.channel_posts_today() >= per_day:
        return
    last = await db.last_channel_post_at()
    min_gap = dt.timedelta(hours=max(1.0, ACTIVE_HOURS / per_day))
    if last and (dt.datetime.now(dt.timezone.utc) - last) < min_gap:
        return

    prompt = random.choice(await _prompts())
    news = await ai.generate_news(prompt)
    if not news:
        log.warning("channel: не удалось сгенерировать новость")
        return
    image_url = await ai.generate_image(news["image_prompt"])
    if not image_url:
        log.warning("channel: нет картинки — публикация пропущена")
        await _notify_admins(context, "⚠️ Новости: не удалось сгенерировать картинку, публикация пропущена.")
        return

    # 1) на сайт (таблица news) — запоминаем id, чтобы потом дописать постоянный file_id
    news_id = None
    try:
        news_id = await db.add_published_news(_slug(news["title"]), news["title"],
                                              news["text"], image_url)
    except Exception as e:
        log.warning("channel: не удалось сохранить новость на сайт: %s", e)

    # photo может быть URL (dall-e-3) или data-URI с base64 (gpt-image-1).
    # Для байтов оборачиваем в BytesIO с именем — PTB надёжно принимает такой объект.
    def _photo_arg():
        if image_url.startswith("data:"):
            import base64
            import io
            buf = io.BytesIO(base64.b64decode(image_url.split(",", 1)[1]))
            buf.name = "news.png"
            return buf
        return image_url

    # 2) в Telegram-канал
    if not config.CHANNEL_ID:
        log.warning("channel: CHANNEL_ID не задан — новость только на сайт")
        await _notify_admins(
            context,
            "⚠️ Новость сохранена на сайт, но в канал НЕ отправлена: у сервиса бота "
            "не задана переменная CHANNEL_ID. Добавь её (напр. @kalorii_nauka) в Render "
            "для сервиса zhiromer и сделай бота админом канала.")
    else:
        bot_link = await _bot_link(context)
        footer = f"\n\n👉 Бот: {bot_link}\n🌐 Сайт: {config.SITE_URL}"
        caption = f"*{news['title']}*\n\n{news['text']}{footer}"
        msg = None
        try:
            msg = await context.bot.send_photo(config.CHANNEL_ID, photo=_photo_arg(),
                                               caption=caption[:1024], parse_mode="Markdown")
        except Exception as e:
            # повтор без Markdown, если разметка подвела
            log.warning("channel: первый send_photo не прошёл (%s), пробую без Markdown", e)
            try:
                plain = f"{news['title']}\n\n{news['text']}{footer}"
                msg = await context.bot.send_photo(config.CHANNEL_ID, photo=_photo_arg(), caption=plain[:1024])
            except Exception as e2:
                log.exception("channel: ошибка публикации в канал: %s", e2)
                await _notify_admins(context, f"⚠️ Канал: не удалось опубликовать.\n{type(e2).__name__}: {e2}")
        # постоянное хранение картинки: file_id из Telegram (URL от OpenAI живёт ~1ч)
        if msg and news_id and getattr(msg, "photo", None):
            try:
                await db.set_news_image_file_id(news_id, msg.photo[-1].file_id)
            except Exception as e:
                log.warning("channel: не удалось сохранить file_id: %s", e)

    log_url = None if image_url.startswith("data:") else image_url
    await db.add_channel_post(prompt, news["title"], log_url)
    log.info("channel: опубликована новость «%s»", news["title"])


async def _notify_admins(context, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception:
            pass


def schedule(application) -> None:
    application.job_queue.run_repeating(_job, interval=CHECK_INTERVAL, first=120,
                                        name="news_autopost")
