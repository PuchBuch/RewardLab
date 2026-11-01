"""RewardLab: фабрика приложения Flask."""

import os
import secrets

from dotenv import load_dotenv
from flask import Flask

from . import config, db, security
from .services import contest


def create_app(overrides: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__)
    secret = os.getenv("APP_SECRET")
    if not secret:
        secret = secrets.token_hex(32)
        print("⚠️ APP_SECRET не задан: сессии сбросятся при перезапуске.")
    app.config.update(
        SECRET_KEY=secret,
        DATABASE=config.DATABASE,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE") == "1",
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    app.config.update(overrides or {})
    if os.getenv("TRUST_PROXY") == "1":
        # За nginx и т.п.: брать реальный IP посетителя из X-Forwarded-For
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    security.init_app(app)
    app.before_request(contest.settle)

    from .blueprints import main, auth, account, blackjack, admin
    for module in (main, auth, account, blackjack, admin):
        app.register_blueprint(module.bp)
    return app
