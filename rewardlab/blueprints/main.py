"""Публичные страницы: главная, таблица лидеров, правила, конфиденциальность."""

import datetime

from flask import Blueprint, render_template, request

from .. import config
from ..db import db, utc_now
from ..services import contest

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    d = db()
    stats = {
        "users":  d.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "claims": d.execute("SELECT COUNT(*) FROM events WHERE kind = 'claim'").fetchone()[0],
        "points": d.execute("SELECT COALESCE(SUM(amount), 0) FROM events WHERE amount > 0").fetchone()[0],
    }
    return render_template("home.html", stats=stats, share=int(config.REF_TIERS[-1][1] * 100),
                           quiz=config.QUIZ_REWARD)


@bp.route("/leaderboard")
def leaderboard():
    tab = request.args.get("tab", "points")
    ctx = {"prizes": config.CONTEST_PRIZES}
    if tab == "inviters":
        rows = db().execute(
            "SELECT u.username, COUNT(f.id) AS value FROM users u "
            "JOIN users f ON f.referred_by = u.id AND f.ref_activated = 1 "
            "GROUP BY u.id ORDER BY value DESC, u.id LIMIT 20").fetchall()
        ctx.update(col="Active friends", empty="Nobody has active friends yet. Invite someone!")
    elif tab == "week":
        start = contest.week_start(utc_now())
        left  = start + datetime.timedelta(days=7) - utc_now()
        rows  = contest.standings(start)
        last  = db().execute(
            "SELECT r.place, u.username, r.amount FROM contest_results r JOIN users u ON u.id = r.user_id "
            "WHERE r.week = ? ORDER BY r.place",
            ((start - datetime.timedelta(days=7)).date().isoformat(),)).fetchall()
        ctx.update(col="Active this week", empty="No active friends this week yet. The first one takes the lead!",
                   left_d=left.days, left_h=left.seconds // 3600, last=last)
    else:
        tab  = "points"
        rows = db().execute("SELECT username, points AS value FROM users "
                            "ORDER BY points DESC, id LIMIT 20").fetchall()
        ctx.update(col="Points", empty="No members yet. Be the first!")
    return render_template("leaderboard.html", tab=tab, rows=rows, **ctx)


@bp.route("/rules")
def rules():
    return render_template(
        "rules.html", cooldown=config.CLAIM_COOLDOWN // 60, base=config.BASE_REWARD,
        max_streak=config.MAX_STREAK_BONUS, rand=config.RANDOM_BONUS, quiz=config.QUIZ_REWARD,
        tiers=config.REF_TIERS, claims_needed=config.REF_ACTIVATION_CLAIMS,
        bonus_inviter=config.REF_BONUS_INVITER, bonus_friend=config.REF_BONUS_FRIEND,
        prizes=config.CONTEST_PRIZES, per_net=config.REG_PER_NETWORK_DAY,
        chips=config.BJ_CHIPS, decks=config.BJ_DECKS)


@bp.route("/legal")
def legal():
    return render_template("legal.html")
