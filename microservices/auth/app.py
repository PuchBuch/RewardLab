"""Auth-сервис: учётные записи, пароли, баны, вход в админку по TOTP, журнал действий админов."""

import re
import secrets
import sqlite3
import datetime

from flask import request, abort
from werkzeug.security import generate_password_hash, check_password_hash

from common.service import create_service, error, payload, need_int
from common.store import db, write, rows, ids_arg, utc_now, now_iso
from common.serve import run

from . import settings, totp

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash     TEXT NOT NULL,
    ref_code    TEXT NOT NULL UNIQUE,
    reg_net     TEXT,                              -- хеш IP при регистрации
    is_admin    INTEGER NOT NULL DEFAULT 0,
    banned      INTEGER NOT NULL DEFAULT 0,
    totp_secret TEXT,
    totp_last   INTEGER NOT NULL DEFAULT 0,        -- последний использованный шаг TOTP
    created     TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admin_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id   INTEGER NOT NULL,
    admin_name TEXT NOT NULL,
    action     TEXT NOT NULL,
    target     TEXT,
    details    TEXT,
    at         TEXT NOT NULL);
"""
PUBLIC = "id, username, ref_code, is_admin, banned, created, totp_secret IS NOT NULL AS has_totp"


def create_app(overrides: dict | None = None):
    app = create_service("auth", SCHEMA, overrides)

    def find(uid: int) -> sqlite3.Row:
        row = db().execute(f"SELECT {PUBLIC}, reg_net FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None:
            abort(404, "User not found.")
        return row

    def log(admin_id: int, action: str, target: str | None = None, details: str = "") -> None:
        name = db().execute("SELECT username FROM users WHERE id = ?", (admin_id,)).fetchone()
        db().execute("INSERT INTO admin_log (admin_id, admin_name, action, target, details, at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (admin_id, name[0] if name else f"#{admin_id}", action, target, details, now_iso()))

    @app.get("/info")
    def info():
        return {"per_net": settings.REG_PER_NETWORK_DAY}

    @app.get("/stats")
    def stats():
        return {"users": db().execute("SELECT COUNT(*) FROM users").fetchone()[0]}

    @app.post("/register")
    def register():
        d        = payload()
        username = str(d.get("username", "")).strip()
        password = str(d.get("password", ""))
        net      = d.get("net") or None
        ref      = str(d.get("ref") or "")[:30]
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            return error("Username: 3–20 letters, digits or underscore.")
        if not 8 <= len(password) <= 128:
            return error("Password must be 8–128 characters.")
        con = write()
        day_ago = (utc_now() - datetime.timedelta(days=1)).isoformat(timespec="seconds")
        if net and con.execute("SELECT COUNT(*) FROM users WHERE reg_net = ? AND created >= ?",
                               (net, day_ago)).fetchone()[0] >= settings.REG_PER_NETWORK_DAY:
            con.rollback()
            return error("Too many accounts were created from your network today. Please try again tomorrow.", 429)
        referrer = con.execute("SELECT id, reg_net FROM users WHERE ref_code = ?", (ref,)).fetchone() if ref else None
        same_net = net is not None and referrer is not None and referrer["reg_net"] == net
        try:
            cur = con.execute("INSERT INTO users (username, pw_hash, ref_code, reg_net, created) VALUES (?, ?, ?, ?, ?)",
                              (username, generate_password_hash(password), secrets.token_urlsafe(6), net, now_iso()))
        except sqlite3.IntegrityError:
            con.rollback()
            return error("That username is taken.", 409)
        con.commit()
        return {"id": cur.lastrowid, "username": username,
                "inviter_id": referrer["id"] if referrer and not same_net else None,
                "ref_ignored": same_net}, 201

    @app.post("/login")
    def login():
        d   = payload()
        row = db().execute("SELECT * FROM users WHERE username = ?", (str(d.get("username", "")).strip(),)).fetchone()
        if row is None or not check_password_hash(row["pw_hash"], str(d.get("password", ""))):
            return error("Invalid username or password.", 401)
        if row["banned"]:
            return error("This account has been suspended for breaking the rules.", 403)
        return {"id": row["id"]}

    @app.get("/users/<int:uid>")
    def user(uid):
        row = dict(find(uid))
        row.pop("reg_net")
        return row

    @app.get("/users")
    def names():
        ids = ids_arg()
        if not ids:
            return {"names": {}}
        marks = ",".join("?" * len(ids))
        return {"names": {str(r["id"]): r["username"]
                          for r in db().execute(f"SELECT id, username FROM users WHERE id IN ({marks})", ids)}}

    @app.delete("/users/<int:uid>")
    def delete(uid):
        db().execute("DELETE FROM users WHERE id = ?", (uid,))
        db().commit()
        return {"ok": True}

    # ─── Админка ───────────────────────────────────────────────
    @app.post("/admin/verify")
    def verify():
        d   = payload()
        uid = need_int(d, "uid")
        u   = db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if u is None or not u["is_admin"] or not u["totp_secret"]:
            abort(404, "Not an admin.")
        step = (totp.check(u["totp_secret"], str(d.get("code", "")).strip(), u["totp_last"])
                if check_password_hash(u["pw_hash"], str(d.get("password", ""))) else None)
        con = write()
        if step is None:
            log(uid, "failed_verification")
            con.commit()
            return error("Invalid password or code.", 401)
        # код одноразовый: шаг сохраняется, только если он новее прошлого
        if con.execute("UPDATE users SET totp_last = ? WHERE id = ? AND totp_last < ?", (step, uid, step)).rowcount != 1:
            con.rollback()
            return error("Invalid password or code.", 401)
        log(uid, "signed_in")
        con.commit()
        return {"ok": True}

    @app.post("/admin/log")
    def add_log():
        d = payload()
        log(need_int(d, "admin_id"), str(d.get("action", ""))[:50], d.get("target"), str(d.get("details", ""))[:300])
        db().commit()
        return {"ok": True}

    @app.get("/admin/overview")
    def overview():
        d       = db()
        day_ago = (utc_now() - datetime.timedelta(days=1)).isoformat(timespec="seconds")
        q       = request.args.get("q", "").strip()[:20]
        return {
            "stats": {
                "users":  d.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "new":    d.execute("SELECT COUNT(*) FROM users WHERE created >= ?", (day_ago,)).fetchone()[0],
                "banned": d.execute("SELECT COUNT(*) FROM users WHERE banned = 1").fetchone()[0],
            },
            "members": rows(d.execute(
                "SELECT id, username, created, banned, is_admin FROM users WHERE username LIKE ? ESCAPE '\\' "
                "ORDER BY id DESC LIMIT 50", ("%" + re.sub(r"([%_\\])", r"\\\1", q) + "%",))),
            "nets": rows(d.execute(
                "SELECT reg_net, COUNT(*) AS n, GROUP_CONCAT(username) AS names FROM users "
                "WHERE reg_net IS NOT NULL GROUP BY reg_net HAVING n > 1 ORDER BY n DESC LIMIT 10")),
            "log": rows(d.execute("SELECT * FROM admin_log ORDER BY id DESC LIMIT 25")),
        }

    @app.get("/admin/users/<int:uid>")
    def admin_user(uid):
        t = dict(find(uid))
        same_net = (db().execute("SELECT COUNT(*) FROM users WHERE reg_net = ? AND id != ?",
                                 (t["reg_net"], uid)).fetchone()[0] if t["reg_net"] else 0)
        log_rows = rows(db().execute("SELECT * FROM admin_log WHERE target = ? ORDER BY id DESC LIMIT 15",
                                     (t["username"],)))
        t.pop("reg_net")
        return {"user": t, "same_net": same_net, "log": log_rows}

    @app.post("/admin/users/<int:uid>/ban")
    def ban(uid):
        find(uid)
        db().execute("UPDATE users SET banned = ? WHERE id = ? AND is_admin = 0", (int(bool(payload().get("banned"))), uid))
        db().commit()
        return {"ok": True}

    return app


if __name__ == "__main__":
    run(create_app(), "auth")
