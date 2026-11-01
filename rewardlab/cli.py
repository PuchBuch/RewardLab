"""Консольные команды: выдача и снятие прав администратора."""

import sys
import sqlite3

from .services import totp


def admin_command(db_path: str, cmd: str, username: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # эмодзи в консоли Windows
    conn = sqlite3.connect(db_path)
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
