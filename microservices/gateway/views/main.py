"""Публичные страницы: главная, таблица лидеров, правила, конфиденциальность."""

from flask import Blueprint, render_template, request

from common import client

from ..backend import info, names, with_names

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    wallet = client.get("wallet", "/stats")
    stats  = {"users": client.get("auth", "/stats")["users"], "claims": wallet["claims"], "points": wallet["awarded"]}
    return render_template("home.html", stats=stats, share=int(info("community")["tiers"][-1][1] * 100),
                           quiz=info("games")["quiz_reward"], jackpot=info("games")["jackpot"])


@bp.route("/leaderboard")
def leaderboard():
    tab = request.args.get("tab", "points")
    ctx = {"prizes": info("community")["prizes"]}
    if tab == "inviters":
        rows = with_names(client.get("community", "/leaderboard/inviters")["rows"])
        ctx.update(col="Active friends", empty="Nobody has active friends yet. Invite someone!")
    elif tab == "week":
        c    = client.get("community", "/contest")
        rows = with_names(c["rows"])
        ctx.update(col="Active this week", empty="No active friends this week yet. The first one takes the lead!",
                   left_d=c["left_d"], left_h=c["left_h"], last=with_names(c["last"]))
    else:
        tab  = "points"
        top  = client.get("wallet", "/top", limit=20)["top"]
        found = names(r["user_id"] for r in top)
        rows = [{"username": found[r["user_id"]], "value": r["points"]} for r in top if r["user_id"] in found]
        ctx.update(col="Points", empty="No members yet. Be the first!")
    return render_template("leaderboard.html", tab=tab, rows=rows, **ctx)


@bp.route("/rules")
def rules():
    games, com = info("games"), info("community")
    return render_template(
        "rules.html", cooldown=games["cooldown"] // 60, lucky_table=games["lucky_table"],
        max_streak=games["max_streak"], quiz=games["quiz_reward"],
        tiers=com["tiers"], claims_needed=com["activation_claims"],
        bonus_inviter=com["bonus_inviter"], bonus_friend=com["bonus_friend"],
        prizes=com["prizes"], per_net=info("auth")["per_net"],
        chips=games["chips"], decks=games["decks"])


@bp.route("/legal")
def legal():
    return render_template("legal.html")
