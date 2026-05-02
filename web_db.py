"""
web_db.py - SQLite layer for the Baby Tracker web app.

Multi-user version: every entry is scoped by user_id, so each family's
data is isolated. Passwords are hashed with werkzeug's PBKDF2.

DB location: env var BABY_TRACKER_DB or ./baby_tracker.db
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.environ.get(
    "BABY_TRACKER_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "baby_tracker.db"),
)

ISO_FMT = "%Y-%m-%d %H:%M:%S"


# ---------- connection ----------

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


# ---------- schema ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
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

CREATE INDEX IF NOT EXISTS idx_sleep_user_start
    ON sleep_sessions (user_id, start_time);
CREATE INDEX IF NOT EXISTS idx_feed_user_time
    ON feeds (user_id, feed_time);
CREATE INDEX IF NOT EXISTS idx_diaper_user_time
    ON diaper_changes (user_id, change_time);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- datetime helpers ----------

def now_iso() -> str:
    return datetime.now().strftime(ISO_FMT)


def to_iso(dt: datetime) -> str:
    return dt.strftime(ISO_FMT)


def from_iso(s: str) -> datetime:
    return datetime.strptime(s, ISO_FMT)


# ===========================================================
# Users / auth
# ===========================================================

def create_user(email: str, password: str,
                display_name: str = "") -> int:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 5:
        raise ValueError("Please enter a valid email address.")
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    pw_hash = generate_password_hash(password)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, display_name, password_hash) "
                "VALUES (?, ?, ?)",
                (email, display_name.strip() or None, pw_hash),
            )
        except sqlite3.IntegrityError:
            raise ValueError("That email is already registered.")
        return cur.lastrowid


def authenticate(email: str, password: str) -> Optional[sqlite3.Row]:
    email = (email or "").strip().lower()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    if row and check_password_hash(row["password_hash"], password):
        return row
    return None


def get_user(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


# ===========================================================
# Sleep
# ===========================================================

def start_sleep(user_id: int, location: str,
                start_time: Optional[str] = None,
                notes: str = "") -> int:
    if not location:
        raise ValueError("Sleep location is required.")
    start_time = start_time or now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sleep_sessions (user_id, location, start_time, notes) "
            "VALUES (?, ?, ?, ?)",
            (user_id, location, start_time, notes),
        )
        return cur.lastrowid


def stop_sleep(user_id: int, session_id: int,
               end_time: Optional[str] = None) -> float:
    end_time = end_time or now_iso()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT start_time FROM sleep_sessions "
            "WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError("Sleep session not found.")
        duration_min = max(
            0.0,
            (from_iso(end_time) - from_iso(row["start_time"])).total_seconds() / 60.0,
        )
        conn.execute(
            "UPDATE sleep_sessions SET end_time = ?, duration_minutes = ? "
            "WHERE id = ? AND user_id = ?",
            (end_time, duration_min, session_id, user_id),
        )
        return duration_min


def add_completed_sleep(user_id: int, location: str,
                        start_time: str, end_time: str,
                        notes: str = "") -> int:
    start = from_iso(start_time)
    end = from_iso(end_time)
    if end < start:
        raise ValueError("End time must be after start time.")
    duration_min = (end - start).total_seconds() / 60.0
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sleep_sessions "
            "(user_id, location, start_time, end_time, duration_minutes, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, location, start_time, end_time, duration_min, notes),
        )
        return cur.lastrowid


def get_open_sleep_session(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sleep_sessions "
            "WHERE user_id = ? AND end_time IS NULL "
            "ORDER BY start_time DESC LIMIT 1",
            (user_id,),
        ).fetchone()


def list_sleep(user_id: int, limit: int = 200) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM sleep_sessions WHERE user_id = ? "
            "ORDER BY start_time DESC LIMIT ?",
            (user_id, limit),
        ).fetchall())


# ===========================================================
# Feeds
# ===========================================================

def add_feed(user_id: int, feed_type: str,
             amount_ml: Optional[float] = None,
             duration_minutes: Optional[float] = None,
             side: Optional[str] = None,
             feed_time: Optional[str] = None,
             notes: str = "") -> int:
    feed_type = (feed_type or "").lower().strip()
    if feed_type not in {"bottle", "breast", "formula"}:
        raise ValueError("Feed type must be bottle, breast, or formula.")
    if side:
        side = side.lower().strip() or None
        if side and side not in {"left", "right", "both"}:
            raise ValueError("Side must be left, right, or both.")
    feed_time = feed_time or now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO feeds (user_id, feed_time, feed_type, amount_ml, "
            "duration_minutes, side, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, feed_time, feed_type, amount_ml,
             duration_minutes, side, notes),
        )
        return cur.lastrowid


def list_feeds(user_id: int, limit: int = 200) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM feeds WHERE user_id = ? "
            "ORDER BY feed_time DESC LIMIT ?",
            (user_id, limit),
        ).fetchall())


# ===========================================================
# Diapers
# ===========================================================

def add_diaper(user_id: int, diaper_type: str,
               change_time: Optional[str] = None,
               notes: str = "") -> int:
    diaper_type = (diaper_type or "").lower().strip()
    if diaper_type not in {"wet", "dirty", "both"}:
        raise ValueError("Diaper type must be wet, dirty, or both.")
    change_time = change_time or now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO diaper_changes (user_id, change_time, diaper_type, notes) "
            "VALUES (?, ?, ?, ?)",
            (user_id, change_time, diaper_type, notes),
        )
        return cur.lastrowid


def list_diapers(user_id: int, limit: int = 200) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT * FROM diaper_changes WHERE user_id = ? "
            "ORDER BY change_time DESC LIMIT ?",
            (user_id, limit),
        ).fetchall())


# ===========================================================
# Delete (with user_id check so people can't delete each other's data)
# ===========================================================

_TABLES = {
    "sleep": "sleep_sessions",
    "feed": "feeds",
    "diaper": "diaper_changes",
}


def delete_entry(user_id: int, kind: str, entry_id: int) -> None:
    table = _TABLES.get(kind)
    if not table:
        raise ValueError(f"Unknown entry kind: {kind}")
    with get_conn() as conn:
        conn.execute(
            f"DELETE FROM {table} WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        )


# ===========================================================
# Daily summary
# ===========================================================

def daily_summary(user_id: int, day: Optional[datetime] = None) -> dict:
    day = day or datetime.now()
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    s_iso, e_iso = to_iso(start), to_iso(end)

    with get_conn() as conn:
        sleep_row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(duration_minutes), 0) AS mins "
            "FROM sleep_sessions WHERE user_id = ? "
            "AND start_time >= ? AND start_time < ? "
            "AND end_time IS NOT NULL",
            (user_id, s_iso, e_iso),
        ).fetchone()

        feed_row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_ml), 0) AS ml "
            "FROM feeds WHERE user_id = ? "
            "AND feed_time >= ? AND feed_time < ?",
            (user_id, s_iso, e_iso),
        ).fetchone()

        feed_breakdown = conn.execute(
            "SELECT feed_type, COUNT(*) AS n FROM feeds WHERE user_id = ? "
            "AND feed_time >= ? AND feed_time < ? GROUP BY feed_type",
            (user_id, s_iso, e_iso),
        ).fetchall()

        diaper_row = conn.execute(
            "SELECT COUNT(*) AS n FROM diaper_changes WHERE user_id = ? "
            "AND change_time >= ? AND change_time < ?",
            (user_id, s_iso, e_iso),
        ).fetchone()

        diaper_breakdown = conn.execute(
            "SELECT diaper_type, COUNT(*) AS n FROM diaper_changes "
            "WHERE user_id = ? AND change_time >= ? AND change_time < ? "
            "GROUP BY diaper_type",
            (user_id, s_iso, e_iso),
        ).fetchall()

    return {
        "date": start.strftime("%Y-%m-%d"),
        "sleep_count": sleep_row["n"],
        "sleep_minutes": float(sleep_row["mins"] or 0),
        "feed_count": feed_row["n"],
        "feed_total_ml": float(feed_row["ml"] or 0),
        "feed_breakdown": {r["feed_type"]: r["n"] for r in feed_breakdown},
        "diaper_count": diaper_row["n"],
        "diaper_breakdown": {r["diaper_type"]: r["n"] for r in diaper_breakdown},
    }


# ===========================================================
# CSV export (returns bytes for download)
# ===========================================================

_EXPORT_QUERIES = {
    "sleep_sessions": (
        "SELECT id, location, start_time, end_time, duration_minutes, notes "
        "FROM sleep_sessions WHERE user_id = ? ORDER BY start_time",
        ["id", "location", "start_time", "end_time", "duration_minutes", "notes"],
    ),
    "feeds": (
        "SELECT id, feed_time, feed_type, amount_ml, duration_minutes, "
        "side, notes FROM feeds WHERE user_id = ? ORDER BY feed_time",
        ["id", "feed_time", "feed_type", "amount_ml",
         "duration_minutes", "side", "notes"],
    ),
    "diaper_changes": (
        "SELECT id, change_time, diaper_type, notes "
        "FROM diaper_changes WHERE user_id = ? ORDER BY change_time",
        ["id", "change_time", "diaper_type", "notes"],
    ),
}


def export_table_csv(user_id: int, table: str) -> bytes:
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
