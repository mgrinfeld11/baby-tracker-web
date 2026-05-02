"""
web_app.py - Flask web app for Baby Tracker (multi-user, PWA + Web Push).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify,
                   redirect, render_template, request, send_from_directory,
                   session, url_for)

import web_db as db


SLEEP_LOCATIONS = ["Bassinet", "Crib", "Stroller", "Car seat",
                   "Carrier", "Mom's arms", "Dad's arms", "Other"]
FEED_TYPES = ["bottle", "breast", "formula"]
SIDES = ["", "left", "right", "both"]
DIAPER_TYPES = ["wet", "dirty", "both"]


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get(
        "FLASK_SECRET_KEY", "dev-only-not-secret-please-override")
    app.jinja_env.globals["fmt_minutes"] = fmt_minutes
    db.init_db()

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

    @app.context_processor
    def inject_globals():
        return {"vapid_public_key": os.environ.get("VAPID_PUBLIC_KEY", "")}

    # ----- Auth -----
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

    # ----- Dashboard -----
    @app.route("/")
    @login_required
    def dashboard():
        uid = session["user_id"]
        return render_template(
            "dashboard.html",
            open_sleep=db.get_open_sleep_session(uid),
            summary=db.daily_summary(uid),
            recent={
                "sleep": db.list_sleep(uid, limit=5),
                "feeds": db.list_feeds(uid, limit=5),
                "diapers": db.list_diapers(uid, limit=5),
            },
            sleep_chart=db.sleep_minutes_per_day(uid, days=7),
            reminder_state=db.compute_reminder_state(uid),
            sleep_locations=SLEEP_LOCATIONS,
            feed_types=FEED_TYPES, sides=SIDES, diaper_types=DIAPER_TYPES,
            now_utc=db.now_iso_utc(),
        )

    # ----- Sleep -----
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
            flash(f"Sleep ended -- {fmt_minutes(mins)}.", "ok")
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

    # ----- Feed -----
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
                amount_oz=parse_float("amount_oz"),
                duration_minutes=parse_float("duration_minutes"),
                side=request.form.get("side") or None,
                feed_time=request.form.get("feed_time", "").strip() or None,
                notes=request.form.get("notes", "").strip(),
            )
            flash("Feed logged.", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("dashboard"))

    # ----- Diaper -----
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

    # ----- History + delete -----
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

    # ----- Daily summary -----
    @app.route("/summary")
    @login_required
    def summary():
        uid = session["user_id"]
        date_str = request.args.get("date") or db.now_utc().strftime("%Y-%m-%d")
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            flash("Bad date -- use YYYY-MM-DD.", "error")
            day = db.now_utc()
            date_str = day.strftime("%Y-%m-%d")
        s = db.daily_summary(uid, day)
        return render_template("summary.html", summary=s, date_str=date_str)

    # ----- Settings -----
    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings_view():
        uid = session["user_id"]
        if request.method == "POST":
            try:
                db.update_settings(
                    uid,
                    feed_interval_min=int(request.form.get("feed_interval_min", 180)),
                    reminder_lead_min=int(request.form.get("reminder_lead_min", 20)),
                    notifications_on=bool(request.form.get("notifications_on")),
                )
                flash("Settings saved.", "ok")
            except ValueError as e:
                flash(str(e), "error")
            return redirect(url_for("settings_view"))
        return render_template(
            "settings.html",
            settings=db.get_settings(uid),
            subscription_count=len(db.list_push_subscriptions(uid)),
        )

    # ----- CSV export -----
    @app.route("/export/<table>")
    @login_required
    def export(table):
        uid = session["user_id"]
        try:
            data = db.export_table_csv(uid, table)
        except ValueError:
            abort(404)
        return Response(data, mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})

    # ----- PWA: manifest + service worker -----
    @app.route("/manifest.json")
    def manifest():
        return jsonify({
            "name": "Baby Tracker", "short_name": "Baby",
            "description": "Track baby sleep, feeds, and diapers.",
            "start_url": "/", "scope": "/",
            "display": "standalone", "orientation": "portrait",
            "background_color": "#f7f8fb", "theme_color": "#5b8def",
            "icons": [
                {"src": "/static/icon-192.png", "sizes": "192x192",
                 "type": "image/png", "purpose": "any maskable"},
                {"src": "/static/icon-512.png", "sizes": "512x512",
                 "type": "image/png", "purpose": "any maskable"},
            ],
        })

    @app.route("/sw.js")
    def service_worker():
        return send_from_directory(app.static_folder, "sw.js",
            mimetype="application/javascript", max_age=0)

    # ----- Push subscription -----
    @app.route("/push/subscribe", methods=["POST"])
    @login_required
    def push_subscribe():
        uid = session["user_id"]
        body = request.get_json(silent=True) or {}
        try:
            endpoint = body["endpoint"]
            p256dh = body["keys"]["p256dh"]
            auth = body["keys"]["auth"]
        except (KeyError, TypeError):
            return jsonify({"ok": False, "error": "bad subscription"}), 400
        ua = request.headers.get("User-Agent", "")[:300]
        db.save_push_subscription(uid, endpoint, p256dh, auth, ua)
        return jsonify({"ok": True})

    @app.route("/push/unsubscribe", methods=["POST"])
    @login_required
    def push_unsubscribe():
        body = request.get_json(silent=True) or {}
        endpoint = body.get("endpoint")
        if endpoint:
            db.delete_push_subscription(endpoint)
        return jsonify({"ok": True})

    @app.route("/push/test", methods=["POST"])
    @login_required
    def push_test():
        uid = session["user_id"]
        subs = db.list_push_subscriptions(uid)
        if not subs:
            return jsonify({
                "ok": False,
                "error": "No push subscriptions saved on this account yet. "
                         "Allow notifications first.",
            }), 400
        from push_sender import send_to_subscriptions
        result = send_to_subscriptions(
            subs, title="Test notification",
            body="If you see this, push is working!",
            url=url_for("dashboard", _external=True),
        )
        return jsonify({"ok": True, **result})

    # ----- Cron endpoint -----
    @app.route("/internal/cron/check-reminders")
    def cron_check_reminders():
        token = request.args.get("token", "")
        expected = os.environ.get("REMINDER_CRON_TOKEN", "")
        if not expected or token != expected:
            abort(403)
        due = db.find_users_due_for_reminder()
        if not due:
            return jsonify({"checked": True, "reminders_sent": 0})
        from push_sender import send_to_subscriptions
        sent = 0
        for d in due:
            subs = db.list_push_subscriptions(d["user_id"])
            if not subs:
                continue
            result = send_to_subscriptions(
                subs, title="Feeding due soon",
                body=f"Next feed in about {d['lead_min']} minutes.",
                url=url_for("dashboard", _external=True),
            )
            sent += result.get("sent", 0)
        return jsonify({"checked": True, "reminders_sent": sent})

    @app.route("/healthz")
    def health():
        return {"ok": True}, 200

    return app


def fmt_minutes(mins):
    if mins is None:
        return "--"
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
