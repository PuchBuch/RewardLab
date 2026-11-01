"""Регистрация, вход, выход, удаление своего аккаунта."""

import re
import secrets
import sqlite3
import datetime

from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash

from .. import config
from ..db import db, utc_now, now_iso
from ..security import current_user, login_required, too_many, network_id
from ..services.points import notify, delete_user

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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        net = network_id()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            flash("Username: 3–20 letters, digits or underscore.", "error")
        elif not 8 <= len(password) <= 128:
            flash("Password must be 8–128 characters.", "error")
        elif request.form.get("terms") != "1":
            flash("Please accept the terms.", "error")
        elif net and db().execute(
                "SELECT COUNT(*) FROM users WHERE reg_net = ? AND created >= ?",
                (net, (utc_now() - datetime.timedelta(days=1)).isoformat(timespec="seconds"))
                ).fetchone()[0] >= config.REG_PER_NETWORK_DAY:
            flash("Too many accounts were created from your network today. Please try again tomorrow.", "error")
        else:
            referrer = (db().execute("SELECT id, reg_net FROM users WHERE ref_code = ?", (ref,)).fetchone()
                        if ref else None)
            same_net = net is not None and referrer is not None and referrer["reg_net"] == net
            ref_id = referrer["id"] if referrer and not same_net else None
            try:
                cur = db().execute(
                    "INSERT INTO users (username, pw_hash, ref_code, referred_by, created, reg_net) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (username, generate_password_hash(password), secrets.token_urlsafe(6),
                     ref_id, now_iso(), net))
                if ref_id:
                    notify(ref_id, f"👋 {username} joined with your invite. They become active "
                                   f"after {config.REF_ACTIVATION_CLAIMS} hourly claims.")
                db().commit()
            except sqlite3.IntegrityError:
                flash("That username is taken.", "error")
            else:
                session.clear()
                session["uid"] = cur.lastrowid
                if same_net:
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
        username = request.form.get("username", "").strip()
        row = db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["pw_hash"], request.form.get("password", "")):
            if row["banned"]:
                flash("This account has been suspended for breaking the rules.", "error")
                return render_template("login.html")
            session.clear()
            session["uid"] = row["id"]
            return redirect(url_for("account.dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.home"))


@bp.post("/delete-account")
@login_required
def delete_account():
    delete_user(current_user()["id"])
    db().commit()
    session.clear()
    flash("Your account and data have been deleted.", "ok")
    return redirect(url_for("main.home"))
