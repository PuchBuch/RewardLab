"""Движок блэкджека. Вся логика на сервере: шуз и закрытая карта дилера никогда не уходят в браузер."""

import json
import secrets

from .. import config
from ..db import db
from .points import add_points

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
OUTCOMES = {             # результат: (тон плашки, текст)
    "blackjack":   ("win",  "Blackjack! 🎉"),
    "win":         ("win",  "You win! 🥳"),
    "dealer_bust": ("win",  "Dealer busts! 🥳"),
    "push":        ("push", "Push 🤝"),
    "lose":        ("lose", "Dealer wins 😅"),
    "bust":        ("lose", "Bust! Over 21 😬"),
    "dealer_bj":   ("lose", "Dealer has blackjack 😮"),
}
_rng = secrets.SystemRandom()


def new_shoe() -> list:
    shoe = [r + s for _ in range(config.BJ_DECKS) for s in SUITS for r in RANKS]
    _rng.shuffle(shoe)
    return shoe


def value(cards: list) -> int:
    total, aces = 0, 0
    for c in cards:
        r = c[:-1]
        if r == "A":
            total, aces = total + 11, aces + 1
        else:
            total += 10 if r in ("J", "Q", "K") else int(r)
    while total > 21 and aces:
        total, aces = total - 10, aces - 1
    return total


def natural(cards: list) -> bool:
    return len(cards) == 2 and value(cards) == 21


def load(row) -> dict:
    game = dict(row)
    for k in ("shoe", "player", "dealer"):
        game[k] = json.loads(game[k])
    return game


def save(game: dict, version: int) -> bool:
    """Сохранить ход, только если раздачу никто не изменил параллельно."""
    cur = db().execute(
        "UPDATE bj_games SET bet = ?, shoe = ?, player = ?, dealer = ?, status = ?, result = ?, payout = ?, "
        "version = version + 1 WHERE id = ? AND version = ? AND status = 'playing'",
        (game["bet"], json.dumps(game["shoe"]), json.dumps(game["player"]), json.dumps(game["dealer"]),
         game["status"], game["result"], game["payout"], game["id"], version))
    return cur.rowcount == 1


def finish(game: dict) -> None:
    """Доиграть за дилера (если нужно), определить исход и выплатить выигрыш."""
    p = value(game["player"])
    if p > 21:
        result = "bust"
    else:
        if not natural(game["player"]):
            while value(game["dealer"]) < 17:          # дилер останавливается на любых 17
                game["dealer"].append(game["shoe"].pop())
        d = value(game["dealer"])
        pbj, dbj = natural(game["player"]), natural(game["dealer"])
        if pbj and dbj:
            result = "push"
        elif pbj:
            result = "blackjack"
        elif dbj:
            result = "dealer_bj"
        elif d > 21:
            result = "dealer_bust"
        elif p > d:
            result = "win"
        elif p == d:
            result = "push"
        else:
            result = "lose"
    bet = game["bet"]
    payout = {"blackjack": bet + bet * 3 // 2, "win": bet * 2, "dealer_bust": bet * 2, "push": bet}.get(result, 0)
    game.update(status="done", result=result, payout=payout)
    if payout:
        add_points(game["user_id"], payout, "blackjack_win")


def view_cards(cards: list, hide_hole: bool, new_from: int, delay_of) -> list:
    """Карты для шаблона. Закрытая карта дилера уходит без масти и номинала."""
    out = []
    for i, c in enumerate(cards):
        if hide_hole and i == 1:
            out.append({"hidden": True, "new": i >= new_from, "d": delay_of(i)})
        else:
            out.append({"r": c[:-1], "s": SUITS[c[-1]], "red": c[-1] in "HD", "hidden": False,
                        "new": i >= new_from, "d": delay_of(i)})
    return out
