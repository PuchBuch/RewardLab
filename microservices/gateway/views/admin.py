"""Админ-панель. Для всех, кроме админов, её адреса отвечают 404.
Вход: пароль + одноразовый код TOTP (проверяет auth), сессия с таймаутом, все действия в журнале."""

import time
from functools import wraps

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort

from common import client
from common.client import ServiceError

from ..backend import names, balance, delete_user
from ..security import current_user, too_many

bp = Blueprint("admin", __name__, url_prefix="/admin")
ADMIN_SESSION_TTL = 15 * 60      # секунд без активности до повторного входа


def admin_log(action: str, target: str | None = None, details: str = "") -> None:
    client.post("auth", "/admin/log", {"admin_id": current_user()["id"], "action": action,
                                       "target": target, "details": details})


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        u = current_user()
        if u is None or not u["is_admin"]:
            abort(404)                      # не раскрываем, что админка существует
        if session.get("admin_uid") != u["id"] or session.get("admin_until", 0) < time.time():
            session.pop("admin_until", None)
            return redirect(url_for("admin.verify"))
        session["admin_until"] = time.time() + ADMIN_SESSION_TTL   # скользящий таймаут
        return view(*args, **kwargs)
    return wrapper


@bp.context_processor
def admin_ctx():
    return {"ttl": ADMIN_SESSION_TTL // 60}


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    u = current_user()
    if u is None or not u["is_admin"] or not u["has_totp"]:
        abort(404)
    if request.method == "POST":
        if too_many(f"admin:{u['id']}", limit=5, window=900) or too_many(f"admin-ip:{request.remote_addr}", limit=10, window=900):
            flash("Too many attempts. Admin login is locked for 15 minutes.", "error")
            return redirect(url_for("admin.verify"))
        try:
            client.post("auth", "/admin/verify", {"uid": u["id"], "password": request.form.get("password", ""),
                                                  "code": request.form.get("code", "")})
        except ServiceError as e:
            if e.status >= 500:
                raise
            flash("Invalid password or code.", "error")
            return redirect(url_for("admin.verify"))
        session["admin_uid"]   = u["id"]
        session["admin_until"] = time.time() + ADMIN_SESSION_TTL
        return redirect(url_for("admin.index"))
    return render_template("admin/verify.html")


@bp.post("/logout")
@admin_required
def logout():
    session.pop("admin_uid", None)
    session.pop("admin_until", None)
    flash("You left admin mode.", "ok")
    return redirect(url_for("account.dashboard"))


@bp.route("")
@admin_required
def index():
    q      = request.args.get("q", "").strip()[:20]
    ov     = client.get("auth", "/admin/overview", q=q)
    wallet = client.get("wallet", "/stats")
    games  = client.get("games", "/admin/stats")
    s = {**ov["stats"], "points": wallet["points"], "claims": wallet["claims_today"],
         "hands": games["hands"], "house": games["house"]}
    ids    = ",".join(str(m["id"]) for m in ov["members"])
    points = client.get("wallet", "/balances", ids=ids)["points"] if ids else {}
    counts = client.get("community", "/referrals/counts", ids=ids)["counts"] if ids else {}
    members = [{**m, "points": points.get(str(m["id"]), 0), **counts.get(str(m["id"]), {"invited": 0, "active": 0})}
               for m in ov["members"]]
    return render_template("admin/index.html", s=s, q=q, members=members, nets=ov["nets"], log=ov["log"])


@bp.route("/user/<int:uid>")
@admin_required
def user(uid):
    a   = client.get("auth", f"/admin/users/{uid}")       # 404 → страница «не найдено»
    ref = client.get("community", f"/referrals/{uid}")
    t   = {**a["user"], "points": balance(uid), "streak": client.get("games", f"/claim/{uid}")["streak"]}
    return render_template(
        "admin/user.html", t=t, referrer=names([ref["inviter_id"]]).get(ref["inviter_id"]),
        same_net=a["same_net"], invited=ref["invited"], active=ref["active"],
        events=client.get("wallet", f"/events/{uid}", limit=15)["events"], log=a["log"])


@bp.post("/user/<int:uid>/<action>")
@admin_required
def action(uid, action):
    t    = client.get("auth", f"/admin/users/{uid}")["user"]
    back = redirect(url_for("admin.user", uid=uid))
    if t["is_admin"]:
        flash("Admin accounts cannot be changed from the panel.", "error")
        return back
    name = t["username"]
    if action == "adjust":
        try:
            amount = int(request.form.get("amount", ""))
        except ValueError:
            amount = 0
        reason = request.form.get("reason", "").strip()[:200]
        if not amount or not -100000 <= amount <= 100000 or not reason:
            flash("Enter a non-zero amount (±100000) and a reason.", "error")
            return back
        amount = client.post("wallet", "/credit", {"uid": uid, "amount": amount, "kind": "admin_adjust"})["amount"]
        client.post("community", "/notify", {"uid": uid, "text": f"🛠 An administrator adjusted your points by "
                                                                  f"{'+' if amount > 0 else ''}{amount}: {reason}"})
        admin_log("adjust_points", name, f"{'+' if amount > 0 else ''}{amount}: {reason}")
        flash(f"Points adjusted by {amount}.", "ok")
    elif action in ("ban", "unban"):
        client.post("auth", f"/admin/users/{uid}/ban", {"banned": action == "ban"})
        admin_log(action, name)
        flash(f"{name} {'banned' if action == 'ban' else 'unbanned'}.", "ok")
    elif action == "unlink":
        client.post("community", f"/referrals/{uid}/unlink")
        admin_log("unlink_referral", name)
        flash("Referral link removed.", "ok")
    elif action == "delete":
        if request.form.get("confirm", "") != name:
            flash("Type the exact username to confirm deletion.", "error")
            return back
        delete_user(uid)
        admin_log("delete_account", name)
        flash(f"{name} deleted.", "ok")
        return redirect(url_for("admin.index"))
    else:
        abort(404)
    return back
