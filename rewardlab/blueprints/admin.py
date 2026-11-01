"""Админ-панель. Для всех, кроме админов, её адреса отвечают 404.
Вход: пароль + одноразовый код TOTP, сессия с таймаутом, все действия в журнале."""

import re
import time
import datetime
from functools import wraps

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort
from werkzeug.security import check_password_hash

from .. import config
from ..db import db, utc_now, now_iso
from ..security import current_user, too_many
from ..services import totp
from ..services.points import add_points, notify, delete_user
from ..services.referrals import active_referrals

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_log(action: str, target: str | None = None, details: str = "") -> None:
    u = current_user()
    db().execute("INSERT INTO admin_log (admin_id, admin_name, action, target, details, at) "
                 "VALUES (?, ?, ?, ?, ?, ?)", (u["id"], u["username"], action, target, details, now_iso()))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        u = current_user()
        if u is None or not u["is_admin"]:
            abort(404)                      # не раскрываем, что админка существует
        if session.get("admin_uid") != u["id"] or session.get("admin_until", 0) < time.time():
            session.pop("admin_until", None)
            return redirect(url_for("admin.verify"))
        session["admin_until"] = time.time() + config.ADMIN_SESSION_TTL   # скользящий таймаут
        return view(*args, **kwargs)
    return wrapper


@bp.context_processor
def admin_ctx():
    return {"ttl": config.ADMIN_SESSION_TTL // 60}


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    u = current_user()
    if u is None or not u["is_admin"] or not u["totp_secret"]:
        abort(404)
    if request.method == "POST":
        if too_many(f"admin:{u['id']}", limit=5, window=900) or too_many(f"admin-ip:{request.remote_addr}", limit=10, window=900):
            flash("Too many attempts. Admin login is locked for 15 minutes.", "error")
            return redirect(url_for("admin.verify"))
        step = (totp.check(u["totp_secret"], request.form.get("code", "").strip(), u["totp_last"])
                if check_password_hash(u["pw_hash"], request.form.get("password", "")) else None)
        if step is None:
            admin_log("failed_verification")
            db().commit()
            flash("Invalid password or code.", "error")
            return redirect(url_for("admin.verify"))
        db().execute("UPDATE users SET totp_last = ? WHERE id = ?", (step, u["id"]))  # код одноразовый
        admin_log("signed_in")
        db().commit()
        session["admin_uid"]   = u["id"]
        session["admin_until"] = time.time() + config.ADMIN_SESSION_TTL
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
    d       = db()
    today   = utc_now().date().isoformat()
    day_ago = (utc_now() - datetime.timedelta(days=1)).isoformat(timespec="seconds")
    s = {
        "users":  d.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "new":    d.execute("SELECT COUNT(*) FROM users WHERE created >= ?", (day_ago,)).fetchone()[0],
        "banned": d.execute("SELECT COUNT(*) FROM users WHERE banned = 1").fetchone()[0],
        "points": d.execute("SELECT COALESCE(SUM(points), 0) FROM users").fetchone()[0],
        "claims": d.execute("SELECT COUNT(*) FROM events WHERE kind = 'claim' AND at >= ?", (today,)).fetchone()[0],
        "hands":  d.execute("SELECT COUNT(*) FROM bj_games WHERE status = 'done' AND created >= ?", (today,)).fetchone()[0],
        "house":  d.execute("SELECT COALESCE(SUM(bet - payout), 0) FROM bj_games "
                            "WHERE status = 'done' AND created >= ?", (today,)).fetchone()[0],
    }
    q = request.args.get("q", "").strip()[:20]
    members = d.execute(
        "SELECT u.id, u.username, u.points, u.created, u.banned, u.is_admin, "
        "  (SELECT COUNT(*) FROM users f WHERE f.referred_by = u.id) AS invited, "
        "  (SELECT COUNT(*) FROM users f WHERE f.referred_by = u.id AND f.ref_activated = 1) AS active "
        "FROM users u WHERE u.username LIKE ? ESCAPE '\\' ORDER BY u.id DESC LIMIT 50",
        ("%" + re.sub(r"([%_\\])", r"\\\1", q) + "%",)).fetchall()
    nets = d.execute("SELECT reg_net, COUNT(*) AS n, GROUP_CONCAT(username) AS names FROM users "
                     "WHERE reg_net IS NOT NULL GROUP BY reg_net HAVING n > 1 ORDER BY n DESC LIMIT 10").fetchall()
    log = d.execute("SELECT * FROM admin_log ORDER BY id DESC LIMIT 25").fetchall()
    return render_template("admin/index.html", s=s, q=q, members=members, nets=nets, log=log)


@bp.route("/user/<int:uid>")
@admin_required
def user(uid):
    d = db()
    t = d.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if t is None:
        abort(404)
    referrer = d.execute("SELECT username FROM users WHERE id = ?", (t["referred_by"],)).fetchone() if t["referred_by"] else None
    same_net = (d.execute("SELECT COUNT(*) FROM users WHERE reg_net = ? AND id != ?", (t["reg_net"], uid)).fetchone()[0]
                if t["reg_net"] else 0)
    return render_template(
        "admin/user.html", t=t, referrer=referrer["username"] if referrer else None, same_net=same_net,
        invited=d.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (uid,)).fetchone()[0],
        active=active_referrals(uid),
        events=d.execute("SELECT kind, amount, at FROM events WHERE user_id = ? ORDER BY id DESC LIMIT 15", (uid,)).fetchall(),
        log=d.execute("SELECT * FROM admin_log WHERE target = ? ORDER BY id DESC LIMIT 15", (t["username"],)).fetchall())


@bp.post("/user/<int:uid>/<action>")
@admin_required
def action(uid, action):
    d = db()
    t = d.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if t is None:
        abort(404)
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
        amount = max(amount, -t["points"])          # баланс не уходит в минус
        add_points(uid, amount, "admin_adjust")
        notify(uid, f"🛠 An administrator adjusted your points by {'+' if amount > 0 else ''}{amount}: {reason}")
        admin_log("adjust_points", name, f"{'+' if amount > 0 else ''}{amount}: {reason}")
        flash(f"Points adjusted by {amount}.", "ok")
    elif action in ("ban", "unban"):
        d.execute("UPDATE users SET banned = ? WHERE id = ?", (int(action == "ban"), uid))
        admin_log(action, name)
        flash(f"{name} {'banned' if action == 'ban' else 'unbanned'}.", "ok")
    elif action == "unlink":
        d.execute("UPDATE users SET referred_by = NULL WHERE id = ?", (uid,))
        admin_log("unlink_referral", name)
        flash("Referral link removed.", "ok")
    elif action == "delete":
        if request.form.get("confirm", "") != name:
            flash("Type the exact username to confirm deletion.", "error")
            return back
        delete_user(uid)
        admin_log("delete_account", name)
        d.commit()
        flash(f"{name} deleted.", "ok")
        return redirect(url_for("admin.index"))
    else:
        abort(404)
    d.commit()
    return back
