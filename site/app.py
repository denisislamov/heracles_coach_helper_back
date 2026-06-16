"""Публичный лендинг бота «Жиромер» + раздел новостей.

Отдельный публичный веб-сервис (без авторизации). Использует ту же базу
PostgreSQL, что бот и админка: читает опубликованные новости из таблицы news.
Двуязычный (RU/EN) — язык берётся из ?lang= и запоминается в cookie.

Запуск (Render): gunicorn app:app
Локально: python app.py
"""
import os
import datetime as dt
from html import escape
from markupsafe import Markup

import psycopg2
import psycopg2.extras
from flask import (Flask, render_template, request, redirect, url_for,
                   make_response, abort)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

BOT_URL = os.environ.get("BOT_URL", "https://t.me/zhiromer_bot")
SITE_NAME = "Жиромер"

app = Flask(__name__)

LANGS = ("ru", "en")

# Тексты интерфейса сайта (контент новостей хранится в БД на двух языках).
T = {
    "ru": {
        "tagline": "твой ИИ-нутрициолог в Telegram",
        "hero_sub": "Надоело искать продукты в таблицах и взвешивать каждый кусок? "
                    "Просто сфотографируй тарелку — Жиромер за пару секунд оценит "
                    "калорийность и БЖУ, запишет в дневник и подскажет, что скорректировать.",
        "cta": "Открыть в Telegram",
        "nav_features": "Возможности",
        "nav_news": "Новости",
        "nav_home": "Главная",
        "features_title": "Что умеет",
        "f1_t": "Распознаёт еду по фото, тексту или числу",
        "f1_d": "Учитывает порции и «скрытые» калории — масло, соусы, сахар. "
                "Можно прислать фото, описание, голосовое или штрих-код продукта.",
        "f2_t": "Ведёт цель под твою задачу",
        "f2_d": "Сбросить, удержать или набрать. Калорийность и активность — под тебя.",
        "f3_t": "Считает белки, жиры и углеводы",
        "f3_d": "По научным нормам (ВОЗ/DRI, а для спорта — ACSM/ISSN). Укажи свой вид "
                "спорта — ИИ подберёт нормы точнее. Тариф Premium+КБЖУ.",
        "f4_t": "Дневной и недельный отчёты",
        "f4_d": "Видно прогресс по дням, мягкие напоминания не забыть приём пищи.",
        "f5_t": "Исправление и записи задним числом",
        "f5_d": "Ошибся — поправь в один тап. Забыл вчера — добавь за прошлый день.",
        "free_t": "Первые анализы — бесплатно",
        "free_d": "Подключай Premium, когда захочешь без лимитов.",
        "news_title": "Новости",
        "news_empty": "Пока новостей нет. Загляни позже!",
        "news_all": "Все новости →",
        "back": "← Ко всем новостям",
        "footer": "Считай калории с умом. Сделано с ❤ для тех, кто следит за питанием.",
        "read": "Читать →",
    },
    "en": {
        "tagline": "your AI nutritionist in Telegram",
        "hero_sub": "Tired of looking up foods in tables and weighing every bite? "
                    "Just snap your plate — Zhiromer estimates calories and macros in "
                    "seconds, logs them, and tells you what to adjust.",
        "cta": "Open in Telegram",
        "nav_features": "Features",
        "nav_news": "News",
        "nav_home": "Home",
        "features_title": "What it does",
        "f1_t": "Recognizes food by photo, text or number",
        "f1_d": "Accounts for portions and hidden calories — oil, sauces, sugar. "
                "Send a photo, a description, a voice note, or a product barcode.",
        "f2_t": "Tracks a goal that fits you",
        "f2_d": "Lose, maintain or gain. Calories and activity tailored to you.",
        "f3_t": "Counts protein, fat and carbs",
        "f3_d": "Using science-based references (WHO/DRI, and ACSM/ISSN for sport). "
                "Add your sport — the AI tunes your targets. Premium+Macros plan.",
        "f4_t": "Daily and weekly reports",
        "f4_d": "See your progress day by day, with gentle reminders to log meals.",
        "f5_t": "Edits and back-dated entries",
        "f5_d": "Made a mistake? Fix it in one tap. Forgot yesterday? Add it for a past day.",
        "free_t": "First analyses are free",
        "free_d": "Go Premium whenever you want unlimited.",
        "news_title": "News",
        "news_empty": "No news yet. Check back soon!",
        "news_all": "All news →",
        "back": "← Back to all news",
        "footer": "Eat with intent. Made with ❤ for people who track their nutrition.",
        "read": "Read →",
    },
}


def get_lang():
    lang = request.args.get("lang") or request.cookies.get("lang") or "ru"
    return lang if lang in LANGS else "ru"


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def query(sql, params=None, one=False):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.description is None:
                return None
            rows = cur.fetchall()
            return (rows[0] if rows else None) if one else rows
    except Exception:
        return None if one else []


def news_fields(row, lang):
    """Заголовок/текст новости на нужном языке с откатом на русский."""
    title = row.get(f"title_{lang}") or row["title_ru"]
    body = row.get(f"body_{lang}") or row["body_ru"]
    return title, body


def render_body(text):
    """Простой рендер: абзацы по пустой строке, экранирование HTML."""
    parts = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    html = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in parts)
    return Markup(html)


@app.context_processor
def inject_globals():
    lang = get_lang()
    return {"lang": lang, "tr": T[lang], "bot_url": BOT_URL,
            "site_name": SITE_NAME, "langs": LANGS, "now_year": dt.date.today().year}


@app.route("/")
def index():
    lang = get_lang()
    rows = query("SELECT * FROM news WHERE published ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 3") or []
    items = []
    for r in rows:
        title, body = news_fields(r, lang)
        items.append({"slug": r["slug"], "title": title,
                      "date": r["published_at"] or r["created_at"]})
    return render_template("index.html", news=items)


@app.route("/news")
def news_list():
    lang = get_lang()
    rows = query("SELECT * FROM news WHERE published ORDER BY published_at DESC NULLS LAST, id DESC") or []
    items = []
    for r in rows:
        title, body = news_fields(r, lang)
        excerpt = (body or "").strip().split("\n\n")[0][:180]
        items.append({"slug": r["slug"], "title": title, "excerpt": excerpt,
                      "date": r["published_at"] or r["created_at"]})
    return render_template("news_list.html", news=items)


@app.route("/news/<slug>")
def news_detail(slug):
    lang = get_lang()
    r = query("SELECT * FROM news WHERE slug=%s AND published", (slug,), one=True)
    if not r:
        abort(404)
    title, body = news_fields(r, lang)
    return render_template("news_detail.html", title=title,
                           body=render_body(body),
                           date=r["published_at"] or r["created_at"])


@app.route("/set-lang/<lang>")
def set_lang(lang):
    if lang not in LANGS:
        lang = "ru"
    resp = make_response(redirect(request.referrer or url_for("index")))
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return resp


@app.route("/health")
def health():
    return "ok"


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8001")), debug=True)
