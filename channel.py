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

# Шаблонные промты с SEO-ключами по умолчанию (если в админке не задано своё).
DEFAULT_PROMPTS = [
    "Сколько калорий в популярном блюде и как не переесть. Ключи: счётчик калорий, "
    "подсчёт калорий по фото, КБЖУ.",
    "Развенчай популярный миф о питании (по данным ВОЗ). Ключи: здоровое питание, "
    "калькулятор калорий, дневник питания.",
    "Практичный совет: как считать калории по фото без таблиц и весов. Ключи: "
    "счётчик калорий по фото, ИИ-нутрициолог, КБЖУ.",
    "Сравни калорийность двух популярных блюд и сделай вывод. Ключи: подсчёт калорий, "
    "КБЖУ, дневник питания.",
    "Совет дня по снижению веса, основанный на доказательной базе. Ключи: похудение, "
    "счётчик калорий, правильное питание.",
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

    # 1) на сайт (таблица news)
    try:
        await db.add_published_news(_slug(news["title"]), news["title"], news["text"], image_url)
    except Exception as e:
        log.warning("channel: не удалось сохранить новость на сайт: %s", e)

    # 2) в Telegram-канал (если задан и бот — админ)
    if config.CHANNEL_ID:
        caption = f"*{news['title']}*\n\n{news['text']}\n\n👉 " + await _bot_link(context)
        try:
            await context.bot.send_photo(config.CHANNEL_ID, photo=image_url,
                                         caption=caption[:1024], parse_mode="Markdown")
        except Exception as e:
            # повтор без Markdown, если разметка подвела
            try:
                plain = f"{news['title']}\n\n{news['text']}\n\n👉 " + await _bot_link(context)
                await context.bot.send_photo(config.CHANNEL_ID, photo=image_url, caption=plain[:1024])
            except Exception as e2:
                log.exception("channel: ошибка публикации в канал: %s", e2)
                await _notify_admins(context, f"⚠️ Канал: не удалось опубликовать.\n{type(e2).__name__}: {e2}")

    await db.add_channel_post(prompt, news["title"], image_url)
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
