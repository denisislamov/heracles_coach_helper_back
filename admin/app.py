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

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-please")


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
@app.route("/analytics")
@login_required
def analytics():
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
            if not code or value <= 0 or kind not in ("premium_days", "credits"):
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
