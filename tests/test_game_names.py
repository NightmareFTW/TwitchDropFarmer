"""Game names polluted by a registry card's status text, and the CurrentDrop lag handling."""
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
from twitch_drop_farmer.game_names import clean_game_name, clean_game_names  # noqa: E402
from twitch_drop_farmer.twitch_client import TwitchClient  # noqa: E402
from twitch_drop_farmer.ui import (  # noqa: E402
    INVENTORY_LAG_FORCE_MINUTES,
    MainWindow,
    _effective_dashboard_game_names,
    _normalize_dashboard_game_name,
)

UTC = timezone.utc

POLLUTED = {
    "Epic Seven Expired 15": "Epic Seven",
    "HITMAN World of Assassination Expired 14": "HITMAN World of Assassination",
    "HITMAN World of Assassination 1 drop · in 4 days": "HITMAN World of Assassination",
    "Grand Theft Auto VI Coming Soon Releases Nov 19 2026 ·": "Grand Theft Auto VI",
    "Planet Zoo 2 3 drops - ends in 2 days": "Planet Zoo 2",
    "Some Game 1 drop": "Some Game",
    "  Spaced    Out  Game  ": "Spaced Out Game",
}

ORDINARY = [
    "Half-Life 2", "Borderlands 4", "Tom Clancy's The Division 2", "Anno 117: Pax Romana",
    "ARK: Survival Evolved", "Planet Zoo 2", "Diablo IV", "Pokémon Trading Card Game Live",
    "Vampire: The Masquerade - Bloodhunt", "Counter-Strike 2", "Dota 2", "Don't Starve Together",
    "Marbles on Stream", "Coin Pusher Live!", "MARVEL SNAP", "Mongil: Star Dive", "NTE: Neverness to Everness",
    "Black Desert", "Where Winds Meet", "007 First Light", "Epic Seven",
]


class TestCleanGameName(unittest.TestCase):
    def test_the_names_seen_in_a_real_log_are_cleaned(self):
        for dirty, clean in POLLUTED.items():
            self.assertEqual(clean_game_name(dirty), clean, dirty)

    def test_ordinary_names_are_left_alone(self):
        for name in ORDINARY:
            self.assertEqual(clean_game_name(name), name)

    def test_cleaning_twice_changes_nothing(self):
        for dirty in POLLUTED:
            once = clean_game_name(dirty)
            self.assertEqual(clean_game_name(once), once)

    def test_a_name_that_is_only_noise_is_not_emptied(self):
        self.assertEqual(clean_game_name("Expired 15"), "Expired 15")
        self.assertEqual(clean_game_name(""), "")

    def test_duplicates_created_by_cleaning_are_merged_in_order(self):
        names = ["HITMAN World of Assassination", "Epic Seven Expired 15", "HITMAN World of Assassination Expired 14",
                 "hitman world of assassination 1 drop · in 4 days", "Epic Seven"]
        self.assertEqual(clean_game_names(names), ["HITMAN World of Assassination", "Epic Seven"])


class TestWhereItIsApplied(unittest.TestCase):
    def test_a_saved_whitelist_is_cleaned_when_the_config_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "config.json"
            file.write_text(json.dumps({
                "whitelist_games": ["Epic Seven Expired 15", "Epic Seven", "MARVEL SNAP"],
                "blacklist_games": ["HITMAN World of Assassination 1 drop · in 4 days"],
            }), encoding="utf-8")
            with patch.object(config_module, "CONFIG_FILE", file):
                cfg = config_module.load_config()

        self.assertEqual(cfg.whitelist_games, ["Epic Seven", "MARVEL SNAP"])
        self.assertEqual(cfg.blacklist_games, ["HITMAN World of Assassination"])

    def test_the_dashboard_merges_polluted_and_clean_names(self):
        self.assertEqual(_normalize_dashboard_game_name("Epic Seven Expired 15"), "Epic Seven")
        self.assertEqual(
            _effective_dashboard_game_names(["HITMAN X", "HITMAN X Expired 14", "HITMAN X 1 drop · in 4 days"]),
            ["HITMAN X"],
        )

    def test_a_registry_card_with_status_text_in_its_title_gives_the_real_name(self):
        client = TwitchClient()
        html = '<div class="sb-name-title">HITMAN World of Assassination 1 drop · in 4 days</div>'

        self.assertEqual(client._registry_card_game_name(html), "HITMAN World of Assassination")

    def test_polluted_registry_entries_in_the_disk_cache_are_dropped_and_clean_ones_kept(self):
        client = TwitchClient()

        def entry(game: str, campaign_id: str) -> dict:
            campaign = client._campaign_from_jsonable(client._campaign_to_jsonable(_registry_campaign(game, campaign_id)))
            return client._campaign_to_jsonable(campaign)

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "campaign_cache.json"
            cache.write_text(json.dumps([
                entry("Epic Seven Expired 15", "external-dirty"),
                entry("MARVEL SNAP", "external-clean"),
            ]), encoding="utf-8")
            client._campaign_cache.clear()
            with patch("twitch_drop_farmer.twitch_client.CAMPAIGN_CACHE_FILE", cache):
                client._load_campaign_cache()

        self.assertEqual(list(client._campaign_cache), ["external-clean"])
        self.assertTrue(any("nome sujo" in note for note in client.consume_diagnostics()))


def _registry_campaign(game: str, campaign_id: str):
    from twitch_drop_farmer.models import DropCampaign

    now = datetime.now(UTC)
    campaign = DropCampaign(
        id=campaign_id, game_name=game, title=game, starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(days=20), status="ACTIVE",
    )
    campaign.source = "external_registry"
    return campaign


class TestInventoryLag(unittest.TestCase):
    def _beat(self, *, inventory: int, current_drop: int, fake: MagicMock | None = None) -> MagicMock:
        """One heartbeat whose Inventory still says ``inventory`` while CurrentDrop says ``current_drop``."""
        keep_count = fake is not None
        fake = fake if fake is not None else MagicMock()
        future = MagicMock()
        future.done.return_value = True
        reconciled = MagicMock(progress_minutes=inventory, required_minutes=360, id="cid")
        future.result.return_value = (True, [], reconciled, {"drop_id": "d1", "current_minutes": current_drop})
        fake._heartbeat_future = future
        fake._heartbeat_pending_campaign_id = "cid"
        if not keep_count:
            fake._heartbeat_no_progress_cycles = 0
        fake._apply_reconciled_campaign_progress.return_value = (inventory, "cid")
        MainWindow._poll_heartbeat_future(fake)
        return fake

    def test_a_one_minute_lag_does_not_force_a_full_refresh(self):
        """Regression: it used to rebuild everything, including the call Twitch rejects for integrity."""
        fake = self._beat(inventory=160, current_drop=161)

        fake.refresh_snapshot.assert_not_called()
        self.assertEqual(fake._heartbeat_no_progress_cycles, 0)
        self.assertTrue(any("atraso normal" in call.args[0] for call in fake._log.call_args_list))

    def test_a_gap_of_two_minutes_is_still_normal(self):
        fake = self._beat(inventory=160, current_drop=162)

        fake.refresh_snapshot.assert_not_called()

    def test_a_bigger_gap_means_the_inventory_is_stuck_and_does_force_a_refresh(self):
        fake = self._beat(inventory=160, current_drop=160 + INVENTORY_LAG_FORCE_MINUTES)

        fake.refresh_snapshot.assert_called_once_with(force=True)

    def test_when_both_agree_the_stall_counter_still_counts(self):
        fake = self._beat(inventory=164, current_drop=164)

        fake.refresh_snapshot.assert_not_called()
        self.assertEqual(fake._heartbeat_no_progress_cycles, 1)

    def _fake_on_campaign(self, campaign_id: str, game: str, idle_beats: int) -> MagicMock:
        fake = MagicMock()
        fake._streamless_campaign_id, fake._streamless_game = campaign_id, game
        fake._forced_farm_campaign_id, fake._forced_farm_game = "", ""
        fake.latest_snapshot = None
        fake._heartbeat_no_progress_cycles = idle_beats
        return fake

    def _switch_to(self, fake: MagicMock, campaign_id: str, game: str) -> None:
        from twitch_drop_farmer.models import FarmDecision

        decision = MagicMock(spec=FarmDecision)
        decision.campaign = MagicMock(id=campaign_id, game_name=game)
        MainWindow._note_target_switch(fake, decision)

    def test_idle_heartbeats_of_the_campaign_that_was_left_do_not_bring_the_refresh_forward_on_the_next(self):
        """Seen in the 2.2.66 log: 2 idle heartbeats on one campaign, a switch, 1 idle heartbeat on the next, and
        the farm forced a full refresh as if the new campaign had 3 in a row."""
        fake = self._fake_on_campaign("old", "Old Game", idle_beats=2)
        self._switch_to(fake, "new", "New Game")

        self._beat(inventory=40, current_drop=40, fake=fake)

        fake.refresh_snapshot.assert_not_called()
        self.assertEqual(fake._heartbeat_no_progress_cycles, 1)

    def test_three_idle_heartbeats_on_the_same_campaign_still_force_the_refresh(self):
        """The safeguard itself must keep working: 3 in a row, no switch in between."""
        fake = self._fake_on_campaign("same", "Same Game", idle_beats=0)

        for _ in range(3):
            self._switch_to(fake, "same", "Same Game")  # the app notes the target on every cycle
            self._beat(inventory=40, current_drop=40, fake=fake)

        fake.refresh_snapshot.assert_called_once_with(force=True)


if __name__ == "__main__":
    unittest.main()
