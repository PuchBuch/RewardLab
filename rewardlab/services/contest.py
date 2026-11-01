"""Еженедельный конкурс приглашений."""

import datetime

from .. import config
from ..db import db, utc_now, now_iso
from .points import add_points, notify


def week_start(dt: datetime.datetime) -> datetime.datetime:
    d = dt.date() - datetime.timedelta(days=dt.weekday())
    return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)


def standings(start: datetime.datetime, limit: int = 20):
    """Кто больше всех привёл активных друзей за неделю. При равенстве выше тот, кто успел раньше."""
    end = start + datetime.timedelta(days=7)
    return db().execute(
        "SELECT u.id, u.username, COUNT(*) AS value, MAX(e.at) AS last FROM events e "
        "JOIN users u ON u.id = e.user_id WHERE e.kind = 'ref_bonus' AND e.at >= ? AND e.at < ? "
        "GROUP BY u.id ORDER BY value DESC, last ASC LIMIT ?",
        (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), limit)).fetchall()


_settled_week = None


def settle() -> None:
    """Раз в неделю выдать призы за прошлую неделю (атомарно, ровно один раз). Вызывается перед запросом."""
    global _settled_week
    prev = week_start(utc_now()) - datetime.timedelta(days=7)
    key  = prev.date().isoformat()
    if _settled_week == key:
        return
    d = db()
    cur = d.execute("INSERT OR IGNORE INTO contest_weeks (week, settled_at) VALUES (?, ?)", (key, now_iso()))
    if cur.rowcount == 1:
        for place, row in enumerate(standings(prev, len(config.CONTEST_PRIZES))):
            amount = config.CONTEST_PRIZES[place]
            add_points(row["id"], amount, "contest")
            d.execute("INSERT INTO contest_results (week, place, user_id, amount) VALUES (?, ?, ?, ?)",
                      (key, place + 1, row["id"], amount))
            notify(row["id"], f"🏆 You took place #{place + 1} in last week's invite contest: +{amount} points!")
    d.commit()
    _settled_week = key
