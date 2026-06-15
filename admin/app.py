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

APP_VERSION = "1.9.0"  # версия админки (синхронизируй с version.py бота)

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

    return render_template("analytics.html", s=stats, labels=labels,
                           new_users_series=new_users_series, entries_series=entries_series)


# ----------------------------------------------------------------- Пользователи
def _plan_label(u) -> str:
    import datetime as dt
    active = u["premium_until"] and u["premium_until"] > dt.datetime.now(dt.timezone.utc)
    base = {"free": "Free", "premium": "Premium", "premium_plus": "Premium+КБЖУ"}.get(u["plan"], u["plan"])
    if u["plan"] != "free" and not active:
        return base + " (истёк)"
    return base


@app.route("/users")
@login_required
def users():
    q = (request.args.get("q") or "").strip()
    flt = request.args.get("filter", "")  # '', alpha, premium, premium_plus, referred, byok, paying
    where, params = [], []
    if q:
        if q.lstrip("-").isdigit():
            where.append("(u.user_id = %s OR u.username ILIKE %s)")
            params += [int(q), f"%{q}%"]
        else:
            where.append("u.username ILIKE %s")
            params.append(f"%{q.lstrip('@')}%")
    if flt == "alpha":
        where.append("u.is_alpha = TRUE")
    elif flt == "premium":
        where.append("u.plan = 'premium' AND u.premium_until > now()")
    elif flt == "premium_plus":
        where.append("u.plan = 'premium_plus' AND u.premium_until > now()")
    elif flt == "referred":
        where.append("u.referred_by IS NOT NULL")
    elif flt == "byok":
        where.append("u.openai_key_enc IS NOT NULL")
    elif flt == "paying":
        where.append("EXISTS (SELECT 1 FROM payments p WHERE p.user_id = u.user_id AND NOT p.is_refunded)")
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
                   (SELECT count(*) FROM entries e WHERE e.user_id = u.user_id) AS entries_count
            FROM users u {where_sql}
            ORDER BY u.created_at DESC LIMIT {PER_PAGE} OFFSET %s""",
        params + [offset]) or []
    summary = {
        "total": query("SELECT count(*) c FROM users", one=True)["c"],
        "premium": query("SELECT count(*) c FROM users WHERE plan='premium' AND premium_until>now()", one=True)["c"],
        "premium_plus": query("SELECT count(*) c FROM users WHERE plan='premium_plus' AND premium_until>now()", one=True)["c"],
        "alpha": query("SELECT count(*) c FROM users WHERE is_alpha", one=True)["c"],
    }
    return render_template("users.html", rows=rows, q=q, flt=flt, summary=summary,
                           plan_label=_plan_label, page=page, pages=pages,
                           matched=matched, per_page=PER_PAGE)


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
        try:
            _set_setting("free_daily_ai", max(0, int(request.form.get("free_daily_ai", "3"))))
            _set_setting("free_period_days", max(1, int(request.form.get("free_period_days", "30"))))
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
        "macros_price": _get_setting("macros_price", "300"),
        "referral_enabled": _get_setting("referral_enabled", "1") in ("1", "true", "yes", "on"),
        "referral_reward_days": _get_setting("referral_reward_days", "30"),
        "referral_friends_needed": _get_setting("referral_friends_needed", "1"),
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
