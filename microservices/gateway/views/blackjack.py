"""Стол блэкджека. Вся игра — в games-сервисе; здесь только отрисовка и анимация карт."""

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort

from common import client
from common.client import ServiceError

from ..backend import info, balance
from ..security import current_user, login_required

bp = Blueprint("blackjack", __name__, url_prefix="/blackjack")
SUITS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}


def view_cards(cards: list, new_from: int, delay_of) -> list:
    """Карты для шаблона. Закрытая карта дилера приходит из games как null."""
    out = []
    for i, c in enumerate(cards):
        if c is None:
            out.append({"hidden": True, "new": i >= new_from, "d": delay_of(i)})
        else:
            out.append({"r": c[:-1], "s": SUITS[c[-1]], "red": c[-1] in "HD", "hidden": False,
                        "new": i >= new_from, "d": delay_of(i)})
    return out


@bp.route("")
@login_required
def index():
    uid    = current_user()["id"]
    points = balance(uid)
    state  = client.get("games", f"/blackjack/{uid}")
    game   = state["game"]
    anim   = session.pop("bj_anim", None)    # какие карты анимировать после последнего действия
    ctx    = {"player": [], "dealer": [], "playing": False, "outcome": None, "bet": 0}
    if game and (game["status"] == "playing" or anim):
        playing = game["status"] == "playing"
        p_from, d_from = anim if anim else (99, 99)
        if anim == [0, 0]:                 # новая раздача: карты по очереди игрок/дилер
            p_delay, d_delay = (lambda i: i * 2), (lambda i: i * 2 + 1)
        else:
            p_delay, d_delay = (lambda i: i - p_from), (lambda i: i - d_from)
        ctx.update(playing=playing, bet=game["bet"], outcome=game["outcome"],
                   player=view_cards(game["player"], p_from, p_delay),
                   dealer=view_cards(game["dealer"], d_from, d_delay),
                   player_val=game["player_val"], dealer_val=game["dealer_val"],
                   can_double=playing and len(game["player"]) == 2 and points >= game["bet"])
    chips = info("games")["chips"]
    affordable = [c for c in chips if c <= points]
    sel = session.get("bj_bet", chips[1])
    if sel not in affordable:
        sel = affordable[-1] if affordable else None
    return render_template("blackjack.html", chips=chips, sel=sel, points=points,
                           history=state["history"], st=state["stats"], **ctx)


@bp.post("/<action>")
@login_required
def action(action):
    if action not in ("deal", "hit", "stand", "double"):
        abort(404)
    uid  = current_user()["id"]
    body = {"uid": uid}
    if action == "deal":
        try:
            body["bet"] = int(request.form.get("bet", ""))
        except ValueError:
            flash("Pick a chip to place your bet.", "error")
            return redirect(url_for("blackjack.index"))
    try:
        r = client.post("games", f"/blackjack/{action}", body)
    except ServiceError as e:
        if e.status >= 500:
            raise
        flash(e.message, "error")
        return redirect(url_for("blackjack.index"))
    if action == "deal":
        session["bj_bet"] = body["bet"]
    if r.get("anim"):
        session["bj_anim"] = r["anim"]
    return redirect(url_for("blackjack.index"))
