from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


CONFIG_DIR = Path.home() / ".twitch-drop-farmer"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.json"


@dataclass(slots=True)
class AppConfig:
    theme: str = "twitch"
    whitelist_games: list[str] = field(default_factory=list)
    blacklist_games: list[str] = field(default_factory=list)
    blacklist_channels: list[str] = field(default_factory=list)
    auto_switch_interval_sec: int = 120


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return AppConfig(**data)


def save_config(cfg: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
