"""Веб-админка бота «Жиромер».

Три страницы: Аналитика, Баг-репорты, Неверные калории.
Вход по логину/паролю (переменные окружения). Использует ту же базу PostgreSQL,
что и бот, и токен бота — для показа присланных фото/видео.

Запуск (Render): gunicorn app:app
Локально: python app.py
"""
import functools
import os

import psycopg2
import psycopg2.extras
import requests
from flask import (Flask, Response, redirect, render_template, request,
                   session, url_for, flash)

# ----------------------------------------------------------------- конфигурация
DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

# Базовые логин/пароль. Поменяй в Render → Environment (можно на свою почту).
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Zhiromer-Admin-2026")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
STAR_USD = float(os.environ.get("STAR_USD", "0.013"))  # курс звезды для оценки выручки
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL_ADMIN = os.environ.get("OPENAI_MODEL_ADMIN", "gpt-4o-mini")
OPENAI_MODEL_NEWS = os.environ.get("OPENAI_MODEL_NEWS", "gpt-4o")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "dall-e-3")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")

APP_VERSION = "1.18.0"  # версия админки (синхронизируй с version.py бота)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-please")


@app.context_processor
def inject_version():
    return {"app_version": APP_VERSION}


# ----------------------------------------------------------------- БД-хелперы
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def query(sql, params=None, one=False):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            return None
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows


def execute(sql, params=None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())


# ----------------------------------------------------------------- авторизация
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("auth"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_ = request.form.get("login", "").strip()
        pwd = request.form.get("password", "")
        if login_ == ADMIN_LOGIN and pwd == ADMIN_PASSWORD:
            session["auth"] = True
            return redirect(request.args.get("next") or url_for("analytics"))
        flash("Неверный логин или пароль")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("analytics"))


# ----------------------------------------------------------------- Аналитика
def collect_stats() -> dict:
    def scalar(sql, params=None):
        row = query(sql, params, one=True)
        return list(row.values())[0] if row else 0

    stats = {
        "total_users": scalar("SELECT count(*) FROM users"),
        "new_today": scalar("SELECT count(*) FROM users WHERE created_at::date = current_date"),
        "new_7d": scalar("SELECT count(*) FROM users WHERE created_at >= now() - interval '7 days'"),
        "new_30d": scalar("SELECT count(*) FROM users WHERE created_at >= now() - interval '30 days'"),
        "dau": scalar("SELECT count(DISTINCT user_id) FROM entries WHERE created_at::date = current_date"),
        "wau": scalar("SELECT count(DISTINCT user_id) FROM entries WHERE created_at >= now() - interval '7 days'"),
        "mau": scalar("SELECT count(DISTINCT user_id) FROM entries WHERE created_at >= now() - interval '30 days'"),
        "entries_today": scalar("SELECT count(*) FROM entries WHERE created_at::date = current_date"),
        "entries_7d": scalar("SELECT count(*) FROM entries WHERE created_at >= now() - interval '7 days'"),
        "premium_active": scalar("SELECT count(*) FROM users WHERE premium_until > now()"),
        "premium_basic_active": scalar("SELECT count(*) FROM users WHERE premium_until > now() AND plan='premium'"),
        "premium_plus_active": scalar("SELECT count(*) FROM users WHERE premium_until > now() AND plan='premium_plus'"),
        "paying_users": scalar("SELECT count(DISTINCT user_id) FROM payments"),
        "stars_total": scalar("SELECT COALESCE(SUM(amount_stars),0) FROM payments"),
        "stars_30d": scalar("SELECT COALESCE(SUM(amount_stars),0) FROM payments WHERE created_at >= now() - interval '30 days'"),
        "open_bugs": scalar("SELECT count(*) FROM bug_reports WHERE status = 'new'"),
        "open_cal": scalar("SELECT count(*) FROM calorie_feedback WHERE status = 'new'"),
    }
    total = stats["total_users"] or 1
    stats["conversion"] = round(stats["paying_users"] / total * 100, 1)
    stats["stickiness"] = round((stats["dau"] / stats["mau"] * 100), 1) if stats["mau"] else 0
    stats["usd_total"] = round(stats["stars_total"] * STAR_USD, 2)
    stats["usd_30d"] = round(stats["stars_30d"] * STAR_USD, 2)
    return stats


# Человекочитаемые подписи источников трафика (ключ = значение ?start=<source>).
SOURCE_LABELS = {
    "site": "🌐 Сайт",
    "channel": "📣 Telegram-канал",
    "referral": "👥 Реферальная программа",
    "dzen": "📰 Яндекс Дзен",
}


@app.route("/analytics")
@login_required
def analytics():
    stats = collect_stats()

    # графики за 14 дней
    import datetime as dt
    days = [(dt.date.today() - dt.timedelta(days=i)) for i in range(13, -1, -1)]
    labels = [d.strftime("%d.%m") for d in days]

    def series(sql):
        rows = query(sql) or []
        m = {r["d"]: int(r["c"]) for r in rows}
        return [m.get(d, 0) for d in days]

    new_users_series = series(
        "SELECT created_at::date d, count(*) c FROM users "
        "WHERE created_at >= now() - interval '14 days' GROUP BY d")
    entries_series = series(
        "SELECT created_at::date d, count(*) c FROM entries "
        "WHERE created_at >= now() - interval '14 days' GROUP BY d")

    # источники привлечения: сколько пришло и сколько из них платят
    sources = query(
        """SELECT COALESCE(source, '(прямой / не размечен)') AS src,
                  count(*) AS total,
                  count(*) FILTER (
                      WHERE EXISTS (SELECT 1 FROM payments p
                                    WHERE p.user_id = users.user_id AND NOT p.is_refunded)
                  ) AS paying
           FROM users GROUP BY src ORDER BY total DESC""") or []

    return render_template("analytics.html", s=stats, labels=labels,
                           new_users_series=new_users_series, entries_series=entries_series,
                           sources=sources, source_labels=SOURCE_LABELS)


# ----------------------------------------------------------------- Пользователи
def _plan_label(u) -> str:
    import datetime as dt
    active = u["premium_until"] and u["premium_until"] > dt.datetime.now(dt.timezone.utc)
    base = {"free": "Free", "premium": "Premium", "premium_plus": "Premium+КБЖУ"}.get(u["plan"], u["plan"])
    if u["plan"] != "free" and not active:
        return base + " (истёк)"
    return base


# Окно «активности»: сколько дней без записей считаем пользователя пассивным.
ACTIVE_WINDOW_DAYS = 7

# Условия сегментов (вкладок). Активный — есть записи за последние N дней;
# пассивный — зарегистрировался давно, но за последние N дней записей нет.
_ACTIVE_COND = (f"EXISTS (SELECT 1 FROM entries e WHERE e.user_id = u.user_id "
                f"AND e.created_at >= now() - interval '{ACTIVE_WINDOW_DAYS} days')")
_PASSIVE_COND = (f"u.created_at < now() - interval '{ACTIVE_WINDOW_DAYS} days' "
                 f"AND NOT {_ACTIVE_COND}")

SEGMENT_WHERE = {
    "active": _ACTIVE_COND,
    "passive": _PASSIVE_COND,
    "paying": "EXISTS (SELECT 1 FROM payments p WHERE p.user_id = u.user_id AND NOT p.is_refunded)",
    "alpha": "u.is_alpha = TRUE",
    "premium": "u.plan = 'premium' AND u.premium_until > now()",
    "premium_plus": "u.plan = 'premium_plus' AND u.premium_until > now()",
    "referred": "u.referred_by IS NOT NULL",
    "byok": "u.openai_key_enc IS NOT NULL",
    "blocked": "u.blocked",
}

# Разрешённые варианты сортировки (защита от SQL-инъекций — только из белого списка).
SORT_OPTIONS = {
    "created_desc": ("u.created_at DESC", "Новые сначала"),
    "created_asc": ("u.created_at ASC", "Старые сначала"),
    "active_desc": ("last_active DESC NULLS LAST", "Активность (свежая)"),
    "active_asc": ("last_active ASC NULLS FIRST", "Активность (давняя)"),
    "entries_desc": ("entries_count DESC", "Больше записей"),
    "premium_desc": ("u.premium_until DESC NULLS LAST", "Подписка дольше"),
    "refs_desc": ("ref_count DESC", "Больше рефералов"),
}


@app.route("/users")
@login_required
def users():
    q = (request.args.get("q") or "").strip()
    flt = request.args.get("filter", "")
    sort = request.args.get("sort", "created_desc")
    if sort not in SORT_OPTIONS:
        sort = "created_desc"
    order_sql = SORT_OPTIONS[sort][0]

    where, params = [], []
    if q:
        if q.lstrip("-").isdigit():
            where.append("(u.user_id = %s OR u.username ILIKE %s)")
            params += [int(q), f"%{q}%"]
        else:
            where.append("u.username ILIKE %s")
            params.append(f"%{q.lstrip('@')}%")
    if flt in SEGMENT_WHERE:
        where.append(SEGMENT_WHERE[flt])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    PER_PAGE = 100
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    matched = query(f"SELECT count(*) c FROM users u {where_sql}", params, one=True)["c"]
    pages = max(1, (matched + PER_PAGE - 1) // PER_PAGE)
    page = min(page, pages)
    offset = (page - 1) * PER_PAGE
    rows = query(
        f"""SELECT u.*,
                   (SELECT count(*) FROM referrals r WHERE r.referrer_id = u.user_id) AS ref_count,
                   (SELECT count(*) FROM entries e WHERE e.user_id = u.user_id) AS entries_count,
                   (SELECT max(e.created_at) FROM entries e WHERE e.user_id = u.user_id) AS last_active
            FROM users u {where_sql}
            ORDER BY {order_sql} LIMIT {PER_PAGE} OFFSET %s""",
        params + [offset]) or []

    def seg_count(cond):
        return query(f"SELECT count(*) c FROM users u WHERE {cond}", one=True)["c"]

    summary = {
        "total": query("SELECT count(*) c FROM users", one=True)["c"],
        "active": seg_count(_ACTIVE_COND),
        "paying": seg_count(SEGMENT_WHERE["paying"]),
        "passive": seg_count(_PASSIVE_COND),
    }
    return render_template("users.html", rows=rows, q=q, flt=flt, sort=sort,
                           sort_options=SORT_OPTIONS, summary=summary,
                           plan_label=_plan_label, page=page, pages=pages,
                           matched=matched, per_page=PER_PAGE,
                           active_days=ACTIVE_WINDOW_DAYS)


@app.route("/users/<int:uid>", methods=["GET", "POST"])
@login_required
def user_detail(uid):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "grant":
            plan = request.form.get("plan", "premium")
            try:
                days = max(1, int(request.form.get("days", "30")))
            except ValueError:
                flash("Дни должны быть числом")
                return redirect(url_for("user_detail", uid=uid))
            if plan not in ("premium", "premium_plus"):
                plan = "premium"
            execute(
                """UPDATE users
                   SET premium_until = GREATEST(COALESCE(premium_until, now()), now())
                                       + make_interval(days => %s),
                       plan = %s
                   WHERE user_id = %s""", (days, plan, uid))
            flash(f"Выдано {days} дн. {plan} пользователю {uid}")
        elif action == "revoke":
            execute("UPDATE users SET premium_until = now(), plan='free' WHERE user_id=%s", (uid,))
            flash(f"Premium отозван у {uid}")
        elif action == "reset_limit":
            execute("UPDATE users SET ai_count_today = 0 WHERE user_id=%s", (uid,))
            flash(f"Дневной лимит сброшен у {uid}")
        elif action == "toggle_alpha":
            execute("UPDATE users SET is_alpha = NOT is_alpha WHERE user_id=%s", (uid,))
            flash("Метка альфа-тестера переключена")
        return redirect(url_for("user_detail", uid=uid))

    u = query("SELECT * FROM users WHERE user_id=%s", (uid,), one=True)
    if not u:
        return "Пользователь не найден", 404
    payments_rows = query(
        "SELECT * FROM payments WHERE user_id=%s ORDER BY created_at DESC", (uid,)) or []
    redemptions = query(
        "SELECT * FROM redemptions WHERE user_id=%s ORDER BY redeemed_at DESC", (uid,)) or []
    refs = query(
        """SELECT r.referred_id, r.created_at, ru.username
           FROM referrals r LEFT JOIN users ru ON ru.user_id = r.referred_id
           WHERE r.referrer_id=%s ORDER BY r.created_at DESC""", (uid,)) or []
    referred_by = None
    if u["referred_by"]:
        referred_by = query("SELECT user_id, username FROM users WHERE user_id=%s",
                            (u["referred_by"],), one=True)
    recent = query(
        "SELECT * FROM entries WHERE user_id=%s ORDER BY created_at DESC LIMIT 15", (uid,)) or []
    totals = query(
        """SELECT count(*) cnt, COALESCE(SUM(amount_stars),0) stars
           FROM payments WHERE user_id=%s AND NOT is_refunded""", (uid,), one=True)
    return render_template("user_detail.html", u=u, payments=payments_rows,
                           redemptions=redemptions, refs=refs, referred_by=referred_by,
                           recent=recent, totals=totals, plan_label=_plan_label,
                           star_usd=STAR_USD)


# ----------------------------------------------------------------- Опросы
@app.route("/surveys")
@login_required
def surveys():
    rows = query("SELECT * FROM surveys ORDER BY created_at DESC LIMIT 500") or []
    return render_template("surveys.html", rows=rows)


# ----------------------------------------------------------------- Баг-репорты
@app.route("/bugs", methods=["GET", "POST"])
@login_required
def bugs():
    if request.method == "POST":
        execute("UPDATE bug_reports SET status=%s WHERE id=%s",
                (request.form["status"], request.form["id"]))
        return redirect(url_for("bugs"))
    rows = query("SELECT * FROM bug_reports ORDER BY created_at DESC LIMIT 500")
    return render_template("bugs.html", rows=rows)


# ----------------------------------------------------------------- Неверные калории
@app.route("/calorie-feedback", methods=["GET", "POST"])
@login_required
def calorie_feedback():
    if request.method == "POST":
        action = request.form.get("action")
        fb_id = request.form["id"]
        if action == "approve":
            # сохранить как правку для будущего распознавания
            fb = query("SELECT * FROM calorie_feedback WHERE id=%s", (fb_id,), one=True)
            if fb and fb["correct_kcal"]:
                execute("INSERT INTO food_corrections (dish, kcal, source_fb) VALUES (%s,%s,%s)",
                        (fb["dish"], fb["correct_kcal"], fb["id"]))
            execute("UPDATE calorie_feedback SET status='done' WHERE id=%s", (fb_id,))
        else:
            execute("UPDATE calorie_feedback SET status=%s WHERE id=%s",
                    (request.form["status"], fb_id))
        return redirect(url_for("calorie_feedback"))
    rows = query("SELECT * FROM calorie_feedback ORDER BY created_at DESC LIMIT 500")
    corrections = query("SELECT * FROM food_corrections ORDER BY created_at DESC LIMIT 200")
    return render_template("calorie_feedback.html", rows=rows, corrections=corrections)


# ----------------------------------------------------------------- Промокоды
@app.route("/promos", methods=["GET", "POST"])
@login_required
def promos():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "toggle":
            execute("UPDATE promo_codes SET active = NOT active WHERE code=%s",
                    (request.form["code"],))
        elif action == "create":
            code = request.form.get("code", "").strip().upper()
            kind = request.form.get("kind", "premium_days")
            try:
                value = int(request.form.get("value", "0"))
                max_uses = int(request.form.get("max_uses", "1"))
            except ValueError:
                flash("Значение и лимит должны быть числами")
                return redirect(url_for("promos"))
            expires = request.form.get("expires_at") or None
            if not code or value <= 0 or kind not in ("premium_days", "premium_plus_days", "credits"):
                flash("Заполни код, тип и положительное значение")
                return redirect(url_for("promos"))
            try:
                execute(
                    """INSERT INTO promo_codes (code, kind, value, max_uses, expires_at)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (code) DO UPDATE
                       SET kind=EXCLUDED.kind, value=EXCLUDED.value,
                           max_uses=EXCLUDED.max_uses, expires_at=EXCLUDED.expires_at,
                           active=TRUE""",
                    (code, kind, value, max_uses, expires))
                flash(f"Промокод {code} сохранён")
            except Exception as e:
                flash(f"Не удалось сохранить: {e}")
        return redirect(url_for("promos"))
    rows = query("SELECT * FROM promo_codes ORDER BY code")
    return render_template("promos.html", rows=rows)


# ----------------------------------------------------------------- Новости (лендинг)
import re as _re


def _slugify(text: str) -> str:
    translit = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i',
        'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
        'у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'',
        'э':'e','ю':'yu','я':'ya','і':'i','ї':'yi','є':'e',
    }
    s = (text or "").lower()
    s = "".join(translit.get(ch, ch) for ch in s)
    s = _re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "news")[:60]


def _news_ai_draft(topic: str) -> dict:
    """Сгенерировать черновик новости (RU+EN) по теме через OpenAI. Возвращает dict полей."""
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY не задан для админки"}
    system = (
        "Ты — копирайтер Telegram-бота для подсчёта калорий «Жиромер». Пиши короткие "
        "новости/анонсы для лендинга: живо, по делу, без воды. Верни строго JSON: "
        '{"title_ru","body_ru","title_en","body_en"}. body — 1–3 абзаца, абзацы '
        "разделяй пустой строкой. EN — качественный перевод RU."
    )
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": OPENAI_MODEL_ADMIN,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": f"Тема новости: {topic}"}],
                  "response_format": {"type": "json_object"},
                  "max_tokens": 700, "temperature": 0.6},
            timeout=60)
        import json as _json
        return _json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"error": str(e)}


# Дефолтные SEO-промты «Миф vs правда про КБЖУ» (синхронно с channel.py бота).
_NEWS_FMT = ("Рубрика «Миф vs правда» про КБЖУ. В заголовке начни со слов «Миф vs правда:». "
             "В тексте раздели «❌ Миф: …» и «✅ Правда: …» (по ВОЗ/доказательной базе), "
             "про калории и/или белки-жиры-углеводы. Тема и ключи: ")
_DEFAULT_NEWS_PROMPTS = [
    _NEWS_FMT + "«жиры вредны». Ключи: жиры, КБЖУ, калории.",
    _NEWS_FMT + "«считать калории бесполезно». Ключи: подсчёт калорий, КБЖУ.",
    _NEWS_FMT + "«углеводы вечером в жир». Ключи: углеводы, КБЖУ, калории.",
    _NEWS_FMT + "«обезжиренное помогает худеть». Ключи: жиры, калории, КБЖУ.",
    _NEWS_FMT + "«после 18:00 нельзя есть». Ключи: калории, дефицит калорий, КБЖУ.",
    _NEWS_FMT + "«сахар надо полностью исключить». Ключи: сахар, углеводы, КБЖУ.",
]


def _news_prompts() -> list:
    raw = _get_setting("channel_topics", "")
    items = [s.strip() for s in (raw or "").splitlines() if s.strip()]
    return items or _DEFAULT_NEWS_PROMPTS


# Случайные стили/композиции — чтобы картинки к новостям не были однотипными.
_IMG_STYLES = [
    "professional food photography, top-down flat lay, marble surface, soft daylight",
    "close-up macro shot, shallow depth of field, fresh ingredient, natural light",
    "bright airy kitchen scene, candid lifestyle, morning light",
    "vibrant farmers market stall, colorful produce, documentary style",
    "minimalist still life on pastel background, studio softbox lighting",
    "rustic wooden table, cozy warm tones, side angle, golden hour",
    "clean editorial magazine style, single subject, bold negative space",
    "dynamic action shot, sports and fitness setting, energetic mood",
    "overhead arrangement of ingredients with kitchen scale, neat composition",
    "moody dark-background gourmet photography, dramatic rim light",
]


def _openai_image(prompt: str):
    """Сгенерировать картинку через OpenAI Images. Возвращает (url, error)."""
    if not OPENAI_API_KEY:
        return None, "OPENAI_API_KEY не задан для админки"
    import random as _random
    style = _random.choice(_IMG_STYLES)
    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": OPENAI_IMAGE_MODEL,
                  "prompt": f"{prompt}. Style: {style}. No text, no numbers, no watermark, no logos.",
                  "size": "1024x1024", "n": 1},
            timeout=120)
        body = r.json()
        if r.status_code != 200 or "data" not in body:
            err = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
            return None, f"OpenAI {r.status_code}: {err or str(body)[:200]}"
        d = body["data"][0]
        if d.get("url"):                       # dall-e-3 → готовый URL (живёт ~1ч)
            return d["url"], None
        if d.get("b64_json"):                  # gpt-image-1 → base64; кладём как data-URI
            return "data:image/png;base64," + d["b64_json"], None
        return None, "OpenAI вернул пустой ответ (нет url/b64_json)"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _ensure_news_columns():
    """Идемпотентно гарантируем нужные колонки (на случай, если бот ещё не накатил схему)."""
    try:
        execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS image_url TEXT")
        execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS image_file_id TEXT")
    except Exception:
        pass


def _gen_news_draft():
    """Сгенерировать новость (текст + картинка) и сохранить как ЧЕРНОВИК (не опубликован). (ok, msg)."""
    if not OPENAI_API_KEY:
        return False, "OPENAI_API_KEY не задан для админки"
    import json as _json
    import random as _random
    prompt = _random.choice(_news_prompts())
    system = (
        "Ты — редактор контента про здоровое питание и КБЖУ (бренд «Жиромер») для сайта и "
        "Telegram-канала. Заголовок + текст до 700 знаков, живо, с 1-2 эмодзи, вплети SEO-ключи. "
        "Только достоверные факты (ВОЗ/доказательная база), без выдуманных чисел и обещаний "
        "«минус 10 кг». Также дай короткий промпт на АНГЛИЙСКОМ для картинки к материалу. "
        "Картинка должна быть РАЗНООБРАЗНОЙ и подходящей именно к теме, а НЕ всегда «тарелка с едой»: "
        "выбери уместный сюжет (отдельный продукт/ингредиент крупным планом, разрез фрукта/овоща, "
        "рынок, кухонная сцена, спорт/активность, кухонные весы и мерная посуда, раскладка продуктов "
        "flat lay, концептуальный натюрморт). Опиши конкретную сцену, ракурс и фон, без текста и цифр. "
        'Верни строго JSON: {"title","text","image_prompt"}.')
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": OPENAI_MODEL_NEWS,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": f"Промт: {prompt}"}],
                  "response_format": {"type": "json_object"},
                  "max_tokens": 700, "temperature": 0.7},
            timeout=90)
        data = _json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return False, f"Не удалось сгенерировать текст: {e}"
    title = (data.get("title") or "").strip()[:300]
    text = (data.get("text") or "").strip()
    img_prompt = (data.get("image_prompt") or "").strip()
    if not (title and text and img_prompt):
        return False, "ИИ вернул неполный ответ, попробуй ещё раз"
    image_url, img_err = _openai_image(img_prompt)
    if not image_url:
        return False, f"Не удалось сгенерировать картинку (обязательна): {img_err}"
    slug = _slugify(title) + "-" + dt_now_suffix()
    try:
        execute("""INSERT INTO news (slug, title_ru, body_ru, image_url, published)
                   VALUES (%s,%s,%s,%s,FALSE) ON CONFLICT (slug) DO NOTHING""",
                (slug, title, text, image_url))
    except Exception as e:
        return False, f"Не удалось сохранить черновик: {e}"
    return True, "✅ Превью сгенерировано — проверь ниже и опубликуй"


def _publish_news(news_id):
    """Опубликовать черновик: на сайт + в канал (с заливкой картинки в Telegram). (ok, msg)."""
    row = query("SELECT * FROM news WHERE id=%s", (news_id,), one=True)
    if not row:
        return False, "Черновик не найден"
    title, text, image_url = row["title_ru"], row["body_ru"], row.get("image_url")
    file_id = None
    if BOT_TOKEN and CHANNEL_ID and image_url:
        try:
            bot_link = "https://t.me/zhiromer_bot?start=channel"
            try:
                me = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10).json()
                bot_link = f"https://t.me/{me['result']['username']}?start=channel"
            except Exception:
                pass
            caption = f"{title}\n\n{text}\n\n👉 {bot_link}"[:1024]
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            if image_url.startswith("data:"):        # gpt-image-1 → грузим байты файлом
                import base64
                photo = base64.b64decode(image_url.split(",", 1)[1])
                resp = requests.post(url, data={"chat_id": CHANNEL_ID, "caption": caption},
                                     files={"photo": ("news.png", photo, "image/png")},
                                     timeout=60).json()
            else:                                     # dall-e-3 → отдаём по URL
                resp = requests.post(url, data={"chat_id": CHANNEL_ID, "photo": image_url,
                                                "caption": caption}, timeout=30).json()
            if resp.get("ok"):
                # самый крупный размер фото — постоянный file_id для сайта
                file_id = resp["result"]["photo"][-1]["file_id"]
        except Exception as e:
            return False, f"Не удалось опубликовать в канал: {e}"
    # если получили постоянный file_id — выкидываем тяжёлый data-URI из БД
    if file_id:
        execute("""UPDATE news SET published=TRUE, published_at=now(),
                   image_file_id=%s, image_url=NULL WHERE id=%s""", (file_id, news_id))
    else:
        execute("UPDATE news SET published=TRUE, published_at=now() WHERE id=%s", (news_id,))
    where = "на сайт и в канал" if file_id else "на сайт"
    return True, f"✅ Опубликовано ({where})"


@app.route("/news", methods=["GET", "POST"])
@login_required
def news_admin():
    _ensure_news_columns()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_prompts":
            _set_setting("channel_topics", (request.form.get("channel_topics") or "").strip())
            flash("Промты сохранены")
        elif action == "gen_preview":
            flash(_gen_news_draft()[1])
        elif action == "publish":
            flash(_publish_news(request.form.get("id"))[1])
        elif action == "discard":
            execute("DELETE FROM news WHERE id=%s AND NOT published", (request.form.get("id"),))
            flash("Черновик удалён")
        return redirect(url_for("news_admin"))

    prompts = _get_setting("channel_topics", "")
    draft = query("SELECT * FROM news WHERE NOT published ORDER BY created_at DESC LIMIT 1", one=True)
    recent = query("SELECT * FROM news WHERE published ORDER BY published_at DESC LIMIT 10") or []
    return render_template("news.html", prompts=prompts, draft=draft, recent=recent,
                           default_prompts="\n".join(_DEFAULT_NEWS_PROMPTS))


def dt_now_suffix() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%m%d%H%M")


# ----------------------------------------------------------------- Настройки
def _get_setting(key, default=""):
    row = query("SELECT value FROM settings WHERE key=%s", (key,), one=True)
    return row["value"] if row else default


def _set_setting(key, value):
    execute("""INSERT INTO settings (key, value) VALUES (%s,%s)
               ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""", (key, str(value)))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        _set_setting("monetization_enabled", "1" if request.form.get("monetization") == "on" else "0")
        _set_setting("macros_tier_enabled", "1" if request.form.get("macros_tier") == "on" else "0")
        _set_setting("referral_enabled", "1" if request.form.get("referral_enabled") == "on" else "0")
        _set_setting("channel_enabled", "1" if request.form.get("channel_enabled") == "on" else "0")
        _set_setting("channel_topics", (request.form.get("channel_topics") or "").strip())
        try:
            _set_setting("channel_per_day", max(1, int(request.form.get("channel_per_day", "1"))))
            _set_setting("free_daily_ai", max(0, int(request.form.get("free_daily_ai", "3"))))
            _set_setting("free_period_days", max(1, int(request.form.get("free_period_days", "30"))))
            _set_setting("premium_price", max(1, int(request.form.get("premium_price", "200"))))
            _set_setting("macros_price", max(1, int(request.form.get("macros_price", "300"))))
            _set_setting("referral_reward_days", max(1, int(request.form.get("referral_reward_days", "30"))))
            _set_setting("referral_friends_needed", max(1, int(request.form.get("referral_friends_needed", "1"))))
        except ValueError:
            flash("Числовые поля должны быть числами")
        flash("Настройки сохранены — бот подхватит их в течение минуты")
        return redirect(url_for("settings"))
    cur = {
        "monetization": _get_setting("monetization_enabled", "0") in ("1", "true", "yes", "on"),
        "macros_tier": _get_setting("macros_tier_enabled", "1") in ("1", "true", "yes", "on"),
        "free_daily_ai": _get_setting("free_daily_ai", "3"),
        "free_period_days": _get_setting("free_period_days", "30"),
        "premium_price": _get_setting("premium_price", "200"),
        "macros_price": _get_setting("macros_price", "300"),
        "referral_enabled": _get_setting("referral_enabled", "1") in ("1", "true", "yes", "on"),
        "referral_reward_days": _get_setting("referral_reward_days", "30"),
        "referral_friends_needed": _get_setting("referral_friends_needed", "1"),
        "channel_enabled": _get_setting("channel_enabled", "0") in ("1", "true", "yes", "on"),
        "channel_per_day": _get_setting("channel_per_day", "1"),
        "channel_topics": _get_setting("channel_topics", ""),
    }
    return render_template("settings.html", cur=cur)


# ----------------------------------------------------------------- ИИ-помощник
ASSISTANT_SYSTEM = (
    "Ты — продуктовый аналитик Telegram-бота для подсчёта калорий «Жиромер». "
    "Тебе дают текущие метрики продукта. Отвечай кратко и по делу на русском: "
    "находи проблемы, предлагай конкретные шаги по росту, удержанию и монетизации. "
    "Опирайся только на предоставленные цифры, не выдумывай данные."
)


def _stats_context():
    s = collect_stats()
    return (
        f"Пользователей всего: {s['total_users']}; новых сегодня/7д/30д: "
        f"{s['new_today']}/{s['new_7d']}/{s['new_30d']}. "
        f"DAU/WAU/MAU: {s['dau']}/{s['wau']}/{s['mau']}, stickiness {s['stickiness']}%. "
        f"Приёмов пищи сегодня/7д: {s['entries_today']}/{s['entries_7d']}. "
        f"Активных Premium: {s['premium_active']}, платящих всего: {s['paying_users']}, "
        f"конверсия {s['conversion']}%. Выручка 30д: {s['stars_30d']}★ (≈${s['usd_30d']}). "
        f"Открытых багов: {s['open_bugs']}, замечаний по калориям: {s['open_cal']}."
    )


def _ask_openai(question, history):
    if not OPENAI_API_KEY:
        return "OPENAI_API_KEY не задан для админки — добавь его в Environment сервиса."
    messages = [{"role": "system", "content": ASSISTANT_SYSTEM},
                {"role": "system", "content": "Текущие метрики: " + _stats_context()}]
    for turn in history[-6:]:
        messages.append({"role": "user", "content": turn["q"]})
        messages.append({"role": "assistant", "content": turn["a"]})
    messages.append({"role": "user", "content": question})
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": OPENAI_MODEL_ADMIN, "messages": messages,
                  "max_tokens": 700, "temperature": 0.5},
            timeout=60)
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Не удалось получить ответ: {e}"


@app.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant():
    history = session.get("chat", [])
    if request.method == "POST":
        if request.form.get("action") == "clear":
            session["chat"] = []
            return redirect(url_for("assistant"))
        q = (request.form.get("q") or "").strip()
        if q:
            a = _ask_openai(q, history)
            history = history + [{"q": q, "a": a}]
            session["chat"] = history[-12:]
        return redirect(url_for("assistant"))
    return render_template("assistant.html", history=history, ctx=_stats_context())


# ----------------------------------------------------------------- прокси медиа
@app.route("/media/<file_id>")
@login_required
def media(file_id):
    """Тянет файл из Telegram по file_id (токен остаётся на сервере)."""
    if not BOT_TOKEN:
        return "BOT_TOKEN не задан", 500
    try:
        gf = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                          params={"file_id": file_id}, timeout=15).json()
        file_path = gf["result"]["file_path"]
        fr = requests.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}", timeout=30)
        return Response(fr.content,
                        content_type=fr.headers.get("Content-Type", "application/octet-stream"))
    except Exception as e:
        return f"Не удалось загрузить медиа: {e}", 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)
