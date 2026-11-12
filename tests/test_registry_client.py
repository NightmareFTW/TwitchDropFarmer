"""The client and the engine act on what the registry says (no network: pages come from fixtures)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer import twitch_client as tc  # noqa: E402
from twitch_drop_farmer.config import AppConfig  # noqa: E402
from twitch_drop_farmer.farmer import FarmEngine  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, StreamCandidate  # noqa: E402
from twitch_drop_farmer.registry_rewards import RewardSummary  # noqa: E402

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures" / "registry"
FIXED_NOW = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)  # the day the fixtures were taken


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW if tz is None else FIXED_NOW.astimezone(tz)


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


class _ClientCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.rewards_file = base / "registry_rewards.json"
        for name, value in (
            ("CONFIG_DIR", base),
            ("COOKIE_FILE", base / "cookies.json"),
            ("SESSION_FILE", base / "session.json"),
            ("CAMPAIGN_CACHE_FILE", base / "campaign_cache.json"),
            ("REGISTRY_REWARDS_FILE", self.rewards_file),
            ("COMPLETED_CAMPAIGNS_FILE", base / "completed_campaigns.json"),
        ):
            patcher = patch.object(tc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = self.new_client()

    def new_client(self) -> tc.TwitchClient:
        client = tc.TwitchClient()
        self.addCleanup(client.segment_watcher.stop)
        client._registry_pause_sec = 0
        self.fetched: list[str] = []

        def fetch(slug: str) -> str:
            self.fetched.append(slug)
            return self.pages.get(slug, fixture("captains-call"))

        client._registry_fetch_page = fetch
        return client

    pages = {
        "elden-ring": fixture("elden-ring"),
        "call-of-duty-modern-warfare-4": fixture("call-of-duty-modern-warfare-4"),
        "cyberpunk-2077": fixture("cyberpunk-2077"),
        "captains-call": fixture("captains-call"),
        "crimson-desert": fixture("crimson-desert"),
    }

    def registry_campaigns(self, html: str | None = None) -> list[DropCampaign]:
        home = html if html is not None else fixture("home_excerpt")
        with patch.object(tc, "datetime", FrozenDatetime), \
                patch.object(tc.requests, "get", return_value=MagicMock(status_code=200, text=home)):
            return self.client._campaigns_from_external_registry()

    def by_name(self, campaigns: list[DropCampaign]) -> dict[str, DropCampaign]:
        return {campaign.game_name: campaign for campaign in campaigns}


class TestCardsBecomeCampaigns(_ClientCase):
    def test_each_card_gets_the_dates_and_state_the_registry_gives(self):
        campaigns = self.by_name(self.registry_campaigns())

        elden = campaigns["ELDEN RING"]
        self.assertEqual(elden.status, "ACTIVE")
        self.assertEqual(elden.starts_at, datetime(2026, 11, 2, 7, 0, tzinfo=UTC))
        self.assertEqual(elden.ends_at, datetime(2026, 11, 30, 6, 59, 59, 999000, tzinfo=UTC))
        self.assertEqual(elden.source, "external_registry")
        self.assertEqual(elden.timestamp_source, "registry")
        self.assertEqual(campaigns["Eternal Return"].status, "UPCOMING")

    def test_a_campaign_history_card_is_expired_not_farmable(self):
        """It used to be ACTIVE for 30 days: the app looked for channels (and could farm) a game with no campaign."""
        fortnite = self.by_name(self.registry_campaigns())["Fortnite"]

        self.assertEqual(fortnite.status, "EXPIRED")
        self.assertFalse(fortnite.active)

    def test_a_coming_soon_card_without_dates_is_upcoming_not_active(self):
        """GTA VI: "Releases Nov 19, 2026"; the app had looked for its channels 9 times overnight."""
        gta = self.by_name(self.registry_campaigns())["Grand Theft Auto VI"]

        self.assertEqual(gta.status, "UPCOMING")
        self.assertTrue(gta.upcoming)
        self.assertFalse(gta.active)
        self.assertFalse(gta.timestamps_are_synthetic)  # so the engine never "repairs" it into an active one
        self.client.wait_for_registry_rewards(10)
        self.assertNotIn("grand-theft-auto-vi", self.fetched)  # nothing is read for it (no card data to compare)

    def test_games_ending_sooner_now_sort_before_games_ending_later(self):
        campaigns = self.by_name(self.registry_campaigns())

        self.assertLess(campaigns["Crimson Desert"].ends_at, campaigns["ELDEN RING"].ends_at)

    def test_a_card_that_says_nothing_keeps_the_old_open_window(self):
        html = '<html><a href="/game/mystery"><div class="sb-name-title">Mystery</div></a></html>'

        mystery = self.registry_campaigns(html)[0]

        self.assertEqual(mystery.status, "ACTIVE")
        self.assertEqual(mystery.timestamp_source, "")
        self.assertEqual(mystery.ends_at, FIXED_NOW + timedelta(days=30))
        self.assertIsNone(self.client._registry_thread)  # nothing to check: no background work either

    def test_the_card_schedule_helper_decides_by_the_clock(self):
        tag = '<a href="/game/x" data-start="2026-11-12T00:00:00Z" data-end="2026-11-13T00:00:00Z">'
        for now, expected in (
            (datetime(2026, 11, 11, tzinfo=UTC), "UPCOMING"),
            (datetime(2026, 11, 12, 12, tzinfo=UTC), "ACTIVE"),
            (datetime(2026, 11, 13, tzinfo=UTC), "EXPIRED"),
        ):
            with self.subTest(now=now):
                self.assertEqual(tc.TwitchClient._registry_card_schedule(tag, now)[2], expected)


class TestBackgroundSweep(_ClientCase):
    def sweep(self) -> list[DropCampaign]:
        campaigns = self.registry_campaigns()
        self.assertTrue(self.client.wait_for_registry_rewards(10))
        self.client.apply_registry_rewards(campaigns)
        return campaigns

    def test_subscription_only_games_are_marked_and_the_others_stay_farmable(self):
        campaigns = self.by_name(self.sweep())

        for game in ("ELDEN RING", "Call of Duty: Modern Warfare 4"):
            self.assertTrue(campaigns[game].requires_subscription, game)
            self.assertFalse(campaigns[game].has_watchable_drops, game)
        mixed = campaigns["Cyberpunk 2077"]
        self.assertFalse(mixed.requires_subscription)
        self.assertTrue(mixed.has_watchable_drops)
        self.assertFalse(campaigns["Captain's Call"].requires_subscription)
        self.assertTrue(campaigns["Captain's Call"].has_watchable_drops)
        self.assertFalse(campaigns["Crimson Desert"].requires_subscription)

    def test_only_games_with_a_campaign_are_read(self):
        self.sweep()

        self.assertNotIn("fortnite", self.fetched)  # campaign history: nothing to check
        self.assertEqual(sorted(self.fetched), sorted(set(self.fetched)))  # each page once
        self.assertIn("elden-ring", self.fetched)

    def test_the_second_refresh_reads_nothing_again(self):
        self.sweep()
        reads = len(self.fetched)

        self.registry_campaigns()
        self.client.wait_for_registry_rewards(10)

        self.assertEqual(len(self.fetched), reads)

    def test_a_restart_remembers_everything_and_reads_nothing(self):
        self.sweep()
        self.fetched.clear()

        restarted = self.new_client()
        self.client = restarted
        campaigns = self.by_name(self.registry_campaigns())
        restarted.wait_for_registry_rewards(10)

        self.assertEqual(self.fetched, [])
        self.assertTrue(campaigns["ELDEN RING"].requires_subscription)  # already marked when the list is built

    def test_a_game_whose_card_changed_is_read_again_and_only_that_one(self):
        self.sweep()
        self.fetched.clear()
        changed = fixture("home_excerpt").replace('data-drops="1" data-end="2026-11-30', 'data-drops="2" data-end="2026-11-30')

        self.registry_campaigns(changed)
        self.client.wait_for_registry_rewards(10)

        self.assertEqual(self.fetched, ["elden-ring"])

    def test_the_sweep_is_slow_on_purpose(self):
        self.assertEqual(tc.TwitchClient()._registry_pause_sec, 1.5)

    def test_a_note_says_which_games_are_subscription_only(self):
        self.client.consume_diagnostics()
        self.sweep()

        notes = " ".join(self.client.consume_diagnostics())

        self.assertIn("elden-ring", notes)
        self.assertIn("verificado", notes)

    def test_one_failed_page_does_not_stop_the_others(self):
        calls: list[str] = []

        def flaky(slug: str) -> str:
            calls.append(slug)
            if slug == "elden-ring" and calls.count(slug) == 1:
                raise requests.ConnectionError("blip")
            return self.pages.get(slug, fixture("captains-call"))

        self.client._registry_fetch_page = flaky
        self.registry_campaigns()
        self.client.wait_for_registry_rewards(10)

        # Elden Ring failed this time, every other game was still read.
        self.assertIsNone(self.client._registry_rewards.summary("elden-ring"))
        self.assertIsNotNone(self.client._registry_rewards.summary("cyberpunk-2077"))
        # ...and the next refresh tries it again.
        self.registry_campaigns()
        self.client.wait_for_registry_rewards(10)
        self.assertTrue(self.client._registry_rewards.summary("elden-ring").subscription_only)

    def test_it_gives_up_after_five_failures_in_a_row_instead_of_hammering_the_site(self):
        calls: list[str] = []

        def down(slug: str) -> str:
            calls.append(slug)
            raise requests.ConnectionError("down")

        self.client._registry_fetch_page = down
        self.client.consume_diagnostics()
        self.registry_campaigns()
        self.client.wait_for_registry_rewards(10)

        self.assertEqual(len(calls), 5)
        self.assertIn("5 vezes seguidas", " ".join(self.client.consume_diagnostics()))
        self.assertFalse(self.client._registry_pending)

    def test_what_was_learned_is_saved_to_disk(self):
        self.sweep()

        self.assertTrue(self.rewards_file.exists())
        self.assertIn("elden-ring", self.rewards_file.read_text(encoding="utf-8"))


class TestApply(_ClientCase):
    def campaign(self, *, source: str = "external_registry", claimed: bool = False) -> DropCampaign:
        return DropCampaign(
            id="x", game_name="Elden Ring", title="Elden Ring", starts_at=FIXED_NOW, ends_at=FIXED_NOW + timedelta(days=1),
            link_url="https://twitchdrops.app/game/elden-ring", source=source, all_drops_claimed=claimed,
        )

    def test_nothing_is_marked_for_a_game_that_has_not_been_read_yet(self):
        campaign = self.campaign()

        self.assertEqual(self.client.apply_registry_rewards([campaign]), 0)
        self.assertFalse(campaign.requires_subscription)

    def test_it_only_touches_registry_campaigns_that_are_not_finished(self):
        self.client._registry_rewards.store("elden-ring", "sig", RewardSummary(subscription=1))
        twitch = self.campaign(source="twitch")
        claimed = self.campaign(claimed=True)
        registry = self.campaign()

        marked = self.client.apply_registry_rewards([twitch, claimed, registry])

        self.assertEqual(marked, 1)
        self.assertFalse(twitch.requires_subscription)  # real Twitch data is never overridden
        self.assertFalse(claimed.requires_subscription)
        self.assertTrue(registry.requires_subscription)

    def test_a_game_that_gained_a_watch_drop_is_unmarked(self):
        self.client._registry_rewards.store("elden-ring", "sig", RewardSummary(subscription=1))
        campaign = self.campaign()
        self.client.apply_registry_rewards([campaign])
        self.assertTrue(campaign.requires_subscription)

        self.client._registry_rewards.store("elden-ring", "sig2", RewardSummary(watchable=1, subscription=1))
        self.client.apply_registry_rewards([campaign])

        self.assertFalse(campaign.requires_subscription)
        self.assertTrue(campaign.has_watchable_drops)

    def test_the_old_parser_for_markup_the_site_never_had_is_gone(self):
        self.assertFalse(hasattr(tc.TwitchClient, "_extract_game_rewards_from_page"))
        self.assertFalse(hasattr(tc.TwitchClient, "_apply_game_page_reward_metadata"))


class TestEngine(_ClientCase):
    """The engine must not farm a game it knows has nothing to watch for, even when the list is cached."""

    def campaign(self, name: str, slug: str) -> DropCampaign:
        now = datetime.now(UTC)
        return DropCampaign(
            id=f"external-{slug}", game_name=name, title=name, starts_at=now - timedelta(hours=1), ends_at=now + timedelta(days=5),
            status="ACTIVE", link_url=f"https://twitchdrops.app/game/{slug}", source="external_registry",
        )

    def engine(self, campaigns: list[DropCampaign]) -> FarmEngine:
        self.client.fetch_campaigns = MagicMock(side_effect=lambda **_kw: list(campaigns))
        self.client.fetch_streams = MagicMock(side_effect=lambda c: [
            StreamCandidate(login=f"{c.id}-chan", display_name="x", game_name=c.game_name, viewer_count=5,
                            drops_enabled=True, channel_id="1")
        ])
        self.client.consume_diagnostics = MagicMock(return_value=[])
        return FarmEngine(self.client, AppConfig(watchdog_enabled=False))

    def reasons(self, snapshot) -> dict[str, str]:
        return {d.campaign.game_name: d.reason_code for d in snapshot.decisions}

    def test_a_subscription_only_game_is_skipped_and_a_mixed_one_is_farmed(self):
        elden = self.campaign("Elden Ring", "elden-ring")
        cyberpunk = self.campaign("Cyberpunk 2077", "cyberpunk-2077")
        self.client._registry_rewards.store("elden-ring", "s", RewardSummary(subscription=1))
        self.client._registry_rewards.store("cyberpunk-2077", "s", RewardSummary(watchable=1, subscription=1))

        reasons = self.reasons(self.engine([elden, cyberpunk]).poll())

        self.assertEqual(reasons["Elden Ring"], "subscription_required")
        self.assertEqual(reasons["Cyberpunk 2077"], "stream_selected")

    def test_what_the_sweep_learns_later_applies_on_the_next_poll_without_a_new_list(self):
        elden = self.campaign("Elden Ring", "elden-ring")
        engine = self.engine([elden])
        self.assertEqual(self.reasons(engine.poll())["Elden Ring"], "stream_selected")  # not read yet

        self.client._registry_rewards.store("elden-ring", "s", RewardSummary(subscription=1))
        reasons = self.reasons(engine.poll())  # the campaign list is still the cached one

        self.assertEqual(self.client.fetch_campaigns.call_count, 1)
        self.assertEqual(reasons["Elden Ring"], "subscription_required")


if __name__ == "__main__":
    unittest.main()
