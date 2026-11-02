"""Games-сервис: ежечасное «счастливое число», ежедневная викторина, блэкджек.
Баллы начисляет и списывает wallet; о заработке игрока сообщается в community (доля пригласившему)."""

import json
import time
import sqlite3
import datetime

from flask import abort

from common import client
from common.client import ServiceError
from common.service import create_service, error, payload, need_int
from common.store import db, write, utc_now
from common.serve import run

from . import settings, lucky, blackjack as bj

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    user_id       INTEGER PRIMARY KEY,
    streak        INTEGER NOT NULL DEFAULT 0,
    last_day      TEXT,
    last_claim_at REAL);
CREATE TABLE IF NOT EXISTS quiz_done (
    user_id INTEGER NOT NULL,
    day     TEXT NOT NULL,
    PRIMARY KEY (user_id, day));
CREATE TABLE IF NOT EXISTS bj_games (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    bet     INTEGER NOT NULL,
    shoe    TEXT NOT NULL,
    player  TEXT NOT NULL,
    dealer  TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'betting',   -- betting → playing → done
    result  TEXT,
    payout  INTEGER NOT NULL DEFAULT 0,
    paid    INTEGER NOT NULL DEFAULT 0,        -- выигрыш зачислен в wallet
    version INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL);
-- не больше одной незавершённой раздачи на пользователя
CREATE UNIQUE INDEX IF NOT EXISTS bj_one_active ON bj_games (user_id) WHERE status <> 'done';
"""
WINS = ("win", "blackjack", "dealer_bust")


def create_app(overrides: dict | None = None):
    app = create_service("games", SCHEMA, overrides)

    def report(uid: int, amount: int, kind: str) -> dict:
        """Сообщить community о заработке. Награда уже выдана, поэтому сбой здесь не отменяет её."""
        try:
            return client.post("community", "/earnings", {"uid": uid, "amount": amount, "kind": kind})
        except ServiceError as e:
            app.logger.warning("community did not get earnings of %s: %s", uid, e)
            return {"activated": False, "welcome": 0}

    @app.get("/info")
    def info():
        return {"cooldown": settings.CLAIM_COOLDOWN, "lucky_table": lucky.table(),
                "jackpot": settings.LUCKY_TIERS[-1][1], "max_streak": settings.MAX_STREAK_BONUS,
                "quiz_reward": settings.QUIZ_REWARD, "chips": settings.BJ_CHIPS, "decks": settings.BJ_DECKS}

    # ─── Ежечасное счастливое число ────────────────────────────
    @app.get("/claim/<int:uid>")
    def claim_state(uid):
        row  = db().execute("SELECT * FROM claims WHERE user_id = ?", (uid,)).fetchone()
        wait = max(0, int(row["last_claim_at"] + settings.CLAIM_COOLDOWN - time.time())) if row and row["last_claim_at"] else 0
        return {"wait": wait, "streak": row["streak"] if row else 0}

    @app.post("/claim")
    def claim():
        uid = need_int(payload(), "uid")
        now = time.time()
        con = write()
        con.execute("INSERT OR IGNORE INTO claims (user_id) VALUES (?)", (uid,))
        old = con.execute("SELECT * FROM claims WHERE user_id = ?", (uid,)).fetchone()
        if old["last_claim_at"] and old["last_claim_at"] > now - settings.CLAIM_COOLDOWN:
            con.rollback()
            return error("Your next bonus is not ready yet.", 409)
        today = utc_now().date()
        if old["last_day"] == today.isoformat():
            streak = max(old["streak"], 1)
        elif old["last_day"] == (today - datetime.timedelta(days=1)).isoformat():
            streak = old["streak"] + 1
        else:
            streak = 1
        number = lucky.roll()
        tier, prize = lucky.prize(number)
        bonus  = min(streak, settings.MAX_STREAK_BONUS)
        reward = prize + bonus
        con.execute("UPDATE claims SET last_claim_at = ?, streak = ?, last_day = ? WHERE user_id = ?",
                    (now, streak, today.isoformat(), uid))
        con.commit()                         # кулдаун занят: второй параллельный бросок получит 409
        try:
            client.post("wallet", "/credit", {"uid": uid, "amount": reward, "kind": "claim",
                                              "op_id": f"claim:{uid}:{now}"})
        except ServiceError:
            # Баллы не начислены — вернуть бросок, чтобы игрок мог повторить
            con.execute("UPDATE claims SET last_claim_at = ?, streak = ?, last_day = ? WHERE user_id = ?",
                        (old["last_claim_at"], old["streak"], old["last_day"], uid))
            con.commit()
            raise
        ref = report(uid, reward, "claim")
        return {"number": number, "tier": tier, "prize": prize, "bonus": bonus, "streak": streak,
                "jackpot": tier == len(settings.LUCKY_TIERS) - 1,
                "activated": ref.get("activated", False), "welcome": ref.get("welcome", 0)}

    # ─── Викторина ─────────────────────────────────────────────
    def todays_question():
        today = utc_now().date()
        return today.isoformat(), settings.QUIZ[today.toordinal() % len(settings.QUIZ)]

    @app.get("/quiz/<int:uid>")
    def quiz_state(uid):
        day, q = todays_question()
        done = db().execute("SELECT 1 FROM quiz_done WHERE user_id = ? AND day = ?", (uid, day)).fetchone() is not None
        return {"q": q["q"], "options": q["options"], "done": done}

    @app.post("/quiz")
    def quiz_answer():
        d      = payload()
        uid    = need_int(d, "uid")
        choice = d.get("choice")
        day, q = todays_question()
        try:
            db().execute("INSERT INTO quiz_done (user_id, day) VALUES (?, ?)", (uid, day))
            db().commit()
        except sqlite3.IntegrityError:
            return error("You have already answered today's question.", 409)
        correct = choice == q["answer"]
        if correct:
            try:
                client.post("wallet", "/credit", {"uid": uid, "amount": settings.QUIZ_REWARD, "kind": "quiz",
                                                  "op_id": f"quiz:{uid}:{day}"})
            except ServiceError:
                db().execute("DELETE FROM quiz_done WHERE user_id = ? AND day = ?", (uid, day))   # дать ответить снова
                db().commit()
                raise
            report(uid, settings.QUIZ_REWARD, "quiz")
        return {"correct": correct, "reward": settings.QUIZ_REWARD if correct else 0,
                "answer": q["options"][q["answer"]]}

    # ─── Блэкджек ──────────────────────────────────────────────
    def pay_out(uid: int) -> None:
        """Зачислить выигрыши завершённых раздач. op_id не даст выплатить дважды,
        а невыплаченное (если wallet был недоступен) доплатится при следующем запросе."""
        for g in db().execute("SELECT id, payout FROM bj_games WHERE user_id = ? AND status = 'done' "
                              "AND payout > 0 AND paid = 0", (uid,)).fetchall():
            try:
                client.post("wallet", "/credit", {"uid": uid, "amount": g["payout"], "kind": "blackjack_win",
                                                  "op_id": f"bj:{g['id']}:payout"})
            except ServiceError as e:
                app.logger.warning("payout of hand %s delayed: %s", g["id"], e)
                return
            db().execute("UPDATE bj_games SET paid = 1 WHERE id = ?", (g["id"],))
            db().commit()

    @app.get("/blackjack/<int:uid>")
    def table(uid):
        pay_out(uid)
        d   = db()
        row = d.execute("SELECT * FROM bj_games WHERE user_id = ? AND status <> 'betting' "
                        "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        wins = ",".join(f"'{w}'" for w in WINS)
        st = d.execute(f"SELECT COUNT(*) AS hands, COALESCE(SUM(result IN ({wins})), 0) AS wins, "
                       "COALESCE(SUM(payout - bet), 0) AS net FROM bj_games WHERE user_id = ? AND status = 'done'",
                       (uid,)).fetchone()
        history = [{"label": bj.OUTCOMES[h["result"]][1], "net": h["payout"] - h["bet"],
                    "p": bj.value(json.loads(h["player"])), "d": bj.value(json.loads(h["dealer"]))}
                   for h in d.execute("SELECT * FROM bj_games WHERE user_id = ? AND status = 'done' "
                                      "ORDER BY id DESC LIMIT 6", (uid,))]
        return {"game": bj.public(bj.load(row)) if row else None, "history": history,
                "stats": {"hands": st["hands"], "net": st["net"],
                          "rate": round(100 * st["wins"] / st["hands"]) if st["hands"] else 0}}

    @app.post("/blackjack/deal")
    def deal():
        d   = payload()
        uid = need_int(d, "uid")
        bet = need_int(d, "bet")
        if bet not in settings.BJ_CHIPS:
            return error("Pick a chip to place your bet.")
        shoe = bj.new_shoe()
        player, dealer = [shoe.pop(), shoe.pop()], [shoe.pop(), shoe.pop()]
        con = db()
        try:
            cur = con.execute("INSERT INTO bj_games (user_id, bet, shoe, player, dealer, created) VALUES (?, ?, ?, ?, ?, ?)",
                              (uid, bet, json.dumps(shoe), json.dumps(player), json.dumps(dealer),
                               utc_now().isoformat(timespec="seconds")))
            con.commit()
        except sqlite3.IntegrityError:        # уже есть незавершённая раздача
            con.rollback()
            return error("Finish your current hand first.", 409)
        gid = cur.lastrowid
        try:
            client.post("wallet", "/debit", {"uid": uid, "amount": bet, "kind": "blackjack_bet", "op_id": f"bj:{gid}:bet"})
        except ServiceError as e:
            con.execute("DELETE FROM bj_games WHERE id = ?", (gid,))
            con.commit()
            if e.status == 409:
                return error("Not enough points for this bet.", 409)
            raise
        con.execute("UPDATE bj_games SET status = 'playing' WHERE id = ?", (gid,))
        if bj.natural(player) or bj.natural(dealer):
            game = bj.load(con.execute("SELECT * FROM bj_games WHERE id = ?", (gid,)).fetchone())
            bj.finish(game)
            bj.save(con, game, game["version"])
        con.commit()
        pay_out(uid)
        return {"anim": [0, 0]}

    @app.post("/blackjack/<action>")
    def move(action):
        if action not in ("hit", "stand", "double"):
            abort(404, "Unknown action.")
        uid = need_int(payload(), "uid")
        con = db()
        row = con.execute("SELECT * FROM bj_games WHERE user_id = ? AND status = 'playing'", (uid,)).fetchone()
        if row is None:
            return {"anim": None}
        game = bj.load(row)
        p_before, d_before = len(game["player"]), len(game["dealer"])
        if action == "hit":
            game["player"].append(game["shoe"].pop())
            if bj.value(game["player"]) >= 21:
                bj.finish(game)
        elif action == "stand":
            bj.finish(game)
        else:
            if len(game["player"]) != 2:
                return error("You can only double on your first two cards and with enough points.", 409)
            try:
                client.post("wallet", "/debit", {"uid": uid, "amount": game["bet"], "kind": "blackjack_bet",
                                                 "op_id": f"bj:{game['id']}:double"})
            except ServiceError as e:
                if e.status == 409:
                    return error("You can only double on your first two cards and with enough points.", 409)
                raise
            game["bet"] *= 2
            game["player"].append(game["shoe"].pop())
            bj.finish(game)
        if not bj.save(con, game, row["version"]):   # параллельный запрос уже изменил раздачу
            con.rollback()
            if action == "double":                   # вернуть вторую ставку
                client.post("wallet", "/credit", {"uid": uid, "amount": row["bet"], "kind": "blackjack_refund",
                                                  "op_id": f"bj:{row['id']}:refund"})
            return {"anim": None}
        con.commit()
        pay_out(uid)
        # Анимировать новые карты игрока; при вскрытии — карты дилера начиная с закрытой
        return {"anim": [p_before, 1 if game["status"] == "done" else d_before]}

    # ─── Админка и удаление ────────────────────────────────────
    @app.get("/admin/stats")
    def admin_stats():
        today = utc_now().date().isoformat()
        r = db().execute("SELECT COUNT(*), COALESCE(SUM(bet - payout), 0) FROM bj_games "
                         "WHERE status = 'done' AND created >= ?", (today,)).fetchone()
        return {"hands": r[0], "house": r[1]}

    @app.delete("/users/<int:uid>")
    def delete(uid):
        con = write()
        for table_name in ("claims", "quiz_done", "bj_games"):
            con.execute(f"DELETE FROM {table_name} WHERE user_id = ?", (uid,))
        con.commit()
        return {"ok": True}

    return app


if __name__ == "__main__":
    run(create_app(), "games")
