"""Сквозное событийное логирование приложения.

Пишет события и ошибки построчным JSON в app_events.jsonl (с ротацией по числу
строк) и дублирует в stdout, чтобы они были видны в `docker compose logs`.

Использование:
    from app_log import log_event, log_exception
    log_event("convert", message="Принято файлов: 3", files=3)
    try: ...
    except Exception as e: log_exception("convert_failed", e)

Страница /logs читает эти события через read_events().
"""
import json
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "app_events.jsonl"
MAX_LINES = 1000  # хранить последние N событий (обрезка при записи)

_lock = threading.Lock()


def log_event(event: str, level: str = "INFO", message: str = "", **fields) -> None:
    """Записывает одно событие. level: INFO | WARNING | ERROR."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "event": event,
        "message": message,
    }
    if fields:
        entry.update(fields)

    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        try:
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_LINES:
                LOG_FILE.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
        except OSError:
            pass

    # дублируем в stdout (видно в docker compose logs)
    print(f"[{entry['ts']}] {level:7} {event}: {message}".rstrip(), file=sys.stderr, flush=True)


def log_exception(event: str, exc: BaseException, **fields) -> None:
    """Записывает ошибку с трейсбэком (level=ERROR)."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_event(event, level="ERROR", message=f"{type(exc).__name__}: {exc}", error=tb, **fields)


def read_events(limit: int = 500) -> list[dict]:
    """Возвращает события, новые сверху (до limit штук)."""
    if not LOG_FILE.exists():
        return []
    out = []
    try:
        for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    out.reverse()
    return out[:limit]


def clear_events() -> None:
    """Полностью очищает файл лога."""
    with _lock:
        try:
            LOG_FILE.write_text("", encoding="utf-8")
        except OSError:
            pass
