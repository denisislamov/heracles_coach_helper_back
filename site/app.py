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
        "tagline": "ИИ-счётчик калорий и КБЖУ в Telegram",
        "seo_desc": "Жиромер — умный счётчик калорий и КБЖУ в Telegram. Подсчёт калорий "
                    "по фото за секунды, дневник питания, нормы по стандартам ВОЗ. "
                    "Считай калории бесплатно целый месяц.",
        "seo_keywords": "счётчик калорий, подсчёт калорий по фото, калькулятор калорий, "
                        "КБЖУ, дневник питания, калории онлайн, нутрициолог ИИ, "
                        "телеграм бот калории, похудение, правильное питание",
        "hero_sub": "Надоело искать продукты в таблицах и взвешивать каждый кусок? "
                    "Просто сфотографируй тарелку — Жиромер за пару секунд оценит "
                    "калорийность и КБЖУ, запишет в дневник питания и подскажет, что "
                    "скорректировать под твою цель.",
        "cta": "Открыть в Telegram",
        "nav_features": "Возможности",
        "nav_news": "Новости",
        "nav_home": "Главная",
        "nav_price": "Цены",
        "usp_title": "Почему Жиромер",
        "u1_t": "Просто как сделать фото",
        "u1_d": "Никаких таблиц и весов. Сфотографировал тарелку — калории и КБЖУ уже в дневнике.",
        "u2_t": "Нормы по стандартам ВОЗ",
        "u2_d": "Расчёт КБЖУ опирается на ВОЗ, DRI и спортивные ACSM/ISSN — не «средние цифры из интернета».",
        "u3_t": "Честная точность",
        "u3_d": "Учитываем скрытые калории — масло, соусы, сахар — и реальные порции, а не занижаем.",
        "u4_t": "Подстраивается под тебя",
        "u4_d": "Цель, активность и даже вид спорта: ИИ подбирает нормы белков, жиров и углеводов лично под тебя.",
        "features_title": "Возможности",
        "f1_t": "Распознаёт еду по фото, тексту или числу",
        "f1_d": "Учитывает порции и «скрытые» калории — масло, соусы, сахар. "
                "Можно прислать фото, описание, голосовое или штрих-код продукта.",
        "f2_t": "Ведёт цель под твою задачу",
        "f2_d": "Сбросить, удержать или набрать. Калорийность и активность — под тебя.",
        "f3_t": "Считает белки, жиры и углеводы",
        "f3_d": "По научным нормам (ВОЗ/DRI, а для спорта — ACSM/ISSN). Укажи свой вид "
                "спорта — ИИ подберёт нормы точнее.",
        "f4_t": "Дневной и недельный отчёты",
        "f4_d": "Виден прогресс по дням, мягкие напоминания не забыть приём пищи.",
        "f5_t": "Исправления и записи задним числом",
        "f5_d": "Ошибся — поправь в один тап. Забыл вчера — добавь за прошлый день.",
        "f6_t": "Голос, штрих-код и избранное",
        "f6_d": "Надиктуй приём пищи, отсканируй штрих-код или добавь любимое блюдо в один тап.",
        "price_title": "Цены",
        "price_sub": "Оплата звёздами Telegram — без карт и сторонних подписок.",
        "price_unit": "★/мес",
        "plan_free_t": "Бесплатно",
        "plan_free_p": "целый месяц",
        "plan_free_d": "Полный доступ на 30 дней: распознавание по фото, дневник, отчёты и цель.",
        "plan_prem_t": "Premium",
        "plan_prem_p": "200",
        "plan_prem_d": "Безлимитные анализы еды по фото и тексту. Без дневных ограничений.",
        "plan_premplus_t": "Premium + КБЖУ",
        "plan_premplus_p": "300",
        "plan_premplus_d": "Всё из Premium плюс расчёт белков/жиров/углеводов и нормы под твой спорт.",
        "plan_badge": "Популярный",
        "news_title": "Новости",
        "news_empty": "Пока новостей нет. Загляни позже!",
        "news_all": "Все новости →",
        "back": "← Ко всем новостям",
        "footer": "Жиромер — считай калории с умом. Подсчёт калорий и КБЖУ по фото в Telegram.",
        "read": "Читать →",
    },
    "en": {
        "tagline": "AI calorie & macro counter in Telegram",
        "seo_desc": "Zhiromer — a smart calorie and macro counter in Telegram. Count "
                    "calories from a photo in seconds, keep a food diary, targets based "
                    "on WHO standards. Track calories free for a whole month.",
        "seo_keywords": "calorie counter, count calories from photo, calorie calculator, "
                        "macros, food diary, calories online, AI nutritionist, "
                        "telegram calorie bot, weight loss, healthy eating",
        "hero_sub": "Tired of looking up foods in tables and weighing every bite? "
                    "Just snap your plate — Zhiromer estimates calories and macros in "
                    "seconds, logs them in your food diary, and tells you what to adjust "
                    "for your goal.",
        "cta": "Open in Telegram",
        "nav_features": "Features",
        "nav_news": "News",
        "nav_home": "Home",
        "nav_price": "Pricing",
        "usp_title": "Why Zhiromer",
        "u1_t": "As simple as taking a photo",
        "u1_d": "No tables, no scales. Snap your plate — calories and macros land in your diary.",
        "u2_t": "Targets based on WHO standards",
        "u2_d": "Macros are based on WHO, DRI and sports ACSM/ISSN references — not random internet averages.",
        "u3_t": "Honest accuracy",
        "u3_d": "We count hidden calories — oil, sauces, sugar — and real portions instead of underestimating.",
        "u4_t": "Tailored to you",
        "u4_d": "Goal, activity and even your sport: the AI tunes protein, fat and carb targets just for you.",
        "features_title": "Features",
        "f1_t": "Recognizes food by photo, text or number",
        "f1_d": "Accounts for portions and hidden calories — oil, sauces, sugar. "
                "Send a photo, a description, a voice note, or a product barcode.",
        "f2_t": "Tracks a goal that fits you",
        "f2_d": "Lose, maintain or gain. Calories and activity tailored to you.",
        "f3_t": "Counts protein, fat and carbs",
        "f3_d": "Using science-based references (WHO/DRI, and ACSM/ISSN for sport). "
                "Add your sport — the AI tunes your targets.",
        "f4_t": "Daily and weekly reports",
        "f4_d": "See your progress day by day, with gentle reminders to log meals.",
        "f5_t": "Edits and back-dated entries",
        "f5_d": "Made a mistake? Fix it in one tap. Forgot yesterday? Add it for a past day.",
        "f6_t": "Voice, barcode and favorites",
        "f6_d": "Dictate a meal, scan a barcode, or add a favorite dish in one tap.",
        "price_title": "Pricing",
        "price_sub": "Pay with Telegram Stars — no cards, no third-party subscriptions.",
        "price_unit": "★/mo",
        "plan_free_t": "Free",
        "plan_free_p": "for a whole month",
        "plan_free_d": "Full access for 30 days: photo recognition, diary, reports and goal.",
        "plan_prem_t": "Premium",
        "plan_prem_p": "200",
        "plan_prem_d": "Unlimited food analyses by photo and text. No daily limits.",
        "plan_premplus_t": "Premium + Macros",
        "plan_premplus_p": "300",
        "plan_premplus_d": "Everything in Premium plus protein/fat/carb targets tuned to your sport.",
        "plan_badge": "Popular",
        "news_title": "News",
        "news_empty": "No news yet. Check back soon!",
        "news_all": "All news →",
        "back": "← Back to all news",
        "footer": "Zhiromer — count calories smartly. Calorie & macro tracking from a photo in Telegram.",
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


def get_prices():
    """Цены тарифов из БД (управляются в админке), с откатом на дефолты."""
    rows = query("SELECT key, value FROM settings WHERE key IN ('premium_price','macros_price')") or []
    m = {r["key"]: r["value"] for r in rows}

    def num(v, default):
        return v if (v and str(v).strip().isdigit()) else default

    return {"premium": num(m.get("premium_price"), "200"),
            "macros": num(m.get("macros_price"), "300")}


def _bot_cta() -> str:
    """Ссылка в бота с меткой источника для атрибуции (откуда пришёл юзер)."""
    sep = "&" if "?" in BOT_URL else "?"
    return f"{BOT_URL}{sep}start=site"


@app.context_processor
def inject_globals():
    lang = get_lang()
    return {"lang": lang, "tr": T[lang], "bot_url": _bot_cta(), "prices": get_prices(),
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
                      "image": r.get("image_url"),
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
                           body=render_body(body), image=r.get("image_url"),
                           date=r["published_at"] or r["created_at"])


@app.route("/set-lang/<lang>")
def set_lang(lang):
    if lang not in LANGS:
        lang = "ru"
    nxt = request.args.get("next") or request.referrer or url_for("index")
    if not nxt.startswith("/"):   # только внутренние пути
        nxt = url_for("index")
    resp = make_response(redirect(nxt))
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@app.route("/health")
def health():
    return "ok"


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8001")), debug=True)
