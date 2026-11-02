"""Выдача и снятие прав администратора (только из консоли сервера):

    python -m auth.cli make-admin <username>
    python -m auth.cli remove-admin <username>
"""

import os
import sys
import sqlite3

from dotenv import load_dotenv

from common.store import ROOT, db_path

from . import totp


def admin_command(path: str, cmd: str, username: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # эмодзи в консоли Windows
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT id, username FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        print(f"User '{username}' not found. Register on the site first.")
        return
    if cmd == "make-admin":
        secret = totp.new_secret()
        conn.execute("UPDATE users SET is_admin = 1, totp_secret = ?, totp_last = 0 WHERE id = ?", (secret, row[0]))
        print(f"✅ {row[1]} is now an admin.\n")
        print("Add this key to your authenticator app (Google Authenticator, Authy, 1Password…):")
        print(f"   Key:  {secret}")
        print(f"   URI:  {totp.provisioning_uri(secret, row[1])}\n")
        print("Keep the key secret. Running make-admin again creates a new key and the old one stops working.")
    else:
        conn.execute("UPDATE users SET is_admin = 0, totp_secret = NULL WHERE id = ?", (row[0],))
        print(f"✅ {row[1]} is no longer an admin.")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    load_dotenv(os.path.join(ROOT, ".env"))
    if len(sys.argv) != 3 or sys.argv[1] not in ("make-admin", "remove-admin"):
        print(__doc__)
        sys.exit(1)
    admin_command(db_path("auth"), sys.argv[1], sys.argv[2])
