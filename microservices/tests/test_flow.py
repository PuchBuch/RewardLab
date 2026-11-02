"""Сквозной тест: все пять сервисов в одном процессе, вызовы между ними идут через тестовые клиенты Flask.

    cd microservices
    python -m tests.test_flow        (или: python -m pytest tests)
"""

import os
import re
import sys
import time
import sqlite3
import tempfile

TOKEN = "test-internal-token"
os.environ["INTERNAL_TOKEN"] = TOKEN
os.environ["APP_SECRET"] = "test-secret"

from common import client                       # noqa: E402
from auth.app import create_app as auth_app     # noqa: E402
from auth.cli import admin_command              # noqa: E402
from auth import totp                           # noqa: E402
from wallet.app import create_app as wallet_app  # noqa: E402
from games.app import create_app as games_app   # noqa: E402
from games import lucky                         # noqa: E402
from community.app import create_app as community_app  # noqa: E402
from gateway.app import create_app as gateway_app      # noqa: E402
from gateway import captcha                     # noqa: E402

TMP = tempfile.mkdtemp()
APPS = {name: make({"DATABASE": os.path.join(TMP, f"{name}.db"), "INTERNAL_TOKEN": TOKEN})
        for name, make in (("auth", auth_app), ("wallet", wallet_app), ("games", games_app),
                           ("community", community_app))}
CLIENTS = {name: app.test_client() for name, app in APPS.items()}
DOWN = set()                                    # «выключенные» сервисы для проверки сбоев


def transport(service, method, path, json, params):
    if service in DOWN:
        return 503, {"error": "service unavailable"}
    r = CLIENTS[service].open(path, method=method, json=json, query_string=params,
                              headers={client.HEADER: TOKEN})
    return r.status_code, r.get_json(silent=True) or {}


client.transport = transport
web_app = gateway_app()


def browser(ip):
    c = web_app.test_client()
    c.environ_base["REMOTE_ADDR"] = ip
    return c


def csrf(c, path="/rules"):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', c.get(path).get_data(as_text=True)).group(1)


def register(c, name, ref=""):
    return c.post("/register", data={"csrf": csrf(c, "/register"), "username": name, "password": "password123",
                                     "terms": "1", "ref": ref}, follow_redirects=True)


def page(c, path):
    r = c.get(path)
    assert r.status_code == 200, (path, r.status_code)
    return r.get_data(as_text=True)


def balance(uid):
    return CLIENTS["wallet"].get(f"/balance/{uid}", headers={client.HEADER: TOKEN}).get_json()["points"]


def reset_cooldown(uid):
    conn = sqlite3.connect(APPS["games"].config["DATABASE"])
    conn.execute("UPDATE claims SET last_claim_at = 0 WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()


def test_internal_token_required():
    for name, c in CLIENTS.items():
        assert c.get("/health").status_code == 200
        assert c.get("/stats").status_code == 401, name
        assert c.get("/stats", headers={client.HEADER: "wrong"}).status_code == 401


def test_full_flow():
    real_check, real_roll = captcha.check, lucky.roll
    captcha.check = lambda answer: True
    try:
        # Регистрация и реферал (разные публичные IP, иначе приглашение не засчитается)
        anna = browser("8.8.8.1")
        assert "Welcome!" in register(anna, "anna").get_data(as_text=True)
        anna_uid = 1
        ref_code = CLIENTS["auth"].get("/users/1", headers={client.HEADER: TOKEN}).get_json()["ref_code"]
        ben = browser("8.8.8.2")
        register(ben, "ben", ref_code)
        assert "ben joined with your invite" in page(anna, "/dashboard")

        # Приглашение из той же сети не засчитывается
        clone = browser("8.8.8.1")
        assert "invite was not counted" in register(clone, "anna_clone", ref_code).get_data(as_text=True)

        # Занятое имя и неверный пароль
        assert "That username is taken." in register(browser("8.8.8.9"), "ANNA").get_data(as_text=True)
        bad = browser("8.8.8.10")
        r = bad.post("/login", data={"csrf": csrf(bad, "/login"), "username": "anna", "password": "nope12345"})
        assert "Invalid username or password." in r.get_data(as_text=True)

        # Ежечасный бросок: число 9990 → 250 + 1 за серию, пригласившему 10%
        lucky.roll = lambda: 9990
        r = ben.post("/claim", data={"csrf": csrf(ben, "/dashboard"), "captcha": "x"}, follow_redirects=True)
        assert "Lucky number 9990: +250 points, +1 streak bonus" in r.get_data(as_text=True)
        assert balance(2) == 251 and balance(anna_uid) == 25
        r = ben.post("/claim", data={"csrf": csrf(ben, "/dashboard"), "captcha": "x"}, follow_redirects=True)
        assert "not ready yet" in r.get_data(as_text=True)
        assert balance(2) == 251

        # Активация друга после 3-й награды: бонусы обоим
        for _ in range(2):
            reset_cooldown(2)
            r = ben.post("/claim", data={"csrf": csrf(ben, "/dashboard"), "captcha": "x"}, follow_redirects=True)
        assert "You are now an active member: +25 welcome bonus" in r.get_data(as_text=True)
        assert balance(2) == 251 * 3 + 25
        assert balance(anna_uid) == 25 * 3 + 50
        assert "is now an active friend" in page(anna, "/dashboard")
        friends = page(anna, "/referrals")
        assert "ben" in friends and "Active" in friends and "+125" in friends

        # Сбой wallet во время броска: бросок возвращается, баллы не теряются
        reset_cooldown(2)
        DOWN.add("wallet")
        assert ben.post("/claim", data={"csrf": csrf(ben, "/rules"), "captcha": "x"}).status_code == 503
        DOWN.discard("wallet")
        r = ben.post("/claim", data={"csrf": csrf(ben, "/dashboard"), "captcha": "x"}, follow_redirects=True)
        assert "Lucky number 9990" in r.get_data(as_text=True)

        # Викторина: один ответ в день
        q = page(ben, "/quiz")
        assert "Question of the day" in q
        before = balance(2)
        ben.post("/quiz", data={"csrf": csrf(ben, "/quiz"), "choice": "0"})
        assert "already answered" in page(ben, "/quiz")
        assert balance(2) in (before, before + 20)

        # Блэкджек: ставка списывается, раздача доигрывается, итог в истории
        before = balance(2)
        ben.post("/blackjack/deal", data={"csrf": csrf(ben, "/blackjack"), "bet": "25"})
        table = page(ben, "/blackjack")
        if "Hit" in table:
            assert balance(2) == before - 25
            ben.post("/blackjack/stand", data={"csrf": csrf(ben, "/blackjack")})
        assert "Recent hands" in page(ben, "/blackjack")
        state = CLIENTS["games"].get("/blackjack/2", headers={client.HEADER: TOKEN}).get_json()
        assert state["stats"]["hands"] == 1
        assert balance(2) == before - 25 + state["game"]["payout"]
        assert ben.post("/blackjack/deal", data={"csrf": csrf(ben, "/blackjack"), "bet": "7"},
                        follow_redirects=True).status_code == 200
        assert CLIENTS["games"].get("/blackjack/2", headers={client.HEADER: TOKEN}).get_json()["stats"]["hands"] == 1

        # Публичные страницы
        for path in ("/", "/leaderboard", "/leaderboard?tab=inviters", "/leaderboard?tab=week", "/rules", "/legal"):
            page(anna, path)
        assert "anna" in page(anna, "/leaderboard?tab=inviters")
        assert "9885" in page(anna, "/rules")

        # Админка: 404 для обычных, вход по паролю + TOTP, начисление, бан
        assert anna.get("/admin").status_code == 404
        admin_command(APPS["auth"].config["DATABASE"], "make-admin", "anna")
        assert anna.get("/admin").status_code == 302
        conn = sqlite3.connect(APPS["auth"].config["DATABASE"])
        secret = conn.execute("SELECT totp_secret FROM users WHERE id = 1").fetchone()[0]
        conn.close()
        code = totp.code_at(secret, int(time.time()) // 30)
        r = anna.post("/admin/verify", data={"csrf": csrf(anna, "/admin/verify"), "password": "password123", "code": code})
        assert r.status_code == 302 and r.headers["Location"].endswith("/admin")
        admin_page = page(anna, "/admin")
        assert "ben" in admin_page and "signed_in" in admin_page
        anna.post("/admin/user/2/adjust", data={"csrf": csrf(anna, "/admin"), "amount": "-100000", "reason": "test"})
        assert balance(2) == 0
        assert "adjusted your points" in page(ben, "/dashboard")
        anna.post("/admin/user/2/ban", data={"csrf": csrf(anna, "/admin")})
        assert ben.get("/dashboard").status_code == 302
        assert "suspended" in ben.post("/login", data={"csrf": csrf(ben, "/login"), "username": "ben",
                                                      "password": "password123"}).get_data(as_text=True)
        page(anna, "/admin/user/2")

        # Удаление аккаунта убирает данные во всех сервисах
        clone.post("/delete-account", data={"csrf": csrf(clone, "/dashboard")})
        assert CLIENTS["auth"].get("/users/3", headers={client.HEADER: TOKEN}).status_code == 404

        # Сервис упал → понятная страница 503, а не трассировка
        DOWN.add("community")
        assert anna.get("/dashboard").status_code == 503
        DOWN.discard("community")
    finally:
        captcha.check, lucky.roll = real_check, real_roll


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for test in (test_internal_token_required, test_full_flow):
        test()
        print("ok", test.__name__)
    print("all passed")
