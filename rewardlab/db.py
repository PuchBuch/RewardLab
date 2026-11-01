"""SQLite: подключение на время запроса, схема и миграции."""

import sqlite3
import datetime

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash       TEXT NOT NULL,
    points        INTEGER NOT NULL DEFAULT 0,
    streak        INTEGER NOT NULL DEFAULT 0,
    last_day      TEXT,
    last_claim_at REAL,
    ref_code      TEXT NOT NULL UNIQUE,
    referred_by   INTEGER,
    created       TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind    TEXT NOT NULL,
    amount  INTEGER NOT NULL,
    at      TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quiz_done (
    user_id INTEGER NOT NULL,
    day     TEXT NOT NULL,
    PRIMARY KEY (user_id, day));
CREATE TABLE IF NOT EXISTS notifications (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text    TEXT NOT NULL,
    at      TEXT NOT NULL,
    seen    INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS contest_weeks (
    week       TEXT PRIMARY KEY,
    settled_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contest_results (
    week    TEXT NOT NULL,
    place   INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    amount  INTEGER NOT NULL,
    PRIMARY KEY (week, place));
CREATE TABLE IF NOT EXISTS bj_games (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    bet     INTEGER NOT NULL,
    shoe    TEXT NOT NULL,
    player  TEXT NOT NULL,
    dealer  TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'playing',
    result  TEXT,
    payout  INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL);
-- не больше одной незавершённой раздачи на пользователя
CREATE UNIQUE INDEX IF NOT EXISTS bj_one_active ON bj_games (user_id) WHERE status = 'playing';
CREATE TABLE IF NOT EXISTS admin_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id   INTEGER NOT NULL,
    admin_name TEXT NOT NULL,
    action     TEXT NOT NULL,
    target     TEXT,
    details    TEXT,
    at         TEXT NOT NULL);
"""

# Колонки, добавленные после первой версии: (таблица, колонка, определение)
MIGRATIONS = [
    ("users",  "ref_activated", "INTEGER NOT NULL DEFAULT 0"),
    ("users",  "reg_net",       "TEXT"),                         # хеш IP при регистрации
    ("users",  "is_admin",      "INTEGER NOT NULL DEFAULT 0"),
    ("users",  "banned",        "INTEGER NOT NULL DEFAULT 0"),
    ("users",  "totp_secret",   "TEXT"),
    ("users",  "totp_last",     "INTEGER NOT NULL DEFAULT 0"),   # последний использованный шаг TOTP
    ("events", "source_id",     "INTEGER"),                      # от какого друга
]


def db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for table, col, ddl in MIGRATIONS:
        if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.commit()
    conn.close()


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    init_db(app.config["DATABASE"])
