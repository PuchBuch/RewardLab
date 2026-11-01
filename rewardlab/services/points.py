"""Начисление и списание баллов, уведомления, удаление аккаунта."""

from ..db import db, now_iso


def add_points(uid: int, amount: int, kind: str, source: int | None = None) -> None:
    db().execute("UPDATE users SET points = points + ? WHERE id = ?", (amount, uid))
    db().execute("INSERT INTO events (user_id, kind, amount, at, source_id) VALUES (?, ?, ?, ?, ?)",
                 (uid, kind, amount, now_iso(), source))


def spend_points(uid: int, amount: int, kind: str) -> bool:
    """Атомарно списать баллы, только если их хватает."""
    cur = db().execute("UPDATE users SET points = points - ? WHERE id = ? AND points >= ?", (amount, uid, amount))
    if cur.rowcount != 1:
        return False
    db().execute("INSERT INTO events (user_id, kind, amount, at) VALUES (?, ?, ?, ?)",
                 (uid, kind, -amount, now_iso()))
    return True


def notify(uid: int, text: str) -> None:
    db().execute("INSERT INTO notifications (user_id, text, at) VALUES (?, ?, ?)", (uid, text, now_iso()))


def delete_user(uid: int) -> None:
    d = db()
    d.execute("UPDATE users SET referred_by = NULL WHERE referred_by = ?", (uid,))
    d.execute("UPDATE events SET source_id = NULL WHERE source_id = ?", (uid,))
    for table in ("events", "quiz_done", "notifications", "contest_results", "bj_games"):
        d.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
    d.execute("DELETE FROM users WHERE id = ?", (uid,))
