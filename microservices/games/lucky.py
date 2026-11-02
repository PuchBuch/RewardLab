"""«Счастливое число» для ежечасной награды: выпадает 0..LUCKY_MAX, награда по таблице."""

import secrets

from . import settings


def roll() -> int:
    return secrets.randbelow(settings.LUCKY_MAX + 1)


def prize(number: int) -> tuple[int, int]:
    """Номер строки таблицы и награда для выпавшего числа."""
    for i, (top, amount) in enumerate(settings.LUCKY_TIERS):
        if number <= top:
            return i, amount
    raise ValueError(number)


def table() -> list[dict]:
    """Таблица для страниц: диапазоны «от–до» и награды."""
    out, start = [], 0
    for top, amount in settings.LUCKY_TIERS:
        out.append({"start": start, "end": top, "amount": amount})
        start = top + 1
    return out
