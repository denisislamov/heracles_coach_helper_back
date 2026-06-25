"""Свежие материалы из научных RSS-лент про питание/нутрициологию.

Используется автопостером канала: берём реальную недавнюю статью из доверенного
источника и на её основе пишем пост (рубрика «Миф vs правда»), со ссылкой на источник.
Так контент остаётся актуальным и достоверным (не выдуманным).
"""
import asyncio
import datetime as dt
import html
import logging
import random
import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

log = logging.getLogger("calbot.research")

# Доверенные ленты (RSS 2.0). Темы — питание, КБЖУ, диеты, метаболизм.
FEEDS = [
    ("Harvard T.H. Chan — The Nutrition Source", "https://nutritionsource.hsph.harvard.edu/feed/"),
    ("ScienceDaily — Nutrition", "https://www.sciencedaily.com/rss/health_medicine/nutrition.xml"),
    ("ScienceDaily — Diet and Weight Loss", "https://www.sciencedaily.com/rss/health_medicine/diet_and_weight_loss.xml"),
]

MAX_AGE_DAYS = 120        # насколько свежей должна быть статья
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str, limit: int = 700) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_date(s: str):
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return None


def _parse_feed(source: str, xml_bytes: bytes) -> list:
    """Извлечь записи из RSS 2.0 (title/link/description/pubDate)."""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        log.warning("research: не удалось распарсить %s: %s", source, e)
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""
        pub = _parse_date(item.findtext("pubDate") or "")
        if not title or not link:
            continue
        out.append({"source": source, "title": _clean(title, 200),
                    "summary": _clean(desc, 700), "link": link, "date": pub})
    return out


async def _fetch(client, source: str, url: str) -> list:
    try:
        r = await client.get(url, timeout=20, follow_redirects=True,
                             headers={"User-Agent": "ZhiromerBot/1.0 (+https://t.me/zhiromer_bot)"})
        r.raise_for_status()
        return _parse_feed(source, r.content)
    except Exception as e:
        log.warning("research: не удалось загрузить ленту %s: %s", source, e)
        return []


async def fresh_article(avoid_links=None):
    """Вернуть свежую статью {source,title,summary,link,date}, ещё не использованную.
    None — если ленты недоступны или нет подходящих свежих материалов."""
    avoid = set(avoid_links or [])
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_fetch(client, s, u) for s, u in FEEDS])
    entries = [e for batch in results for e in batch]
    if not entries:
        return None

    now = dt.datetime.now(dt.timezone.utc)

    def recent(e):
        d = e["date"]
        if not d:
            return True   # без даты — считаем условно свежим
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return (now - d).days <= MAX_AGE_DAYS

    fresh = [e for e in entries if e["link"] not in avoid and recent(e)]
    if not fresh:                       # все недавно использованы/старые — берём любую новую
        fresh = [e for e in entries if e["link"] not in avoid] or entries
    return random.choice(fresh)
