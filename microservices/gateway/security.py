"""Текущий пользователь, CSRF, ограничение попыток, заголовки безопасности."""

import hmac
import time
import hashlib
import secrets
import ipaddress
from collections import defaultdict, deque
from functools import wraps

from flask import current_app, g, session, request, redirect, url_for, abort

from common import client
from common.client import ServiceError


def current_user() -> dict | None:
    """Пользователь из auth-сервиса. Забаненный или удалённый считается вышедшим."""
    if "user" not in g:
        uid, user = session.get("uid"), None
        if uid:
            try:
                user = client.get("auth", f"/users/{uid}")
            except ServiceError as e:
                if e.status != 404:
                    raise
            if user is None or user["banned"]:
                session.pop("uid", None)
                user = None
        g.user = user
    return g.user


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapper


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400)


def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


HITS = defaultdict(deque)


def too_many(key: str, limit: int = 10, window: int = 600) -> bool:
    now = time.time()
    q = HITS[key]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def network_id() -> str | None:
    """Необратимый хеш IP: сам адрес не хранится, но совпадения видны.
    Для локальных и внутренних адресов (разработка, Docker без TRUST_PROXY) проверки отключены: None."""
    ip = request.remote_addr or ""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_loopback or addr.is_private:
        return None
    return hmac.new(current_app.secret_key.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def inject_user():
    """Пользователь и счётчик непрочитанных уведомлений доступны во всех шаблонах.
    Если сервис не отвечает, страница всё равно отрисуется (например, страница ошибки)."""
    try:
        u = current_user()
        unread = client.get("community", f"/unread/{u['id']}")["count"] if u else 0
    except ServiceError:
        u, unread = g.get("user"), 0
    return {"user": u, "unread": unread}


def init_app(app) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(check_csrf)
    app.after_request(security_headers)
    app.context_processor(inject_user)
