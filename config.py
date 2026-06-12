"""Настройки приложения, читаемые из переменных окружения (.env).

Сейчас хранит только задержку обработки документов. Чтобы изменить задержку —
впишите число секунд в .env -> PROCESSING_DELAY_SECONDS (можно дробное) и
пересоздайте контейнер: `docker compose up -d` (переменные окружения читаются
при старте контейнера, а не на лету).
"""
import os


def get_delay_seconds() -> float:
    """Задержка обработки документов в секундах (>= 0)."""
    try:
        val = float(os.getenv("PROCESSING_DELAY_SECONDS", "0"))
    except (TypeError, ValueError):
        val = 0.0
    return max(0.0, val)
