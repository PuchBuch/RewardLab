"""Капча из 5 цифр. Цифры рисуются линиями (не текстом), поэтому их нельзя просто прочитать из SVG.
В сессии хранится только HMAC кода: cookie Flask подписана, но не зашифрована."""

import hmac
import hashlib
import secrets

from flask import current_app, session

LENGTH = 5
_rng = secrets.SystemRandom()

# Цифры как ломаные в поле 10×16
GLYPHS = {
    "0": [[(0, 0), (10, 0), (10, 16), (0, 16), (0, 0)], [(10, 0), (0, 16)]],
    "1": [[(2, 4), (6, 0), (6, 16)], [(2, 16), (10, 16)]],
    "2": [[(0, 3), (3, 0), (8, 0), (10, 3), (10, 6), (0, 16), (10, 16)]],
    "3": [[(0, 0), (10, 0), (4, 7), (10, 10), (10, 14), (7, 16), (0, 16)]],
    "4": [[(8, 16), (8, 0), (0, 11), (10, 11)]],
    "5": [[(10, 0), (0, 0), (0, 7), (7, 7), (10, 10), (10, 14), (7, 16), (0, 16)]],
    "6": [[(9, 0), (3, 0), (0, 4), (0, 16), (10, 16), (10, 8), (0, 8)]],
    "7": [[(0, 0), (10, 0), (3, 16)]],
    "8": [[(0, 0), (10, 0), (10, 7), (0, 7), (0, 0)], [(0, 7), (0, 16), (10, 16), (10, 7)]],
    "9": [[(10, 8), (0, 8), (0, 0), (10, 0), (10, 12), (6, 16), (1, 16)]],
}
COLORS = ["#0F766E", "#0284C7", "#B8894A", "#0E7490", "#7C5E2A"]


def _digest(code: str) -> str:
    return hmac.new(current_app.secret_key.encode(), f"captcha:{code}".encode(), hashlib.sha256).hexdigest()


def new_svg() -> str:
    """Создать новый код, запомнить его в сессии и вернуть картинку."""
    code = "".join(_rng.choice("0123456789") for _ in range(LENGTH))
    session["captcha"] = _digest(code)
    j = lambda d: _rng.uniform(-d, d)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 56" width="180" height="56">',
             '<rect width="180" height="56" rx="10" fill="#F6EAD0"/>']
    for _ in range(6):                                   # фоновые помехи
        parts.append(f'<path d="M{_rng.uniform(0, 180):.0f} {_rng.uniform(0, 56):.0f} '
                     f'Q{_rng.uniform(0, 180):.0f} {_rng.uniform(0, 56):.0f} {_rng.uniform(0, 180):.0f} {_rng.uniform(0, 56):.0f}" '
                     f'stroke="{_rng.choice(COLORS)}" stroke-opacity=".35" stroke-width="{_rng.uniform(1, 2.2):.1f}" fill="none"/>')
    for i, ch in enumerate(code):
        x, y = 18 + i * 31 + j(3), 12 + j(4)
        scale = _rng.uniform(1.6, 1.95)
        transform = f"translate({x:.1f} {y:.1f}) rotate({j(14):.0f} 5 8) scale({scale:.2f})"
        for line in GLYPHS[ch]:
            pts = " ".join(f"{px + j(.7):.1f},{py + j(.7):.1f}" for px, py in line)
            parts.append(f'<polyline points="{pts}" transform="{transform}" fill="none" stroke="{_rng.choice(COLORS)}" '
                         f'stroke-width="{_rng.uniform(1.1, 1.5):.2f}" stroke-linecap="round" stroke-linejoin="round"/>')
    for _ in range(18):                                  # точки поверх цифр
        parts.append(f'<circle cx="{_rng.uniform(0, 180):.0f}" cy="{_rng.uniform(0, 56):.0f}" r="{_rng.uniform(.8, 1.8):.1f}" '
                     f'fill="{_rng.choice(COLORS)}" fill-opacity=".6"/>')
    parts.append("</svg>")
    return "".join(parts)


def check(answer: str) -> bool:
    """Проверить ответ. Код одноразовый: после любой попытки нужен новый."""
    expected = session.pop("captcha", None)
    answer = (answer or "").strip()
    return bool(expected) and len(answer) == LENGTH and hmac.compare_digest(_digest(answer), expected)
