"""«Счастливое число» для ежечасной награды: выпадает 0..LUCKY_MAX, награда по таблице."""

import secrets

from .. import config


def roll() -> int:
    return secrets.randbelow(config.LUCKY_MAX + 1)


def prize(number: int) -> tuple[int, int]:
    """Номер строки таблицы и награда для выпавшего числа."""
    for i, (top, amount) in enumerate(config.LUCKY_TIERS):
        if number <= top:
            return i, amount
    raise ValueError(number)


def table() -> list[dict]:
    """Таблица для шаблонов: диапазоны «от–до» и награды."""
    rows, start = [], 0
    for top, amount in config.LUCKY_TIERS:
        rows.append({"start": start, "end": top, "amount": amount})
        start = top + 1
    return rows
