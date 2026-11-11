"""Energy profiles: how many requests the app makes to Twitch, and how fast it reacts.

A profile is a trade-off, and every value in it is really used:

* ``poll_interval_sec``: how often the app re-checks the channel being farmed (and tops up
  the list of the next candidates). A shorter interval notices a channel going offline
  sooner but asks Twitch more often.
* ``campaign_refresh_sec``: how long the campaign list (Inventory, dashboard, registry) is
  reused before it is fetched again.
* ``front_ttl_sec`` / ``background_ttl_sec``: how long the channel lookup of the next
  candidates, and of every other game (it only feeds the dashboard ribbons), is reused.
* ``watchdog_stall_timeout_min``: minutes without progress before the stall monitor gives up
  on a campaign (it restarts the channel watch and switches channel earlier, see
  farm_health.py).

The heartbeat (every ~59 s) and the video watcher are what Twitch counts as watching, so they
are the same in every profile. "Balanceado" is exactly what the app did before profiles had
any effect.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class EnergyProfile:
    """One setting of the requests/reactivity trade-off."""

    name: str
    poll_interval_sec: int
    campaign_refresh_sec: int
    front_ttl_sec: int
    background_ttl_sec: int
    watchdog_stall_timeout_min: int
    description: str = ""


PROFILE_ECONOMIC = EnergyProfile(
    name="Económico",
    poll_interval_sec=300,  # 5 min
    campaign_refresh_sec=1800,  # 30 min
    front_ttl_sec=600,
    background_ttl_sec=7200,
    watchdog_stall_timeout_min=45,
    description="Fewest requests. A channel that goes offline is noticed later.",
)

PROFILE_BALANCED = EnergyProfile(
    name="Balanceado",
    poll_interval_sec=120,  # 2 min
    campaign_refresh_sec=600,  # 10 min
    front_ttl_sec=300,
    background_ttl_sec=3600,
    watchdog_stall_timeout_min=30,
    description="Recommended. The default behaviour.",
)

PROFILE_AGGRESSIVE = EnergyProfile(
    name="Agressivo",
    poll_interval_sec=60,  # 1 min
    campaign_refresh_sec=300,  # 5 min
    front_ttl_sec=120,
    background_ttl_sec=1800,
    watchdog_stall_timeout_min=20,
    description="Reacts fastest, with the most requests.",
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
