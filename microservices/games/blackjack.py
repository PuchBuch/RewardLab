"""Движок блэкджека. Шуз и закрытая карта дилера никогда не покидают сервис."""

import json
import secrets

from . import settings

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = "SHDC"
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
    shoe = [r + s for _ in range(settings.BJ_DECKS) for s in SUITS for r in RANKS]
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


def save(con, game: dict, version: int) -> bool:
    """Сохранить ход, только если раздачу никто не изменил параллельно."""
    cur = con.execute(
        "UPDATE bj_games SET bet = ?, shoe = ?, player = ?, dealer = ?, status = ?, result = ?, payout = ?, "
        "version = version + 1 WHERE id = ? AND version = ? AND status = 'playing'",
        (game["bet"], json.dumps(game["shoe"]), json.dumps(game["player"]), json.dumps(game["dealer"]),
         game["status"], game["result"], game["payout"], game["id"], version))
    return cur.rowcount == 1


def finish(game: dict) -> None:
    """Доиграть за дилера (если нужно) и определить исход. Выплату делает вызывающий код через wallet."""
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


def public(game: dict) -> dict:
    """Раздача для клиента: без шуза, закрытая карта дилера — null, пока идёт игра."""
    playing = game["status"] == "playing"
    dealer  = [None if playing and i == 1 else c for i, c in enumerate(game["dealer"])]
    out = {"id": game["id"], "status": game["status"], "bet": game["bet"], "player": game["player"], "dealer": dealer,
           "player_val": value(game["player"]),
           "dealer_val": value(game["dealer"][:1]) if playing else value(game["dealer"]),
           "result": game["result"], "payout": game["payout"], "outcome": None}
    if not playing:
        kind, title = OUTCOMES[game["result"]]
        net = game["payout"] - game["bet"]
        sub = {"win": f"+{net} points", "push": "Your bet is returned",
               "lose": f"−{game['bet']} points. Better luck next hand!"}[kind]
        out["outcome"] = {"kind": kind, "title": title, "sub": sub}
    return out
