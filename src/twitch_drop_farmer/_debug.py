"""Campaign debug helper — activated by TDF_DEBUG_CAMPAIGNS=1."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path.home() / ".twitch-drop-farmer"
LOG_FILE = _LOG_DIR / "campaign_debug.log"

TARGET_GAMES: frozenset[str] = frozenset(
    {
        "world of warcraft",
        "nte: neverness to everness",
        "neverness to everness",
        "clair obscur: expedition 33",
        "the quinfall",
    }
)


def enabled() -> bool:
    return os.environ.get("TDF_DEBUG_CAMPAIGNS", "") == "1"


_last_write_error: str = ""


def log(message: str) -> None:
    global _last_write_error
    if not enabled():
        return
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")
        _last_write_error = ""
    except Exception as exc:
        _last_write_error = str(exc)


def get_write_error() -> str:
    """Return the last file-write error, or '' if the last write succeeded."""
    return _last_write_error


def is_target(game_name: str) -> bool:
    return game_name.casefold() in TARGET_GAMES
