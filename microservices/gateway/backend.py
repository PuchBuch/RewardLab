"""Обращения gateway к сервисам, которые нужны нескольким страницам."""

import time

from flask import request

from common import client

_info: dict = {}
INFO_TTL = 60


def info(service: str) -> dict:
    """Настройки сервиса для страниц (таблица призов, уровни, ставки). Кэш на минуту."""
    cached = _info.get(service)
    if cached is None or cached[0] < time.time() - INFO_TTL:
        cached = _info[service] = (time.time(), client.get(service, "/info"))
    return cached[1]


def names(ids) -> dict[int, str]:
    ids = sorted({int(i) for i in ids if i is not None})
    if not ids:
        return {}
    found = client.get("auth", "/users", ids=",".join(map(str, ids)))["names"]
    return {int(k): v for k, v in found.items()}


def with_names(items: list[dict], key: str = "user_id") -> list[dict]:
    """Добавить username к строкам; строки удалённых пользователей пропускаются."""
    found = names(i[key] for i in items)
    return [{**i, "username": found[i[key]]} for i in items if i[key] in found]


def balance(uid: int) -> int:
    return client.get("wallet", f"/balance/{uid}")["points"]


def delete_user(uid: int) -> None:
    """Удалить данные пользователя во всех сервисах. Auth последним: пока он жив, удаление можно повторить."""
    for service in ("community", "games", "wallet", "auth"):
        client.delete(service, f"/users/{uid}")


def invite_link(u: dict) -> str:
    return f"{request.host_url}register?ref={u['ref_code']}"
