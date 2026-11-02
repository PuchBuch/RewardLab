"""HTTP-клиент для вызовов между сервисами. Каждый запрос несёт служебный токен."""

import os

import requests

HEADER  = "X-Internal-Token"
PORTS   = {"gateway": 5000, "auth": 5001, "wallet": 5002, "games": 5003, "community": 5004}
TIMEOUT = 5
transport = None   # тесты подменяют: функция (service, method, path, json, params) -> (status, data)


class ServiceError(Exception):
    """Сервис ответил ошибкой (status 4xx/5xx) или недоступен (503)."""

    def __init__(self, service: str, status: int, data=None):
        self.service, self.status = service, status
        self.message = data.get("error", "") if isinstance(data, dict) else ""
        super().__init__(f"{service}: {status} {self.message}")


def url(service: str) -> str:
    return os.getenv(f"{service.upper()}_URL") or f"http://127.0.0.1:{PORTS[service]}"


def call(service: str, method: str, path: str, json=None, params=None) -> dict:
    if transport:
        status, data = transport(service, method, path, json, params)
    else:
        try:
            r = requests.request(method, url(service) + path, json=json, params=params, timeout=TIMEOUT,
                                 headers={HEADER: os.getenv("INTERNAL_TOKEN", "")})
        except requests.RequestException:
            raise ServiceError(service, 503, {"error": "service unavailable"}) from None
        status = r.status_code
        try:
            data = r.json()
        except ValueError:
            data = {}
    if status >= 400:
        raise ServiceError(service, status, data)
    return data


def get(service: str, path: str, **params) -> dict:
    return call(service, "GET", path, params=params or None)


def post(service: str, path: str, json: dict | None = None) -> dict:
    return call(service, "POST", path, json=json or {})


def delete(service: str, path: str) -> dict:
    return call(service, "DELETE", path)
