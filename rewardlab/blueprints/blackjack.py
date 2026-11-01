"""Блэкджек: стол и ходы игрока."""

import json
import sqlite3

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort

from .. import config
from ..db import db, now_iso
from ..security import current_user, login_required
from ..services import blackjack as bj
from ..services.points import spend_points

bp = Blueprint("blackjack", __name__, url_prefix="/blackjack")


@bp.route("")
@login_required
def index():
    u    = current_user()
    row  = db().execute("SELECT * FROM bj_games WHERE user_id = ? ORDER BY id DESC LIMIT 1", (u["id"],)).fetchone()
    anim = session.pop("bj_anim", None)    # какие карты анимировать после последнего действия
    ctx  = {"player": [], "dealer": [], "playing": False, "outcome": None, "bet": 0}
    if row and (row["status"] == "playing" or anim):
        game = bj.load(row)
        playing = game["status"] == "playing"
        p_from, d_from = anim if anim else (99, 99)
        if anim == [0, 0]:                 # новая раздача: карты по очереди игрок/дилер
            p_delay, d_delay = (lambda i: i * 2), (lambda i: i * 2 + 1)
        else:
            p_delay, d_delay = (lambda i: i - p_from), (lambda i: i - d_from)
        ctx.update(
            playing=playing, bet=game["bet"],
            player=bj.view_cards(game["player"], False, p_from, p_delay),
            dealer=bj.view_cards(game["dealer"], playing, d_from, d_delay),
            player_val=bj.value(game["player"]),
            dealer_val=bj.value(game["dealer"][:1]) if playing else bj.value(game["dealer"]),
            can_double=playing and len(game["player"]) == 2 and u["points"] >= game["bet"])
        if not playing:
            kind, title = bj.OUTCOMES[game["result"]]
            net = game["payout"] - game["bet"]
            sub = {"win": f"+{net} points", "push": "Your bet is returned",
                   "lose": f"−{game['bet']} points. Better luck next hand!"}[kind]
            ctx["outcome"] = {"kind": kind, "title": title, "sub": sub}
    st = db().execute(
        "SELECT COUNT(*) AS hands, "
        "  COALESCE(SUM(result IN ('win', 'blackjack', 'dealer_bust')), 0) AS wins, "
        "  COALESCE(SUM(payout - bet), 0) AS net "
        "FROM bj_games WHERE user_id = ? AND status = 'done'", (u["id"],)).fetchone()
    history = [{"label": bj.OUTCOMES[h["result"]][1], "net": h["payout"] - h["bet"],
                "p": bj.value(json.loads(h["player"])), "d": bj.value(json.loads(h["dealer"]))}
               for h in db().execute("SELECT * FROM bj_games WHERE user_id = ? AND status = 'done' "
                                     "ORDER BY id DESC LIMIT 6", (u["id"],))]
    affordable = [c for c in config.BJ_CHIPS if c <= u["points"]]
    sel = session.get("bj_bet", config.BJ_CHIPS[1])
    if sel not in affordable:
        sel = affordable[-1] if affordable else None
    return render_template("blackjack.html", chips=config.BJ_CHIPS, sel=sel, points=u["points"], history=history,
                           st={"hands": st["hands"], "net": st["net"],
                               "rate": round(100 * st["wins"] / st["hands"]) if st["hands"] else 0}, **ctx)


@bp.post("/<action>")
@login_required
def action(action):
    uid = current_user()["id"]
    if action == "deal":
        try:
            bet = int(request.form.get("bet", ""))
        except ValueError:
            bet = 0
        if bet not in config.BJ_CHIPS:
            flash("Pick a chip to place your bet.", "error")
            return redirect(url_for("blackjack.index"))
        if not spend_points(uid, bet, "blackjack_bet"):
            db().rollback()
            flash("Not enough points for this bet.", "error")
            return redirect(url_for("blackjack.index"))
        shoe = bj.new_shoe()
        player, dealer = [shoe.pop(), shoe.pop()], [shoe.pop(), shoe.pop()]
        try:
            cur = db().execute(
                "INSERT INTO bj_games (user_id, bet, shoe, player, dealer, created) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, bet, json.dumps(shoe), json.dumps(player), json.dumps(dealer), now_iso()))
        except sqlite3.IntegrityError:     # уже есть незавершённая раздача
            db().rollback()
            return redirect(url_for("blackjack.index"))
        if bj.natural(player) or bj.natural(dealer):
            game = {"id": cur.lastrowid, "user_id": uid, "bet": bet, "shoe": shoe, "player": player,
                    "dealer": dealer, "status": "playing", "result": None, "payout": 0}
            bj.finish(game)
            bj.save(game, 0)
        db().commit()
        session["bj_bet"]  = bet
        session["bj_anim"] = [0, 0]
        return redirect(url_for("blackjack.index"))

    row = db().execute("SELECT * FROM bj_games WHERE user_id = ? AND status = 'playing'", (uid,)).fetchone()
    if row is None:
        return redirect(url_for("blackjack.index"))
    game = bj.load(row)
    p_before, d_before = len(game["player"]), len(game["dealer"])
    if action == "hit":
        game["player"].append(game["shoe"].pop())
        if bj.value(game["player"]) >= 21:
            bj.finish(game)
    elif action == "stand":
        bj.finish(game)
    elif action == "double":
        if len(game["player"]) != 2 or not spend_points(uid, game["bet"], "blackjack_bet"):
            db().rollback()
            flash("You can only double on your first two cards and with enough points.", "error")
            return redirect(url_for("blackjack.index"))
        game["bet"] *= 2
        game["player"].append(game["shoe"].pop())
        bj.finish(game)
    else:
        abort(404)
    if not bj.save(game, row["version"]):  # параллельный запрос уже изменил раздачу
        db().rollback()
        return redirect(url_for("blackjack.index"))
    db().commit()
    # Анимировать новые карты игрока; при вскрытии — карты дилера начиная с закрытой
    session["bj_anim"] = [p_before, 1 if game["status"] == "done" else d_before]
    return redirect(url_for("blackjack.index"))
