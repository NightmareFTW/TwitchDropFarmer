from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
from pathlib import Path


CONFIG_DIR = Path.home() / ".twitch-drop-farmer"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.json"


@dataclass(slots=True)
class AppConfig:
    theme: str = "twitch"
    language: str = "pt_PT"
    sort_mode: str = "ending_soonest"
    whitelist_games: list[str] = field(default_factory=list)
    blacklist_games: list[str] = field(default_factory=list)
    whitelist_channels: list[str] = field(default_factory=list)
    blacklist_channels: list[str] = field(default_factory=list)
    auto_switch_interval_sec: int = 120
    auto_claim_drops: bool = False
    auth_mode: str = "token"  # "token" ou "session"
    # v2 features
    energy_profile: str = "Balanceado"  # Energy profile name
    watchdog_enabled: bool = True  # Enable automatic recovery
    watchdog_stall_timeout_min: int = 30  # Stall timeout
    alert_campaign_expiring: bool = True
    alert_token_invalid: bool = True
    alert_no_progress: bool = True
    alert_farm_complete: bool = True
    auto_update_enabled: bool = True  # Enable automatic update + restart
    auto_update_restart_delay_sec: int = 30  # Wait before auto-restart
    check_updates_on_startup: bool = True
    dashboard_hide_subscription_required: bool = False


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    valid_keys = {item.name for item in fields(AppConfig)}
    filtered = {key: value for key, value in data.items() if key in valid_keys}
    return AppConfig(**filtered)


def save_config(cfg: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
