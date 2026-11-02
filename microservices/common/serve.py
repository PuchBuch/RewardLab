"""Запуск сервиса на production-сервере waitress (работает и в Windows, и в Docker)."""

import os

from waitress import serve

from .client import PORTS


def run(app, name: str) -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv(f"{name.upper()}_PORT") or PORTS[name])
    print(f"RewardLab {name}: http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=8)
