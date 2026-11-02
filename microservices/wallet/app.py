"""Wallet-сервис: балансы и журнал операций.
Все изменения баланса идут только через /credit и /debit. Операции с op_id идемпотентны:
повтор того же запроса (например, после таймаута) не начислит баллы дважды."""

from flask import request

from common.service import create_service, error, payload, need_int
from common.store import db, write, rows, ids_arg, utc_now, now_iso
from common.serve import run

SCHEMA = """
CREATE TABLE IF NOT EXISTS balances (
    user_id INTEGER PRIMARY KEY,
    points  INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0));
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    kind      TEXT NOT NULL,
    amount    INTEGER NOT NULL,
    at        TEXT NOT NULL,
    source_id INTEGER,                 -- от какого друга (реферальные начисления)
    op_id     TEXT UNIQUE);            -- ключ идемпотентности
CREATE INDEX IF NOT EXISTS events_user ON events (user_id, id);
CREATE INDEX IF NOT EXISTS events_kind ON events (kind, at);
"""
REF_KINDS = ("referral", "ref_bonus")


def create_app(overrides: dict | None = None):
    app = create_service("wallet", SCHEMA, overrides)

    def points(uid: int) -> int:
        row = db().execute("SELECT points FROM balances WHERE user_id = ?", (uid,)).fetchone()
        return row[0] if row else 0

    def op_done(op_id) -> bool:
        return bool(op_id) and db().execute("SELECT 1 FROM events WHERE op_id = ?", (op_id,)).fetchone() is not None

    def record(uid, kind, amount, source=None, op_id=None) -> None:
        db().execute("INSERT INTO events (user_id, kind, amount, at, source_id, op_id) VALUES (?, ?, ?, ?, ?, ?)",
                     (uid, kind, amount, now_iso(), source, op_id))

    @app.post("/accounts")
    def open_account():
        db().execute("INSERT OR IGNORE INTO balances (user_id) VALUES (?)", (need_int(payload(), "uid"),))
        db().commit()
        return {"ok": True}

    @app.post("/credit")
    def credit():
        """Начислить (или списать отрицательной суммой, но не ниже нуля — для админа)."""
        d      = payload()
        uid    = need_int(d, "uid")
        amount = need_int(d, "amount")
        kind   = str(d.get("kind", ""))[:30]
        op_id  = d.get("op_id")
        source = d.get("source")
        if not kind or amount == 0:
            return error("Need a kind and a non-zero amount.")
        con = write()
        if op_done(op_id):
            con.rollback()
            return {"points": points(uid), "amount": 0, "duplicate": True}
        con.execute("INSERT OR IGNORE INTO balances (user_id) VALUES (?)", (uid,))
        amount = max(amount, -points(uid))           # баланс не уходит в минус
        if amount:
            con.execute("UPDATE balances SET points = points + ? WHERE user_id = ?", (amount, uid))
            record(uid, kind, amount, source, op_id)
        con.commit()
        return {"points": points(uid), "amount": amount}

    @app.post("/debit")
    def debit():
        """Списать, только если баллов хватает. Иначе 409."""
        d      = payload()
        uid    = need_int(d, "uid")
        amount = need_int(d, "amount")
        kind   = str(d.get("kind", ""))[:30]
        op_id  = d.get("op_id")
        if not kind or amount <= 0:
            return error("Need a kind and a positive amount.")
        con = write()
        if op_done(op_id):
            con.rollback()
            return {"points": points(uid), "duplicate": True}
        cur = con.execute("UPDATE balances SET points = points - ? WHERE user_id = ? AND points >= ?", (amount, uid, amount))
        if cur.rowcount != 1:
            con.rollback()
            return error("Not enough points.", 409)
        record(uid, kind, -amount, op_id=op_id)
        con.commit()
        return {"points": points(uid)}

    @app.get("/balance/<int:uid>")
    def balance(uid):
        return {"points": points(uid)}

    @app.get("/balances")
    def balances():
        ids = ids_arg()
        if not ids:
            return {"points": {}}
        marks = ",".join("?" * len(ids))
        return {"points": {str(r[0]): r[1] for r in
                           db().execute(f"SELECT user_id, points FROM balances WHERE user_id IN ({marks})", ids)}}

    @app.get("/events/<int:uid>")
    def events(uid):
        limit = min(request.args.get("limit", 10, type=int), 100)
        return {"events": rows(db().execute("SELECT kind, amount, at FROM events WHERE user_id = ? "
                                            "ORDER BY id DESC LIMIT ?", (uid, limit)))}

    @app.get("/top")
    def top():
        limit = min(request.args.get("limit", 20, type=int), 100)
        return {"top": rows(db().execute("SELECT user_id, points FROM balances "
                                         "ORDER BY points DESC, user_id LIMIT ?", (limit,)))}

    @app.get("/earned/<int:uid>")
    def earned(uid):
        """Сколько пользователь получил от друзей: всего и по каждому другу."""
        marks = ",".join("?" * len(REF_KINDS))
        total = db().execute(f"SELECT COALESCE(SUM(amount), 0) FROM events WHERE user_id = ? AND kind IN ({marks})",
                             (uid, *REF_KINDS)).fetchone()[0]
        by_source = {str(r[0]): r[1] for r in db().execute(
            "SELECT source_id, SUM(amount) FROM events WHERE user_id = ? AND source_id IS NOT NULL GROUP BY source_id",
            (uid,))}
        return {"total": total, "by_source": by_source}

    @app.get("/stats")
    def stats():
        d     = db()
        today = utc_now().date().isoformat()
        return {
            "claims":       d.execute("SELECT COUNT(*) FROM events WHERE kind = 'claim'").fetchone()[0],
            "claims_today": d.execute("SELECT COUNT(*) FROM events WHERE kind = 'claim' AND at >= ?", (today,)).fetchone()[0],
            "awarded":      d.execute("SELECT COALESCE(SUM(amount), 0) FROM events WHERE amount > 0").fetchone()[0],
            "points":       d.execute("SELECT COALESCE(SUM(points), 0) FROM balances").fetchone()[0],
        }

    @app.delete("/users/<int:uid>")
    def delete(uid):
        con = write()
        con.execute("UPDATE events SET source_id = NULL WHERE source_id = ?", (uid,))
        con.execute("DELETE FROM events WHERE user_id = ?", (uid,))
        con.execute("DELETE FROM balances WHERE user_id = ?", (uid,))
        con.commit()
        return {"ok": True}

    return app


if __name__ == "__main__":
    run(create_app(), "wallet")
