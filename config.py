"""Простой конфиг приложения, читаемый из config.json.

Сейчас хранит только задержку обработки документов. Чтобы изменить задержку —
впишите число секунд в config.json -> "processing_delay_seconds" (можно дробное).
Значение читается на каждый запрос главной страницы, перезапуск не нужен.
"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = BASE_DIR / "config.json"

DEFAULTS = {
    "processing_delay_seconds": 10,
}


def load_config() -> dict:
    """Читает config.json, подставляя значения по умолчанию для отсутствующих ключей.
    Если файла нет — создаёт его со значениями по умолчанию."""
    data = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        try:
            CONFIG_FILE.write_text(
                json.dumps(DEFAULTS, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return {**DEFAULTS, **data}


def get_delay_seconds() -> float:
    """Задержка обработки документов в секундах (>= 0)."""
    try:
        val = float(load_config().get("processing_delay_seconds", 0))
    except (TypeError, ValueError):
        val = 0.0
    return max(0.0, val)
