"""Личный кабинет: дашборд, ежечасное счастливое число, викторина, друзья."""

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, make_response

from common import client
from common.client import ServiceError

from .. import captcha
from ..backend import info, names, balance, invite_link
from ..security import current_user, login_required, too_many

bp = Blueprint("account", __name__)


@bp.route("/dashboard")
@login_required
def dashboard():
    user  = current_user()
    uid   = user["id"]
    state = client.get("games", f"/claim/{uid}")
    ref   = client.get("community", f"/referrals/{uid}")
    notes = client.get("community", f"/notifications/{uid}", limit=5)["items"]
    client.post("community", f"/notifications/{uid}/seen")
    games = info("games")
    u = {**user, "points": balance(uid), "streak": state["streak"]}
    return render_template("dashboard.html", u=u, wait=state["wait"], refs=ref["invited"],
                           events=client.get("wallet", f"/events/{uid}", limit=10)["events"], notes=notes,
                           link=invite_link(user), lucky_table=games["lucky_table"], max_streak=games["max_streak"],
                           roll=session.pop("last_roll", None), share=int(ref["tier"][1] * 100))


@bp.route("/captcha.svg")
@login_required
def captcha_image():
    resp = make_response(captcha.new_svg())
    resp.headers["Content-Type"] = "image/svg+xml"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/claim")
@login_required
def claim():
    uid = current_user()["id"]
    if too_many(f"captcha:{uid}", limit=20, window=600):
        flash("Too many attempts. Please wait a few minutes.", "error")
        return redirect(url_for("account.dashboard"))
    if not captcha.check(request.form.get("captcha", "")):
        flash("Wrong security code. Please try the new one.", "error")
        return redirect(url_for("account.dashboard"))
    try:
        r = client.post("games", "/claim", {"uid": uid})
    except ServiceError as e:
        if e.status >= 500:
            raise
        flash(e.message, "error")
        return redirect(url_for("account.dashboard"))
    session["last_roll"] = {"n": r["number"], "tier": r["tier"], "prize": r["prize"], "bonus": r["bonus"]}
    msg = f"Lucky number {r['number']}: +{r['prize']} points, +{r['bonus']} streak bonus ({r['streak']} day(s))."
    if r["jackpot"]:
        msg = "🎰 JACKPOT! " + msg
    if r["activated"]:
        msg += f" 🎉 You are now an active member: +{r['welcome']} welcome bonus!"
    flash(msg, "ok")
    return redirect(url_for("account.dashboard"))


@bp.route("/quiz", methods=["GET", "POST"])
@login_required
def quiz():
    uid = current_user()["id"]
    if request.method == "POST":
        try:
            choice = int(request.form.get("choice", "-1"))
        except ValueError:
            choice = -1
        try:
            r = client.post("games", "/quiz", {"uid": uid, "choice": choice})
        except ServiceError as e:
            if e.status >= 500:
                raise
            return redirect(url_for("account.quiz"))
        if r["correct"]:
            flash(f"Correct! +{r['reward']} points.", "ok")
        else:
            flash(f"Not quite. The answer was: {r['answer']}", "error")
        return redirect(url_for("account.quiz"))
    q = client.get("games", f"/quiz/{uid}")
    return render_template("quiz.html", q=q, done=q["done"])


@bp.route("/referrals")
@login_required
def referrals():
    user   = current_user()
    ref    = client.get("community", f"/referrals/{user['id']}")
    earned = client.get("wallet", f"/earned/{user['id']}")
    found  = names(f["user_id"] for f in ref["friends"])
    friends = [{"username": found.get(f["user_id"], "—"), "ref_activated": f["activated"], "claims": f["claims"],
                "earned": earned["by_source"].get(str(f["user_id"]), 0)} for f in ref["friends"]]
    com = info("community")
    return render_template("referrals.html", active=ref["active"], tier=ref["tier"], nxt=ref["next"],
                           tiers=com["tiers"], friends=friends, earned=earned["total"], link=invite_link(user),
                           claims_needed=com["activation_claims"],
                           bonus_inviter=com["bonus_inviter"], bonus_friend=com["bonus_friend"])
