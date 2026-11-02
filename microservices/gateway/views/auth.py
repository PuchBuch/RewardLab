"""Регистрация, вход, выход, удаление своего аккаунта."""

from flask import Blueprint, render_template, request, session, redirect, url_for, flash

from common import client
from common.client import ServiceError

from ..backend import delete_user
from ..security import current_user, login_required, too_many, network_id

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("account.dashboard"))
    ref = request.values.get("ref", "").strip()[:30]
    if request.method == "POST":
        if too_many(f"{request.remote_addr}:register"):
            flash("Too many attempts. Please try again in a few minutes.", "error")
            return redirect(url_for("auth.register"))
        if request.form.get("terms") != "1":
            flash("Please accept the terms.", "error")
            return render_template("register.html", ref=ref)
        try:
            u = client.post("auth", "/register", {"username": request.form.get("username", ""),
                                                  "password": request.form.get("password", ""),
                                                  "net": network_id(), "ref": ref})
        except ServiceError as e:
            if e.status >= 500:
                raise
            flash(e.message, "error")
            return render_template("register.html", ref=ref)
        client.post("wallet", "/accounts", {"uid": u["id"]})
        if u["inviter_id"]:
            client.post("community", "/referrals", {"friend_id": u["id"], "inviter_id": u["inviter_id"],
                                                    "friend_name": u["username"]})
        session.clear()
        session["uid"] = u["id"]
        if u["ref_ignored"]:
            flash("Account created. The invite was not counted: it came from the inviter's own network "
                  "(see the fair play rules).", "error")
        flash("Welcome! Make your first claim.", "ok")
        return redirect(url_for("account.dashboard"))
    return render_template("register.html", ref=ref)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("account.dashboard"))
    if request.method == "POST":
        if too_many(f"{request.remote_addr}:login"):
            flash("Too many attempts. Please try again in a few minutes.", "error")
            return redirect(url_for("auth.login"))
        try:
            r = client.post("auth", "/login", {"username": request.form.get("username", ""),
                                               "password": request.form.get("password", "")})
        except ServiceError as e:
            if e.status >= 500:
                raise
            flash(e.message, "error")
            return render_template("login.html")
        session.clear()
        session["uid"] = r["id"]
        return redirect(url_for("account.dashboard"))
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.home"))


@bp.post("/delete-account")
@login_required
def delete_account():
    delete_user(current_user()["id"])
    session.clear()
    flash("Your account and data have been deleted.", "ok")
    return redirect(url_for("main.home"))
