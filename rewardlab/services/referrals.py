"""Реферальная программа: уровни, доля от заработка друга, бонус за активацию."""

from flask import request

from .. import config
from ..db import db
from .points import add_points, notify


def active_referrals(uid: int) -> int:
    return db().execute("SELECT COUNT(*) FROM users WHERE referred_by = ? AND ref_activated = 1",
                        (uid,)).fetchone()[0]


def ref_tier(active: int):
    """Текущий уровень и следующий (или None, если уровень максимальный)."""
    idx = max(i for i, t in enumerate(config.REF_TIERS) if active >= t[0])
    nxt = config.REF_TIERS[idx + 1] if idx + 1 < len(config.REF_TIERS) else None
    return config.REF_TIERS[idx], nxt


def credit_referrer(friend, amount: int) -> None:
    """Начислить пригласившему его долю от заработка друга."""
    ref_id = friend["referred_by"]
    if ref_id:
        rate = ref_tier(active_referrals(ref_id))[0][1]
        add_points(ref_id, max(1, round(amount * rate)), "referral", source=friend["id"])


def check_activation(friend) -> bool:
    """Разовые бонусы, когда приглашённый друг становится активным."""
    if not friend["referred_by"] or friend["ref_activated"]:
        return False
    claims = db().execute("SELECT COUNT(*) FROM events WHERE user_id = ? AND kind = 'claim'",
                          (friend["id"],)).fetchone()[0]
    if claims < config.REF_ACTIVATION_CLAIMS:
        return False
    ref_id   = friend["referred_by"]
    old_tier = ref_tier(active_referrals(ref_id))[0]
    cur = db().execute("UPDATE users SET ref_activated = 1 WHERE id = ? AND ref_activated = 0",
                       (friend["id"],))
    if cur.rowcount != 1:
        return False
    add_points(ref_id, config.REF_BONUS_INVITER, "ref_bonus", source=friend["id"])
    add_points(friend["id"], config.REF_BONUS_FRIEND, "welcome_bonus")
    notify(ref_id, f"🎉 {friend['username']} is now an active friend: +{config.REF_BONUS_INVITER} points!")
    new_tier = ref_tier(active_referrals(ref_id))[0]
    if new_tier != old_tier:
        notify(ref_id, f"⬆️ Level up! You are now {new_tier[2]}: "
                       f"{int(new_tier[1] * 100)}% of your friends' earnings.")
    return True


def invite_link(u) -> str:
    return f"{request.host_url}register?ref={u['ref_code']}"
