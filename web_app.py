"""
web_app.py - Flask web app for Baby Tracker.

Run locally:
    pip install -r requirements.txt
    export FLASK_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
    python web_app.py

In production, gunicorn picks it up via the Procfile:
    gunicorn web_app:app
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect,
                   render_template, request, session, url_for)

import web_db as db


SLEEP_LOCATIONS = ["Bassinet", "Crib", "Stroller", "Car seat",
                   "Carrier", "Mom's arms", "Dad's arms", "Other"]
FEED_TYPES = ["bottle", "breast", "formula"]
SIDES = ["", "left", "right", "both"]
DIAPER_TYPES = ["wet", "dirty", "both"]


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get(
        "FLASK_SECRET_KEY",
        # Dev fallback. Set FLASK_SECRET_KEY in production!
        "dev-only-not-secret-please-override",
    )
    app.jinja_env.globals["fmt_minutes"] = fmt_minutes

    db.init_db()

    # ---- helpers ----

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapper

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("user_id")
        if uid is not None:
            g.user = db.get_user(uid)
            if g.user is None:
                session.clear()

    # =========================================================
    # Auth
    # =========================================================

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email = request.form.get("email", "")
            password = request.form.get("password", "")
            display_name = request.form.get("display_name", "")
            try:
                user_id = db.create_user(email, password, display_name)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("register.html", email=email,
                                       display_name=display_name)
            session["user_id"] = user_id
            flash("Account created. Welcome!", "ok")
            return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "")
            password = request.form.get("password", "")
            user = db.authenticate(email, password)
            if not user:
                flash("Wrong email or password.", "error")
                return render_template("login.html", email=email)
            session.clear()
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # =========================================================
    # Dashboard (the main quick-log page)
    # =========================================================

    @app.route("/")
    @login_required
    def dashboard():
        uid = session["user_id"]
        open_sleep = db.get_open_sleep_session(uid)
        summary = db.daily_summary(uid)
        recent = {
            "sleep": db.list_sleep(uid, limit=5),
            "feeds": db.list_feeds(uid, limit=5),
            "diapers": db.list_diapers(uid, limit=5),
        }
        return render_template(
            "dashboard.html",
            open_sleep=open_sleep,
            summary=summary,
            recent=recent,
            sleep_locations=SLEEP_LOCATIONS,
            feed_types=FEED_TYPES,
            sides=SIDES,
            diaper_types=DIAPER_TYPES,
            now=db.now_iso(),
        )

    # =========================================================
    # Sleep
    # =========================================================

    @app.route("/sleep/start", methods=["POST"])
    @login_required
    def sleep_start():
        uid = session["user_id"]
        try:
            db.start_sleep(uid, request.form.get("location", "").strip())
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("dashboard"))

    @app.route("/sleep/stop/<int:session_id>", methods=["POST"])
    @login_required
    def sleep_stop(session_id):
        uid = session["user_id"]
        try:
            mins = db.stop_sleep(uid, session_id)
            flash(f"Sleep ended — {fmt_minutes(mins)}.", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("dashboard"))

    @app.route("/sleep/manual", methods=["POST"])
    @login_required
    def sleep_manual():
        uid = session["user_id"]
        try:
            db.add_completed_sleep(
                uid,
                location=request.form.get("location", "").strip(),
                start_time=request.form.get("start_time", "").strip(),
                end_time=request.form.get("end_time", "").strip(),
                notes=request.form.get("notes", "").strip(),
            )
            flash("Sleep saved.", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("dashboard"))

    # =========================================================
    # Feed
    # =========================================================

    @app.route("/feed/add", methods=["POST"])
    @login_required
    def feed_add():
        uid = session["user_id"]

        def parse_float(name):
            v = (request.form.get(name) or "").strip()
            return float(v) if v else None

        try:
            db.add_feed(
                uid,
                feed_type=request.form.get("feed_type", ""),
                amount_ml=parse_float("amount_ml"),
                duration_minutes=parse_float("duration_minutes"),
                side=request.form.get("side") or None,
                feed_time=request.form.get("feed_time", "").strip() or None,
                notes=request.form.get("notes", "").strip(),
            )
            flash("Feed logged.", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("dashboard"))

    # =========================================================
    # Diaper
    # =========================================================

    @app.route("/diaper/add", methods=["POST"])
    @login_required
    def diaper_add():
        uid = session["user_id"]
        try:
            db.add_diaper(
                uid,
                diaper_type=request.form.get("diaper_type", ""),
                change_time=request.form.get("change_time", "").strip() or None,
                notes=request.form.get("notes", "").strip(),
            )
            flash("Diaper logged.", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("dashboard"))

    # =========================================================
    # History
    # =========================================================

    @app.route("/history")
    @login_required
    def history():
        uid = session["user_id"]
        kind = request.args.get("kind", "sleep")
        if kind == "feed":
            entries = db.list_feeds(uid)
        elif kind == "diaper":
            entries = db.list_diapers(uid)
        else:
            kind = "sleep"
            entries = db.list_sleep(uid)
        return render_template("history.html", kind=kind, entries=entries)

    @app.route("/delete/<kind>/<int:entry_id>", methods=["POST"])
    @login_required
    def delete(kind, entry_id):
        uid = session["user_id"]
        try:
            db.delete_entry(uid, kind, entry_id)
        except ValueError:
            abort(400)
        return redirect(request.referrer or url_for("dashboard"))

    # =========================================================
    # Daily summary (separate page; dashboard also shows today's)
    # =========================================================

    @app.route("/summary")
    @login_required
    def summary():
        uid = session["user_id"]
        date_str = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            flash("Bad date — use YYYY-MM-DD.", "error")
            day = datetime.now()
            date_str = day.strftime("%Y-%m-%d")
        s = db.daily_summary(uid, day)
        return render_template("summary.html", summary=s, date_str=date_str)

    # =========================================================
    # CSV export
    # =========================================================

    @app.route("/export/<table>")
    @login_required
    def export(table):
        uid = session["user_id"]
        try:
            data = db.export_table_csv(uid, table)
        except ValueError:
            abort(404)
        return Response(
            data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{table}.csv"',
            },
        )

    # =========================================================
    # Health check (useful for hosts)
    # =========================================================

    @app.route("/healthz")
    def health():
        return {"ok": True}, 200

    return app


# ---------- jinja helper ----------

def fmt_minutes(mins):
    if mins is None:
        return "—"
    mins = float(mins)
    h = int(mins // 60)
    m = int(round(mins - h * 60))
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
