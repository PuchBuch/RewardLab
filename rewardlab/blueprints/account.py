"""Личный кабинет: дашборд, ежечасная награда, викторина, друзья."""

import time
import random
import sqlite3
import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash

from .. import config
from ..db import db, utc_now
from ..security import current_user, login_required
from ..services.points import add_points
from ..services.referrals import active_referrals, ref_tier, credit_referrer, check_activation, invite_link

bp = Blueprint("account", __name__)


@bp.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    wait = 0
    if u["last_claim_at"]:
        wait = max(0, int(u["last_claim_at"] + config.CLAIM_COOLDOWN - time.time()))
    refs = db().execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (u["id"],)).fetchone()[0]
    events = db().execute("SELECT kind, amount, at FROM events WHERE user_id = ? "
                          "ORDER BY id DESC LIMIT 10", (u["id"],)).fetchall()
    notes = db().execute("SELECT text, at, seen FROM notifications WHERE user_id = ? "
                         "ORDER BY id DESC LIMIT 5", (u["id"],)).fetchall()
    db().execute("UPDATE notifications SET seen = 1 WHERE user_id = ? AND seen = 0", (u["id"],))
    db().commit()
    return render_template("dashboard.html", u=u, wait=wait, refs=refs, events=events, notes=notes,
                           link=invite_link(u),
                           share=int(ref_tier(active_referrals(u["id"]))[0][1] * 100))


@bp.post("/claim")
@login_required
def claim():
    u   = current_user()
    now = time.time()
    # Атомарная проверка: обновится, только если с прошлой награды прошёл час
    cur = db().execute(
        "UPDATE users SET last_claim_at = ? WHERE id = ? "
        "AND (last_claim_at IS NULL OR last_claim_at <= ?)",
        (now, u["id"], now - config.CLAIM_COOLDOWN))
    if cur.rowcount != 1:
        db().commit()
        flash("Your next bonus is not ready yet.", "error")
        return redirect(url_for("account.dashboard"))

    today = utc_now().date()
    if u["last_day"] == today.isoformat():
        streak = max(u["streak"], 1)
    elif u["last_day"] == (today - datetime.timedelta(days=1)).isoformat():
        streak = u["streak"] + 1
    else:
        streak = 1
    reward = config.BASE_REWARD + min(streak, config.MAX_STREAK_BONUS) + random.randint(0, config.RANDOM_BONUS)
    db().execute("UPDATE users SET streak = ?, last_day = ? WHERE id = ?",
                 (streak, today.isoformat(), u["id"]))
    add_points(u["id"], reward, "claim")
    credit_referrer(u, reward)
    msg = f"+{reward} points! Streak: {streak} day(s)."
    if check_activation(u):
        msg += f" 🎉 You are now an active member: +{config.REF_BONUS_FRIEND} welcome bonus!"
    db().commit()
    flash(msg, "ok")
    return redirect(url_for("account.dashboard"))


@bp.route("/quiz", methods=["GET", "POST"])
@login_required
def quiz():
    u     = current_user()
    today = utc_now().date()
    q     = config.QUIZ[today.toordinal() % len(config.QUIZ)]
    done  = db().execute("SELECT 1 FROM quiz_done WHERE user_id = ? AND day = ?",
                         (u["id"], today.isoformat())).fetchone() is not None
    if request.method == "POST" and not done:
        try:
            choice = int(request.form.get("choice", "-1"))
        except ValueError:
            choice = -1
        try:
            db().execute("INSERT INTO quiz_done (user_id, day) VALUES (?, ?)", (u["id"], today.isoformat()))
        except sqlite3.IntegrityError:
            db().commit()
            return redirect(url_for("account.quiz"))
        if choice == q["answer"]:
            add_points(u["id"], config.QUIZ_REWARD, "quiz")
            credit_referrer(u, config.QUIZ_REWARD)
            flash(f"Correct! +{config.QUIZ_REWARD} points.", "ok")
        else:
            flash(f"Not quite. The answer was: {q['options'][q['answer']]}", "error")
        db().commit()
        return redirect(url_for("account.quiz"))
    return render_template("quiz.html", q=q, done=done)


@bp.route("/referrals")
@login_required
def referrals():
    u = current_user()
    active = active_referrals(u["id"])
    tier, nxt = ref_tier(active)
    friends = db().execute(
        "SELECT f.username, f.ref_activated, "
        "  (SELECT COUNT(*) FROM events WHERE user_id = f.id AND kind = 'claim') AS claims, "
        "  (SELECT COALESCE(SUM(amount), 0) FROM events WHERE user_id = :me AND source_id = f.id) AS earned "
        "FROM users f WHERE f.referred_by = :me ORDER BY f.id DESC", {"me": u["id"]}).fetchall()
    earned = db().execute("SELECT COALESCE(SUM(amount), 0) FROM events "
                          "WHERE user_id = ? AND kind IN ('referral', 'ref_bonus')", (u["id"],)).fetchone()[0]
    return render_template("referrals.html", active=active, tier=tier, nxt=nxt, tiers=config.REF_TIERS,
                           friends=friends, earned=earned, link=invite_link(u),
                           claims_needed=config.REF_ACTIVATION_CLAIMS,
                           bonus_inviter=config.REF_BONUS_INVITER, bonus_friend=config.REF_BONUS_FRIEND)
