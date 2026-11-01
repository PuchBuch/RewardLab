"""
RewardLab Demo — точка входа.
Код приложения лежит в пакете rewardlab/ (структура описана в README.md).

Запуск:
    python app.py                            # http://127.0.0.1:5000
Админ-панель (/admin): права выдаются только из консоли, вход по паролю + коду TOTP:
    python app.py make-admin <username>      # выдать права и показать ключ для аутентификатора
    python app.py remove-admin <username>
"""

import os
import sys

from rewardlab import create_app
from rewardlab.cli import admin_command

app = create_app()

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("make-admin", "remove-admin"):
        admin_command(app.config["DATABASE"], sys.argv[1], sys.argv[2])
        sys.exit()
    port = int(os.getenv("PORT", "5000"))
    print(f"RewardLab demo: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
