"""SQLite: у каждого сервиса своя база, подключение на время запроса."""

import os
import sqlite3
import datetime

from flask import current_app, g, request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # папка microservices/


def db_path(name: str) -> str:
    return os.path.join(os.getenv("DATA_DIR") or os.path.join(ROOT, "data"), f"{name}.db")


def init_app(app, schema: str) -> None:
    path = app.config["DATABASE"]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(schema)
    conn.commit()
    conn.close()
    app.teardown_appcontext(close_db)


def db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def write() -> sqlite3.Connection:
    """Начать транзакцию записи сразу: параллельные изменения выполняются по очереди."""
    con = db()
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    return con


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur]


def ids_arg(limit: int = 200) -> list[int]:
    """Список id из параметра ?ids=1,2,3."""
    return [int(x) for x in request.args.get("ids", "").split(",") if x.isdigit()][:limit]


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")
