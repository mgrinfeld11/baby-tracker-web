"""
web_db.py - SQLite layer for the Baby Tracker web app (multi-user).

All timestamps are stored as UTC ISO 8601 strings with a trailing Z
(e.g. "2026-05-02T07:30:00Z"). Each browser converts to local time at
display time using the <time data-utc="..."> pattern in the templates.
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.environ.get(
    "BABY_TRACKER_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "baby_tracker.db"),
)

UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"
ML_PER_OZ = 29.5735


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sleep_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    location         TEXT NOT NULL,
    start_time       TEXT NOT NULL,
    end_time         TEXT,
    duration_minutes REAL,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS feeds (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feed_time        TEXT NOT NULL,
    feed_type        TEXT NOT NULL,
    amount_ml        REAL,
    amount_oz        REAL,
    duration_minutes REAL,
    side             TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS diaper_changes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    change_time  TEXT NOT NULL,
    diaper_type  TEXT NOT NULL,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id              INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    feed_interval_min    INTEGER NOT NULL DEFAULT 180,
    reminder_lead_min    INTEGER NOT NULL DEFAULT 20,
    notifications_on     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    user_agent  TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS reminder_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_feed_time  TEXT NOT NULL,
    sent_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(user_id, last_feed_time)
);

CREATE INDEX IF NOT EXISTS idx_sleep_user_start ON sleep_sessions (user_id, start_time);
CREATE INDEX IF NOT EXISTS idx_feed_user_time   ON feeds (user_id, feed_time);
CREATE INDEX IF NOT EXISTS idx_diaper_user_time ON diaper_changes (user_id, change_time);
CREATE INDEX IF NOT EXISTS idx_subs_user        ON push_subscriptions (user_id);
"""


def _has_column(conn, table, column):
    return any(r["name"] == column
               for r in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _migrate_legacy_data(conn):
    if not _has_column(conn, "feeds", "amount_oz"):
        conn.execute("ALTER TABLE feeds ADD COLUMN amount_oz REAL")
    conn.execute(
        "UPDATE feeds SET amount_oz = amount_ml / ? "
        "WHERE amount_oz IS NULL AND amount_ml IS NOT NULL",
        (ML_PER_OZ,),
    )
    for table, col in [("sleep_sessions", "start_time"),
                       ("sleep_sessions", "end_time"),
                       ("feeds", "feed_time"),
                       ("diaper_changes", "change_time")]:
        conn.execute(
            f"UPDATE {table} SET {col} = REPLACE({col}, ' ', 'T') || 'Z' "
            f"WHERE {col} IS NOT NULL "
            f"  AND {col} NOT LIKE '%Z' "
            f"  AND {col} NOT LIKE '%+__:__'"
        )


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_legacy_data(conn)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso_utc():
    return now_utc().strftime(UTC_FMT)


def to_iso_utc(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(UTC_FMT)


def from_iso_utc(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = s.replace(" ", "T", 1)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----- Users / auth -----

def create_user(email, password, display_name=""):
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 5:
        raise ValueError("Please enter a valid email address.")
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    pw_hash = generate_password_hash(password)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, display_name, password_hash) VALUES (?, ?, ?)",
                (email, display_name.strip() or None, pw_hash),
            )
            user_id = cur.lastrowid
            conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
        except sqlite3.IntegrityError:
            raise ValueError("That email is already registered.")
        return user_id


def authenticate(email, password):
    email = (email or "").strip().lower()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row and check_password_hash(row["password_hash"], password):
        return row
    return None


def get_user(user_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# ----- Settings -----

def get_settings(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
            return {"feed_interval_min": 180, "reminder_lead_min": 20, "notifications_on": 1}
    return dict(row)


def update_settings(user_id, feed_interval_min, reminder_lead_min, notifications_on=True):
    if feed_interval_min < 30 or feed_interval_min > 720:
        raise ValueError("Feed interval must be between 30 and 720 minutes.")
    if reminder_lead_min < 0 or reminder_lead_min > feed_interval_min:
        raise ValueError("Reminder lead must be between 0 and the interval length.")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, feed_interval_min, "
            "reminder_lead_min, notifications_on) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "  feed_interval_min = excluded.feed_interval_min, "
            "  reminder_lead_min = excluded.reminder_lead_min, "
            "  notifications_on  = excluded.notifications_on",
            (user_id, feed_interval_min, reminder_lead_min,
             1 if notifications_on else 0),
        )


# ----- Sleep -----

def start_sleep(user_id, location, start_time=None, notes=""):
    if not location:
        raise ValueError("Sleep location is required.")
    start_time = start_time or now_iso_utc()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sleep_sessions (user_id, location, start_time, notes) "
            "VALUES (?, ?, ?, ?)",
            (user_id, location, start_time, notes),
        )
        return cur.lastrowid


def stop_sleep(user_id, session_id, end_time=None):
    end_time = end_time or now_iso_utc()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT start_time FROM sleep_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError("Sleep session not found.")
        duration_min = max(0.0,
            (from_iso_utc(end_time) - from_iso_utc(row["start_time"])).total_seconds() / 60.0)
        conn.execute(
            "UPDATE sleep_sessions SET end_time = ?, duration_minutes = ? "
            "WHERE id = ? AND user_id = ?",
            (end_time, duration_min, session_id, user_id),
        )
        return duration_min


def add_completed_sleep(user_id, location, start_time, end_time, notes=""):
    start = from_iso_utc(start_time)
    end = from_iso_utc(end_time)
    if end < start:
        raise ValueError("End time must be after start time.")
    duration_min = (end - start).total_seconds() / 60.0
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sleep_sessions "
            "(user_id, location, start_time, end_time, duration_minutes, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, location, to_iso_utc(start), to_iso_utc(end),
             duration_min, notes),
        )
        return cur.lastrowid


def get_open_sleep_session(user_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sleep_sessions WHERE user_id = ? AND end_time IS NULL "
            "ORDER BY start_time DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def list_sleep(user_id, limit=200):
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM sleep_sessions WHERE user_id = ? "
            "ORDER BY start_time DESC LIMIT ?",
            (user_id, limit),
        ).fetchall())


def sleep_minutes_per_day(user_id, days=7):
    end = now_utc().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = end - timedelta(days=days)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT substr(start_time, 1, 10) AS day, "
            "       COALESCE(SUM(duration_minutes), 0) AS mins "
            "FROM sleep_sessions WHERE user_id = ? AND end_time IS NOT NULL "
            "  AND start_time >= ? AND start_time < ? GROUP BY day",
            (user_id, to_iso_utc(start), to_iso_utc(end)),
        ).fetchall()
    by_day = {r["day"]: float(r["mins"]) for r in rows}
    out = []
    cursor = start
    for _ in range(days):
        key = cursor.strftime("%Y-%m-%d")
        out.append({"date": key, "minutes": by_day.get(key, 0.0)})
        cursor += timedelta(days=1)
    return out


# ----- Feeds -----

def add_feed(user_id, feed_type, amount_oz=None, duration_minutes=None,
             side=None, feed_time=None, notes=""):
    feed_type = (feed_type or "").lower().strip()
    if feed_type not in {"bottle", "breast", "formula"}:
        raise ValueError("Feed type must be bottle, breast, or formula.")
    if feed_type == "breast":
        amount_oz = None
    else:
        duration_minutes = None
        side = None
    if side:
        side = side.lower().strip() or None
        if side and side not in {"left", "right", "both"}:
            raise ValueError("Side must be left, right, or both.")
    feed_time = feed_time or now_iso_utc()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO feeds (user_id, feed_time, feed_type, amount_oz, "
            "duration_minutes, side, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, feed_time, feed_type, amount_oz, duration_minutes, side, notes),
        )
        return cur.lastrowid


def list_feeds(user_id, limit=200):
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM feeds WHERE user_id = ? ORDER BY feed_time DESC LIMIT ?",
            (user_id, limit),
        ).fetchall())


def get_last_feed(user_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM feeds WHERE user_id = ? ORDER BY feed_time DESC LIMIT 1",
            (user_id,),
        ).fetchone()


# ----- Diapers -----

def add_diaper(user_id, diaper_type, change_time=None, notes=""):
    diaper_type = (diaper_type or "").lower().strip()
    if diaper_type not in {"wet", "dirty", "both"}:
        raise ValueError("Diaper type must be wet, dirty, or both.")
    change_time = change_time or now_iso_utc()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO diaper_changes (user_id, change_time, diaper_type, notes) "
            "VALUES (?, ?, ?, ?)",
            (user_id, change_time, diaper_type, notes),
        )
        return cur.lastrowid


def list_diapers(user_id, limit=200):
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM diaper_changes WHERE user_id = ? "
            "ORDER BY change_time DESC LIMIT ?",
            (user_id, limit),
        ).fetchall())


# ----- Delete -----

_TABLES = {"sleep": "sleep_sessions", "feed": "feeds", "diaper": "diaper_changes"}


def delete_entry(user_id, kind, entry_id):
    table = _TABLES.get(kind)
    if not table:
        raise ValueError(f"Unknown entry kind: {kind}")
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ? AND user_id = ?",
                     (entry_id, user_id))


# ----- Daily summary -----

def daily_summary(user_id, day=None):
    day = day or now_utc()
    if day.tzinfo is None:
        day = day.replace(tzinfo=timezone.utc)
    start = day.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    s_iso, e_iso = to_iso_utc(start), to_iso_utc(end)
    with get_conn() as conn:
        sleep_row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(duration_minutes), 0) AS mins "
            "FROM sleep_sessions WHERE user_id = ? "
            "AND start_time >= ? AND start_time < ? AND end_time IS NOT NULL",
            (user_id, s_iso, e_iso)).fetchone()
        feed_row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_oz), 0) AS oz "
            "FROM feeds WHERE user_id = ? AND feed_time >= ? AND feed_time < ?",
            (user_id, s_iso, e_iso)).fetchone()
        feed_breakdown = conn.execute(
            "SELECT feed_type, COUNT(*) AS n FROM feeds WHERE user_id = ? "
            "AND feed_time >= ? AND feed_time < ? GROUP BY feed_type",
            (user_id, s_iso, e_iso)).fetchall()
        diaper_row = conn.execute(
            "SELECT COUNT(*) AS n FROM diaper_changes WHERE user_id = ? "
            "AND change_time >= ? AND change_time < ?",
            (user_id, s_iso, e_iso)).fetchone()
        diaper_breakdown = conn.execute(
            "SELECT diaper_type, COUNT(*) AS n FROM diaper_changes "
            "WHERE user_id = ? AND change_time >= ? AND change_time < ? "
            "GROUP BY diaper_type",
            (user_id, s_iso, e_iso)).fetchall()
    return {
        "date": start.strftime("%Y-%m-%d"),
        "sleep_count": sleep_row["n"],
        "sleep_minutes": float(sleep_row["mins"] or 0),
        "feed_count": feed_row["n"],
        "feed_total_oz": float(feed_row["oz"] or 0),
        "feed_breakdown": {r["feed_type"]: r["n"] for r in feed_breakdown},
        "diaper_count": diaper_row["n"],
        "diaper_breakdown": {r["diaper_type"]: r["n"] for r in diaper_breakdown},
    }


# ----- CSV export -----

_EXPORT_QUERIES = {
    "sleep_sessions": (
        "SELECT id, location, start_time, end_time, duration_minutes, notes "
        "FROM sleep_sessions WHERE user_id = ? ORDER BY start_time",
        ["id", "location", "start_time", "end_time", "duration_minutes", "notes"],
    ),
    "feeds": (
        "SELECT id, feed_time, feed_type, amount_oz, duration_minutes, side, notes "
        "FROM feeds WHERE user_id = ? ORDER BY feed_time",
        ["id", "feed_time", "feed_type", "amount_oz", "duration_minutes", "side", "notes"],
    ),
    "diaper_changes": (
        "SELECT id, change_time, diaper_type, notes "
        "FROM diaper_changes WHERE user_id = ? ORDER BY change_time",
        ["id", "change_time", "diaper_type", "notes"],
    ),
}


def export_table_csv(user_id, table):
    if table not in _EXPORT_QUERIES:
        raise ValueError(f"Unknown table: {table}")
    query, headers = _EXPORT_QUERIES[table]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    with get_conn() as conn:
        for row in conn.execute(query, (user_id,)):
            writer.writerow([row[h] for h in headers])
    return buf.getvalue().encode("utf-8")


# ----- Push subscriptions -----

def save_push_subscription(user_id, endpoint, p256dh, auth, user_agent=""):
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, endpoint, p256dh, auth, user_agent or None),
            )
        except sqlite3.IntegrityError:
            conn.execute(
                "UPDATE push_subscriptions SET user_id = ?, p256dh = ?, auth = ?, "
                "user_agent = ? WHERE endpoint = ?",
                (user_id, p256dh, auth, user_agent or None, endpoint),
            )


def list_push_subscriptions(user_id=None):
    with get_conn() as conn:
        if user_id is None:
            return list(conn.execute("SELECT * FROM push_subscriptions").fetchall())
        return list(conn.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)
        ).fetchall())


def delete_push_subscription(endpoint):
    with get_conn() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


# ----- Reminder logic -----

def compute_reminder_state(user_id):
    settings = get_settings(user_id)
    last = get_last_feed(user_id)
    interval = int(settings["feed_interval_min"])
    lead = int(settings["reminder_lead_min"])
    if last is None:
        return {
            "last_feed_utc": None, "next_feed_utc": None,
            "reminder_at_utc": None, "interval_min": interval, "lead_min": lead,
            "notifications_on": bool(settings["notifications_on"]),
        }
    last_dt = from_iso_utc(last["feed_time"])
    next_dt = last_dt + timedelta(minutes=interval)
    reminder_dt = next_dt - timedelta(minutes=lead)
    return {
        "last_feed_utc": to_iso_utc(last_dt),
        "next_feed_utc": to_iso_utc(next_dt),
        "reminder_at_utc": to_iso_utc(reminder_dt),
        "interval_min": interval, "lead_min": lead,
        "notifications_on": bool(settings["notifications_on"]),
    }


def find_users_due_for_reminder(now=None, window_min=2):
    now = now or now_utc()
    window_start = now - timedelta(minutes=window_min)
    out = []
    with get_conn() as conn:
        users = conn.execute("SELECT id FROM users").fetchall()
    for u in users:
        state = compute_reminder_state(u["id"])
        if not state["notifications_on"] or not state["reminder_at_utc"]:
            continue
        reminder_dt = from_iso_utc(state["reminder_at_utc"])
        if not (window_start <= reminder_dt <= now):
            continue
        last_feed = state["last_feed_utc"]
        with get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO reminder_log (user_id, last_feed_time) VALUES (?, ?)",
                    (u["id"], last_feed),
                )
            except sqlite3.IntegrityError:
                continue
        out.append({"user_id": u["id"], **state})
    return out
