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
import research

log = logging.getLogger("calbot.channel")

# Рубрика «Миф ❌ / Правда ✅» про КБЖУ (калории, белки/жиры/углеводы). SEO-ключи вшиты.
# Формат поста: заголовок «Миф vs правда: …», в тексте «❌ Миф: …» и «✅ Правда: …».
_FMT = ("Рубрика «Миф vs правда» про КБЖУ. В заголовке начни со слов «Миф vs правда:». "
        "В тексте чётко раздели: строка «❌ Миф: …» и строка «✅ Правда: …» (по ВОЗ/доказательной "
        "базе). Обязательно про калории и/или белки-жиры-углеводы. Тема и ключи: ")
DEFAULT_PROMPTS = [
    # — Калории и КБЖУ —
    _FMT + "«жиры — это вредно, их надо убрать». Ключи: жиры, КБЖУ, калории, здоровое питание.",
    _FMT + "«считать калории бесполезно». Ключи: подсчёт калорий, счётчик калорий, КБЖУ, дневник питания.",
    _FMT + "«углеводы вечером превращаются в жир». Ключи: углеводы, КБЖУ, калории.",
    _FMT + "«обезжиренные продукты помогают похудеть». Ключи: жиры, калории, КБЖУ, похудение.",
    _FMT + "«фрукты можно есть без ограничений». Ключи: углеводы, сахар, калории, КБЖУ.",
    _FMT + "«главное — не калории, а время приёма пищи». Ключи: калории, КБЖУ, дефицит калорий.",
    _FMT + "«после 18:00 есть нельзя». Ключи: калории, КБЖУ, дефицит калорий, похудение.",
    _FMT + "«сахар нужно полностью исключить». Ключи: сахар, углеводы, калории, КБЖУ.",
    _FMT + "«орехи и авокадо — ПП, можно без счёта». Ключи: жиры, калории, КБЖУ.",
    _FMT + "«салат всегда низкокалориен». Ключи: калории, жиры, заправка, КБЖУ.",
    _FMT + "«есть жиросжигающие продукты». Ключи: калории, КБЖУ, похудение, дефицит калорий.",
    _FMT + "«калории из «чистой» еды можно не считать». Ключи: калории, КБЖУ, подсчёт калорий.",
    _FMT + "«кето/безуглеводка — единственный путь похудеть». Ключи: углеводы, КБЖУ, калории, похудение.",
    _FMT + "«детокс и вода с лимоном сжигают жир». Ключи: калории, КБЖУ, похудение.",
    _FMT + "«дефицит калорий замедляет метаболизм навсегда». Ключи: калории, дефицит калорий, КБЖУ.",
    _FMT + "«цельнозерновой хлеб не калорийный, можно сколько угодно». Ключи: углеводы, калории, КБЖУ.",
    _FMT + "«мёд и тростниковый сахар полезнее обычного для фигуры». Ключи: сахар, калории, КБЖУ.",
    _FMT + "«смузи и фреши — диетический напиток». Ключи: сахар, калории, КБЖУ, похудение.",
    _FMT + "«растительное масло можно лить без ограничений — оно полезное». Ключи: жиры, калории, КБЖУ.",
    _FMT + "«алкоголь не влияет на калорийность рациона». Ключи: калории, КБЖУ, похудение.",
    _FMT + "«газировка zero мешает похудению так же, как обычная». Ключи: калории, сахар, КБЖУ.",
    _FMT + "«домашняя еда всегда низкокалорийна». Ключи: калории, жиры, КБЖУ, подсчёт калорий.",
    _FMT + "«пропуск приёмов пищи разгоняет похудение». Ключи: калории, КБЖУ, дефицит калорий.",
    # — Спортивное питание —
    _FMT + "«чем больше белка, тем больше мышц — автоматически». Ключи: белок, норма белка, спортивное питание, КБЖУ.",
    _FMT + "«без протеина и гейнера мышцы не растут». Ключи: белок, спортивное питание, спортпит, КБЖУ.",
    _FMT + "«если тренируешься, можно есть что угодно». Ключи: калории, дефицит калорий, спортивное питание, КБЖУ.",
    _FMT + "«белковые батончики — здоровый перекус без счёта». Ключи: белок, сахар, калории, спортивное питание, КБЖУ.",
    _FMT + "«тренировка натощак сжигает больше жира». Ключи: калории, дефицит калорий, спортивное питание, КБЖУ.",
    _FMT + "«углеводы мешают сушке, их надо убрать спортсмену». Ключи: углеводы, спортивное питание, КБЖУ, калории.",
]

CHECK_INTERVAL = 1800   # как часто проверять, не пора ли публиковать (сек)
ACTIVE_HOURS = 14       # окно, на которое равномерно «размазываем» публикации


def _truthy(v):
    return v is not None and str(v).strip().lower() in ("1", "true", "yes", "on")


async def _prompts() -> list:
    raw = await db.get_setting("channel_topics")
    items = [s.strip() for s in (raw or "").splitlines() if s.strip()]
    return items or DEFAULT_PROMPTS


async def _pick_prompt() -> str:
    """Выбрать промт, не повторяя недавние: проходим весь список по кругу,
    прежде чем тема повторится. Так две подряд (и вообще близкие) новости не дублируются."""
    prompts = await _prompts()
    if len(prompts) <= 1:
        return prompts[0] if prompts else ""
    # сколько последних тем избегаем: почти весь список, но всегда оставляем выбор
    avoid_n = max(1, len(prompts) - 1)
    recent = set(await db.recent_channel_topics(avoid_n))
    fresh = [p for p in prompts if p not in recent]
    if not fresh:                       # все недавно использованы — берём всё, кроме самой последней
        last = next(iter(await db.recent_channel_topics(1)), None)
        fresh = [p for p in prompts if p != last] or prompts
    return random.choice(fresh)


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

    # Анти-повтор: учитываем недавние темы и недавно использованные статьи.
    recent = await db.recent_channel_topics(40)

    # Микс двух типов постов: по нашим промтам (миф/правда про КБЖУ и спортпит)
    # и по свежим научным исследованиям. Доля исследований — настройка (по умолчанию 40%).
    try:
        research_ratio = int(await db.get_setting("channel_research_ratio") or 40)
    except (TypeError, ValueError):
        research_ratio = 40
    research_ratio = max(0, min(100, research_ratio))

    article = None
    if random.randint(1, 100) <= research_ratio:
        try:
            article = await research.fresh_article(recent)
        except Exception as e:
            log.warning("channel: ошибка получения свежей статьи: %s", e)

    if article:                          # пост на основе реальной свежей статьи
        topic_log = article["link"]
        task = (_FMT + "сформулируй один распространённый миф по теме материала ниже и "
                "опровергни его, опираясь на его выводы. Без выдуманных цифр.")
        news = await ai.generate_news(task, source=article)
    else:                                # пост по нашему промту (миф/правда)
        topic_log = await _pick_prompt()
        news = await ai.generate_news(topic_log)

    if not news:
        log.warning("channel: не удалось сгенерировать новость")
        return

    # Ссылка на источник — в тексте (и на сайте, и в канале) для достоверности.
    if article:
        news["text"] = f"{news['text']}\n\n📚 Источник: {article['source']} — {article['link']}"
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
    await db.add_channel_post(topic_log, news["title"], log_url)
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
