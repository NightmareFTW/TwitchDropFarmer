from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import os
from pathlib import Path

from .game_names import clean_game_names


CONFIG_DIR = Path.home() / ".twitch-drop-farmer"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.json"
# The session the user agreed to keep (see AppConfig.remember_session). It holds the login
# token in plain text, exactly like cookies.json, so it only exists after an explicit "yes".
SESSION_FILE = CONFIG_DIR / "session.json"
# Cached campaign catalog (non-secret metadata) so the full game list survives
# app restarts, instead of being empty until a browser-fallback fetch succeeds.
CAMPAIGN_CACHE_FILE = CONFIG_DIR / "campaign_cache.json"
# What the public registry says each game's active drops need (watch time or a subscription).
REGISTRY_REWARDS_FILE = CONFIG_DIR / "registry_rewards.json"


@dataclass(slots=True)
class AppConfig:
    theme: str = "twitch"
    language: str = "pt_PT"
    sort_mode: str = "ending_soonest"
    whitelist_games: list[str] = field(default_factory=list)
    blacklist_games: list[str] = field(default_factory=list)
    whitelist_channels: list[str] = field(default_factory=list)
    blacklist_channels: list[str] = field(default_factory=list)
    auto_claim_drops: bool = False
    auth_mode: str = "token"  # "token" ou "session"
    # v2 features
    energy_profile: str = "Balanceado"  # Energy profile name
    watchdog_enabled: bool = True  # Enable automatic recovery
    watchdog_stall_timeout_min: int = 30  # Stall timeout
    alert_campaign_expiring_soon: bool = True
    alert_token_invalid: bool = True
    alert_no_progress: bool = True
    alert_farm_complete: bool = True
    alert_stream_offline: bool = True
    alert_api_error: bool = True
    alert_watchdog_recovered: bool = True
    alert_drop_ready: bool = True
    auto_update_enabled: bool = False  # Not implemented: nothing downloads or installs an update by itself
    auto_update_restart_delay_sec: int = 30  # Wait before auto-restart
    check_updates_on_startup: bool = True
    dashboard_hide_subscription_required: bool = False
    remember_session: bool = False  # The user agreed to keep the session JSON so "Log in" can restore it


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    valid_keys = {item.name for item in fields(AppConfig)}
    filtered = {key: value for key, value in data.items() if key in valid_keys}
    # Names saved by older versions may carry a registry card's status text.
    for key in ("whitelist_games", "blacklist_games"):
        if isinstance(filtered.get(key), list):
            filtered[key] = clean_game_names(filtered[key])
    return AppConfig(**filtered)


def save_config(cfg: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
