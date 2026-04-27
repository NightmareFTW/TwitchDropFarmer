"""Energy profiles for customizable farming behavior."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class EnergyProfile:
    """Configuration profile for farming behavior."""

    name: str
    polling_interval_sec: int  # Heartbeat polling frequency
    campaign_refresh_sec: int  # Full campaign list refresh
    api_timeout_sec: int  # HTTP request timeout
    stream_check_timeout_sec: int  # Stream validation timeout
    watchdog_stall_timeout_min: int  # Stall timeout for watchdog recovery
    log_level: str  # "DEBUG", "INFO", "WARNING"
    enable_aggressive_retry: bool  # Retry failed requests aggressively
    description: str = ""


# Predefined profiles
PROFILE_ECONOMIC = EnergyProfile(
    name="Económico",
    polling_interval_sec=600,  # 10 min
    campaign_refresh_sec=3600,  # 1 hour
    api_timeout_sec=30,
    stream_check_timeout_sec=20,
    watchdog_stall_timeout_min=45,
    log_level="WARNING",
    enable_aggressive_retry=False,
    description="Minimal network/CPU usage. Best for low-power devices.",
)

PROFILE_BALANCED = EnergyProfile(
    name="Balanceado",
    polling_interval_sec=300,  # 5 min
    campaign_refresh_sec=1800,  # 30 min
    api_timeout_sec=20,
    stream_check_timeout_sec=15,
    watchdog_stall_timeout_min=30,
    log_level="INFO",
    enable_aggressive_retry=False,
    description="Recommended. Balanced responsiveness and resource usage.",
)

PROFILE_AGGRESSIVE = EnergyProfile(
    name="Agressivo",
    polling_interval_sec=120,  # 2 min
    campaign_refresh_sec=600,  # 10 min
    api_timeout_sec=15,
    stream_check_timeout_sec=10,
    watchdog_stall_timeout_min=20,
    log_level="DEBUG",
    enable_aggressive_retry=True,
    description="High responsiveness. May use more network/CPU.",
)

AVAILABLE_PROFILES = [PROFILE_ECONOMIC, PROFILE_BALANCED, PROFILE_AGGRESSIVE]


def get_profile_by_name(name: str) -> EnergyProfile | None:
    """Get profile by name, case-insensitive."""
    for profile in AVAILABLE_PROFILES:
        if profile.name.lower() == name.lower():
            return profile
    return None


def get_default_profile() -> EnergyProfile:
    """Return default profile."""
    return PROFILE_BALANCED
