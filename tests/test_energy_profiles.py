"""The energy profile must do what it promises: fewer requests when economical, more when aggressive."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer import config as config_module  # noqa: E402
from twitch_drop_farmer.config import AppConfig  # noqa: E402
from twitch_drop_farmer.energy_profiles import (  # noqa: E402
    AVAILABLE_PROFILES,
    PROFILE_AGGRESSIVE,
    PROFILE_BALANCED,
    PROFILE_ECONOMIC,
    get_default_profile,
    get_profile_by_name,
)
from twitch_drop_farmer.farmer import FarmEngine  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, StreamCandidate  # noqa: E402

UTC = timezone.utc


class _Clock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now


def _campaigns(count: int) -> list[DropCampaign]:
    now = datetime.now(UTC)
    return [
        DropCampaign(
            id=f"c{i:03d}", game_name=f"G{i:03d}", title="t", starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1 + i % 9), status="ACTIVE", required_minutes=120, progress_minutes=10,
            has_watchable_drops=True,
            drops=[{"id": f"d{i}", "name": "r", "required_minutes": 120, "current_minutes": 10, "claimed": False}],
        )
        for i in range(count)
    ]


def _engine(profile_name: str, campaigns: list[DropCampaign]) -> tuple[FarmEngine, MagicMock, _Clock]:
    client = MagicMock()
    client.consume_diagnostics.side_effect = lambda: []
    client.fetch_campaigns.side_effect = lambda **_kw: list(campaigns)
    client.fetch_streams.side_effect = lambda c: [
        StreamCandidate(login=f"{c.id}-chan", display_name="x", game_name=c.game_name, viewer_count=50,
                        drops_enabled=True, channel_id="1")
    ]
    clock = _Clock()
    return FarmEngine(client, AppConfig(watchdog_enabled=False, energy_profile=profile_name), clock=clock), client, clock


class TestProfileData(unittest.TestCase):
    def test_each_step_is_more_economical_than_the_next_more_reactive_one(self):
        eco, bal, agg = PROFILE_ECONOMIC, PROFILE_BALANCED, PROFILE_AGGRESSIVE
        for field in ("poll_interval_sec", "campaign_refresh_sec", "front_ttl_sec", "background_ttl_sec",
                      "watchdog_stall_timeout_min"):
            with self.subTest(field):
                self.assertGreater(getattr(eco, field), getattr(bal, field))
                self.assertGreater(getattr(bal, field), getattr(agg, field))

    def test_balanced_is_exactly_what_the_app_did_before_profiles_had_any_effect(self):
        self.assertEqual(PROFILE_BALANCED.poll_interval_sec, 120)
        self.assertEqual(PROFILE_BALANCED.campaign_refresh_sec, FarmEngine.CAMPAIGN_REFRESH_SEC)
        self.assertEqual(PROFILE_BALANCED.front_ttl_sec, FarmEngine.FRONT_TTL_SEC)
        self.assertEqual(PROFILE_BALANCED.background_ttl_sec, FarmEngine.BACKGROUND_TTL_SEC)
        self.assertEqual(PROFILE_BALANCED.watchdog_stall_timeout_min, 30)
        self.assertIs(get_default_profile(), PROFILE_BALANCED)

    def test_profiles_are_found_by_name_ignoring_case(self):
        self.assertIs(get_profile_by_name("agressivo"), PROFILE_AGGRESSIVE)
        self.assertIsNone(get_profile_by_name("nonexistent"))

    def test_the_fields_nobody_read_are_gone(self):
        for dead in ("polling_interval_sec", "api_timeout_sec", "stream_check_timeout_sec", "log_level",
                     "enable_aggressive_retry"):
            self.assertFalse(hasattr(PROFILE_BALANCED, dead), dead)

    def test_an_old_config_file_with_the_removed_interval_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "config.json"
            file.write_text(json.dumps({"auto_switch_interval_sec": 120, "energy_profile": "Agressivo"}), encoding="utf-8")
            with patch.object(config_module, "CONFIG_FILE", file):
                cfg = config_module.load_config()

        self.assertEqual(cfg.energy_profile, "Agressivo")
        self.assertFalse(hasattr(cfg, "auto_switch_interval_sec"))


class TestEngineFollowsTheProfile(unittest.TestCase):
    def test_the_engine_takes_the_profile_from_the_config(self):
        for profile in AVAILABLE_PROFILES:
            with self.subTest(profile.name):
                engine, _, _ = _engine(profile.name, _campaigns(3))

                self.assertEqual(engine.campaign_refresh_sec, profile.campaign_refresh_sec)
                self.assertEqual(engine.front_ttl_sec, profile.front_ttl_sec)
                self.assertEqual(engine.background_ttl_sec, profile.background_ttl_sec)

    def test_an_unknown_profile_name_falls_back_to_the_default(self):
        engine, _, _ = _engine("Nonexistent", _campaigns(3))

        self.assertEqual(engine.campaign_refresh_sec, PROFILE_BALANCED.campaign_refresh_sec)

    def test_changing_the_profile_changes_how_long_the_campaign_list_is_reused(self):
        for profile, should_refetch in ((PROFILE_ECONOMIC, False), (PROFILE_BALANCED, True), (PROFILE_AGGRESSIVE, True)):
            with self.subTest(profile.name):
                engine, client, clock = _engine("Balanceado", _campaigns(3))
                engine.apply_profile(profile)
                engine.poll()

                clock.now += 700  # past 10 min, well before 30 min
                engine.poll()

                self.assertEqual(client.fetch_campaigns.call_count, 2 if should_refetch else 1)

    def test_the_next_candidates_are_rechecked_sooner_when_aggressive_and_later_when_economical(self):
        for profile, rechecked in ((PROFILE_ECONOMIC, False), (PROFILE_BALANCED, True), (PROFILE_AGGRESSIVE, True)):
            with self.subTest(profile.name):
                engine, client, clock = _engine("Balanceado", _campaigns(3))
                engine.apply_profile(profile)
                engine.poll()
                looked_up = client.fetch_streams.call_count

                clock.now += 400  # past the 300 s of Balanceado, before the 600 s of Económico
                engine.poll()

                self.assertEqual(client.fetch_streams.call_count > looked_up, rechecked)

    def test_the_promise_economical_asks_twitch_less_and_aggressive_more(self):
        """Requests per hour once started: directory lookups plus campaign-list fetches (the first hour also pays
        for looking every game up once, whatever the profile, so it is left out)."""
        def total(client: MagicMock) -> int:
            return client.fetch_streams.call_count + client.fetch_campaigns.call_count

        per_hour = {}
        for profile in AVAILABLE_PROFILES:
            engine, client, clock = _engine(profile.name, _campaigns(40))
            target = None
            after_warm_up = None
            for offset in range(0, 3 * 3600, profile.poll_interval_sec):
                clock.now = 10_000.0 + offset
                if after_warm_up is None and offset >= 3600:
                    after_warm_up = total(client)
                if target:
                    engine.set_focus(target)
                snapshot = engine.poll()
                live = [d for d in snapshot.decisions if d.reason_code == "stream_selected"]
                if live and target is None:
                    target = live[0].campaign.id
            per_hour[profile.name] = (total(client) - after_warm_up) / 2

        self.assertLess(per_hour["Económico"], per_hour["Balanceado"])
        self.assertLess(per_hour["Balanceado"], per_hour["Agressivo"])
        self.assertGreater(per_hour["Balanceado"], 1.5 * per_hour["Económico"])
        self.assertGreater(per_hour["Agressivo"], 1.5 * per_hour["Balanceado"])


if __name__ == "__main__":
    unittest.main()
