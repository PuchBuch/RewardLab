"""Gateway: страницы сайта, сессии, CSRF, капча и лимиты попыток.
Своей базы нет — данные берутся из сервисов auth, wallet, games и community."""

import os
import secrets

from dotenv import load_dotenv
from flask import Flask, render_template

from common.client import ServiceError
from common.serve import run
from common.store import ROOT

from . import security


def create_app(overrides: dict | None = None) -> Flask:
    load_dotenv(os.path.join(ROOT, ".env"))
    app = Flask(__name__)
    secret = os.getenv("APP_SECRET")
    if not secret:
        secret = secrets.token_hex(32)
        print("⚠️ APP_SECRET не задан: сессии сбросятся при перезапуске.")
    app.config.update(
        SECRET_KEY=secret,
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

    security.init_app(app)

    @app.errorhandler(ServiceError)
    def service_error(e):
        if e.status == 404:
            return render_template("error.html", code=404, title="Page not found",
                                   text="This page does not exist."), 404
        app.logger.warning("service error: %s", e)
        return render_template("error.html", code=503, title="Temporarily unavailable",
                               text="Part of RewardLab is not responding right now. Please try again in a minute."), 503

    @app.get("/health")
    def health():
        return {"service": "gateway", "ok": True}

    from .views import main, auth, account, blackjack, admin
    for module in (main, auth, account, blackjack, admin):
        app.register_blueprint(module.bp)
    return app


if __name__ == "__main__":
    run(create_app(), "gateway")
