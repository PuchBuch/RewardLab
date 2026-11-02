"""Community-сервис: реферальная программа, уведомления, недельный конкурс и рейтинг пригласивших."""

import datetime

from flask import request

from common import client
from common.client import ServiceError
from common.service import create_service, payload, need_int
from common.store import db, write, rows, ids_arg, utc_now, now_iso
from common.serve import run

from . import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS referrals (
    friend_id    INTEGER PRIMARY KEY,          -- у каждого не больше одного пригласившего
    inviter_id   INTEGER NOT NULL,
    claims       INTEGER NOT NULL DEFAULT 0,   -- сколько ежечасных наград получил друг
    activated    INTEGER NOT NULL DEFAULT 0,
    activated_at TEXT,
    created      TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS referrals_inviter ON referrals (inviter_id);
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
"""


def active_referrals(uid: int) -> int:
    return db().execute("SELECT COUNT(*) FROM referrals WHERE inviter_id = ? AND activated = 1", (uid,)).fetchone()[0]


def ref_tier(active: int):
    """Текущий уровень и следующий (или None, если уровень максимальный)."""
    idx = max(i for i, t in enumerate(settings.REF_TIERS) if active >= t[0])
    nxt = settings.REF_TIERS[idx + 1] if idx + 1 < len(settings.REF_TIERS) else None
    return settings.REF_TIERS[idx], nxt


def notify(uid: int, text: str) -> None:
    db().execute("INSERT INTO notifications (user_id, text, at) VALUES (?, ?, ?)", (uid, text, now_iso()))


def week_start(dt: datetime.datetime) -> datetime.datetime:
    d = dt.date() - datetime.timedelta(days=dt.weekday())
    return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)


def standings(start: datetime.datetime, limit: int = 20) -> list[dict]:
    """Кто больше всех привёл активных друзей за неделю. При равенстве выше тот, кто успел раньше."""
    end = start + datetime.timedelta(days=7)
    return rows(db().execute(
        "SELECT inviter_id AS user_id, COUNT(*) AS value, MAX(activated_at) AS last FROM referrals "
        "WHERE activated = 1 AND activated_at >= ? AND activated_at < ? "
        "GROUP BY inviter_id ORDER BY value DESC, last ASC LIMIT ?",
        (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), limit)))


def create_app(overrides: dict | None = None):
    app = create_service("community", SCHEMA, overrides)
    settled = {"week": None}

    def credit(uid, amount, kind, op_id, source=None) -> None:
        client.post("wallet", "/credit", {"uid": uid, "amount": amount, "kind": kind, "op_id": op_id, "source": source})

    @app.before_request
    def settle():
        """Раз в неделю выдать призы за прошлую неделю. Начисления идемпотентны (op_id),
        поэтому при сбое wallet неделя просто будет закрыта при следующем запросе."""
        if request.path == "/health":
            return
        prev = week_start(utc_now()) - datetime.timedelta(days=7)
        key  = prev.date().isoformat()
        if settled["week"] == key:
            return
        if db().execute("SELECT 1 FROM contest_weeks WHERE week = ?", (key,)).fetchone() is None:
            winners = standings(prev, len(settings.CONTEST_PRIZES))
            try:
                for place, row in enumerate(winners):
                    credit(row["user_id"], settings.CONTEST_PRIZES[place], "contest", f"contest:{key}:{place + 1}")
            except ServiceError as e:
                app.logger.warning("contest %s not settled yet: %s", key, e)
                return
            con = write()
            if con.execute("INSERT OR IGNORE INTO contest_weeks (week, settled_at) VALUES (?, ?)",
                           (key, now_iso())).rowcount == 1:
                for place, row in enumerate(winners):
                    amount = settings.CONTEST_PRIZES[place]
                    con.execute("INSERT INTO contest_results (week, place, user_id, amount) VALUES (?, ?, ?, ?)",
                                (key, place + 1, row["user_id"], amount))
                    notify(row["user_id"], f"🏆 You took place #{place + 1} in last week's invite contest: +{amount} points!")
            con.commit()
        settled["week"] = key

    @app.get("/info")
    def info():
        return {"tiers": settings.REF_TIERS, "activation_claims": settings.REF_ACTIVATION_CLAIMS,
                "bonus_inviter": settings.REF_BONUS_INVITER, "bonus_friend": settings.REF_BONUS_FRIEND,
                "prizes": settings.CONTEST_PRIZES}

    # ─── Реферальная программа ─────────────────────────────────
    @app.post("/referrals")
    def link():
        d = payload()
        friend, inviter = need_int(d, "friend_id"), need_int(d, "inviter_id")
        if friend == inviter:
            return {"ok": False}
        con = write()
        if con.execute("INSERT OR IGNORE INTO referrals (friend_id, inviter_id, created) VALUES (?, ?, ?)",
                       (friend, inviter, now_iso())).rowcount == 1:
            notify(inviter, f"👋 {str(d.get('friend_name', 'A friend'))[:20]} joined with your invite. They become "
                            f"active after {settings.REF_ACTIVATION_CLAIMS} hourly claims.")
        con.commit()
        return {"ok": True}

    @app.post("/earnings")
    def earnings():
        """Друг что-то заработал: доля пригласившему, а после N-й награды — разовые бонусы обоим."""
        d      = payload()
        uid    = need_int(d, "uid")
        amount = need_int(d, "amount")
        kind   = str(d.get("kind", ""))
        con = write()
        r = con.execute("SELECT * FROM referrals WHERE friend_id = ?", (uid,)).fetchone()
        if r is None:
            con.rollback()
            return {"activated": False, "welcome": 0}
        inviter  = r["inviter_id"]
        old_tier = ref_tier(active_referrals(inviter))[0]
        share    = max(1, round(amount * old_tier[1]))
        claims   = r["claims"] + (kind == "claim")
        activate = not r["activated"] and claims >= settings.REF_ACTIVATION_CLAIMS
        con.execute("UPDATE referrals SET claims = ?, activated = MAX(activated, ?), "
                    "activated_at = COALESCE(activated_at, ?) WHERE friend_id = ?",
                    (claims, int(activate), now_iso() if activate else None, uid))
        con.commit()

        credit(inviter, share, "referral", None, source=uid)
        if not activate:
            return {"activated": False, "welcome": 0}
        try:
            credit(inviter, settings.REF_BONUS_INVITER, "ref_bonus", f"ref_bonus:{uid}", source=uid)
            credit(uid, settings.REF_BONUS_FRIEND, "welcome_bonus", f"welcome:{uid}")
        except ServiceError:
            # Бонусы не дошли: активация повторится со следующей наградой, op_id не даст выплатить дважды
            db().execute("UPDATE referrals SET activated = 0, activated_at = NULL WHERE friend_id = ?", (uid,))
            db().commit()
            raise
        try:
            name = client.get("auth", f"/users/{uid}")["username"]
        except ServiceError:
            name = "Your friend"
        notify(inviter, f"🎉 {name} is now an active friend: +{settings.REF_BONUS_INVITER} points!")
        new_tier = ref_tier(active_referrals(inviter))[0]
        if new_tier != old_tier:
            notify(inviter, f"⬆️ Level up! You are now {new_tier[2]}: "
                            f"{int(new_tier[1] * 100)}% of your friends' earnings.")
        db().commit()
        return {"activated": True, "welcome": settings.REF_BONUS_FRIEND}

    @app.get("/referrals/<int:uid>")
    def summary(uid):
        active = active_referrals(uid)
        tier, nxt = ref_tier(active)
        friends = rows(db().execute("SELECT friend_id AS user_id, claims, activated FROM referrals "
                                    "WHERE inviter_id = ? ORDER BY created DESC", (uid,)))
        inviter = db().execute("SELECT inviter_id FROM referrals WHERE friend_id = ?", (uid,)).fetchone()
        return {"active": active, "invited": len(friends), "tier": tier, "next": nxt, "friends": friends,
                "inviter_id": inviter[0] if inviter else None}

    @app.get("/referrals/counts")
    def counts():
        ids = ids_arg()
        out = {str(i): {"invited": 0, "active": 0} for i in ids}
        if ids:
            marks = ",".join("?" * len(ids))
            for r in db().execute(f"SELECT inviter_id, COUNT(*), SUM(activated) FROM referrals "
                                  f"WHERE inviter_id IN ({marks}) GROUP BY inviter_id", ids):
                out[str(r[0])] = {"invited": r[1], "active": r[2]}
        return {"counts": out}

    @app.post("/referrals/<int:uid>/unlink")
    def unlink(uid):
        db().execute("DELETE FROM referrals WHERE friend_id = ?", (uid,))
        db().commit()
        return {"ok": True}

    # ─── Уведомления ───────────────────────────────────────────
    @app.post("/notify")
    def add_note():
        d = payload()
        notify(need_int(d, "uid"), str(d.get("text", ""))[:300])
        db().commit()
        return {"ok": True}

    @app.get("/notifications/<int:uid>")
    def notes(uid):
        limit = min(request.args.get("limit", 5, type=int), 50)
        items = rows(db().execute("SELECT text, at, seen FROM notifications WHERE user_id = ? "
                                  "ORDER BY id DESC LIMIT ?", (uid, limit)))
        return {"items": items}

    @app.post("/notifications/<int:uid>/seen")
    def seen(uid):
        db().execute("UPDATE notifications SET seen = 1 WHERE user_id = ? AND seen = 0", (uid,))
        db().commit()
        return {"ok": True}

    @app.get("/unread/<int:uid>")
    def unread(uid):
        return {"count": db().execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND seen = 0",
                                      (uid,)).fetchone()[0]}

    # ─── Рейтинги ──────────────────────────────────────────────
    @app.get("/leaderboard/inviters")
    def inviters():
        return {"rows": rows(db().execute(
            "SELECT inviter_id AS user_id, COUNT(*) AS value FROM referrals WHERE activated = 1 "
            "GROUP BY inviter_id ORDER BY value DESC, inviter_id LIMIT 20"))}

    @app.get("/contest")
    def contest():
        start = week_start(utc_now())
        left  = start + datetime.timedelta(days=7) - utc_now()
        last  = rows(db().execute("SELECT place, user_id, amount FROM contest_results WHERE week = ? ORDER BY place",
                                  ((start - datetime.timedelta(days=7)).date().isoformat(),)))
        return {"rows": standings(start), "left_d": left.days, "left_h": left.seconds // 3600, "last": last}

    @app.delete("/users/<int:uid>")
    def delete(uid):
        con = write()
        con.execute("DELETE FROM referrals WHERE friend_id = ? OR inviter_id = ?", (uid, uid))
        for table in ("notifications", "contest_results"):
            con.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
        con.commit()
        return {"ok": True}

    return app


if __name__ == "__main__":
    run(create_app(), "community")
