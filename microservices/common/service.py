"""Каркас внутреннего сервиса: Flask, своя база, проверка служебного токена, ошибки в JSON."""

import os
import hmac

from dotenv import load_dotenv
from flask import Flask, request, jsonify, abort
from werkzeug.exceptions import HTTPException

from . import store
from .client import HEADER, ServiceError


def create_service(name: str, schema: str, overrides: dict | None = None) -> Flask:
    load_dotenv(os.path.join(store.ROOT, ".env"))
    app = Flask(name)
    app.config.update(DATABASE=store.db_path(name), INTERNAL_TOKEN=os.getenv("INTERNAL_TOKEN", ""),
                      MAX_CONTENT_LENGTH=64 * 1024)
    app.config.update(overrides or {})
    store.init_app(app, schema)

    @app.before_request
    def check_token():
        if request.path == "/health":
            return None
        token = app.config["INTERNAL_TOKEN"]
        sent  = request.headers.get(HEADER, "")
        if not token or not hmac.compare_digest(sent.encode(), token.encode()):
            return error("Missing or invalid internal token.", 401)
        return None

    @app.get("/health")
    def health():
        return {"service": name, "ok": True}

    @app.errorhandler(HTTPException)
    def http_error(e):
        return error(e.description, e.code)

    @app.errorhandler(ServiceError)
    def dependency_error(e):
        app.logger.warning("dependency failed: %s", e)
        return error(f"Service '{e.service}' is unavailable.", 503)

    return app


def error(message: str, status: int = 422):
    return jsonify(error=message), status


def payload() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def need_int(data: dict, key: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError):
        abort(422, f"'{key}' must be an integer.")
