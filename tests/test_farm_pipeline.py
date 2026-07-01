"""
Deterministic unit tests for the FarmEngine pipeline.

These tests do NOT require network access or a running Qt instance.
They prove that actionable Inventory campaigns:
  A. reach fetch_streams() in poll()
  B. active browser-only campaigns (required_minutes=0, drops=[]) DO reach fetch_streams()
     and get no_valid_stream when no streams are available (instead of INATIVO)
  C. are filtered by whitelist (whitelist applies to Inventory campaigns too)
  D. are selected as the farming target when a live stream is available
  E. campaign with no stream (fetch_streams returns []) ends up not farmable
  + regression: inventory campaign with missing/bad timestamps (active=False)
                must still reach fetch_streams() and not be silently dropped

TestFetchStreamsSlugResolution verifies TwitchClient.fetch_streams() stream
source priority (allowed_channels first, then directory):
  - When allowed_channels is non-empty, _fetch_streams_from_allowed_channels is
    called exclusively; the game directory (_fetch_streams_for_slug) is NOT called.
  - When allowed_channels is empty, game directory is used.
  - When slug resolution fails and allowed_channels is empty, return [].

TestStreamCandidateEligibility verifies stream eligibility filtering:
  - allowed_channels streams are preferred over directory when both exist.
  - Non-allowed directory streams are rejected by choose_stream.

TestExpiringAlertTimestampSource verifies the campaign-expiring alert:
  - Only fires for campaign-level timestamps (timestamp_source='campaign').
  - Must NOT fire for drop-level or synthetic timestamps.
"""
from __future__ import annotations

import sys
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.models import DropCampaign, FarmDecision, StreamCandidate
from twitch_drop_farmer.farmer import FarmEngine
from twitch_drop_farmer.config import AppConfig

UTC = timezone.utc


def _make_drops(count: int = 5) -> list[dict]:
    return [
        {
            "name": f"Drop {i + 1}",
            "image_url": "",
            "required_minutes": 24,
            "current_minutes": 0,
            "remaining_minutes": 24,
            "claimed": False,
        }
        for i in range(count)
    ]


def _inventory_campaign(
    game_name: str,
    campaign_id: str = "real-001",
    required_minutes: int = 120,
    drops_count: int = 5,
    progress: int = 0,
) -> DropCampaign:
    now = datetime.now(UTC)
    return DropCampaign(
        id=campaign_id,
        game_name=game_name,
        title=f"{game_name} Campaign",
        starts_at=now - timedelta(days=7),
        ends_at=now + timedelta(days=14),
        status="ACTIVE",
        required_minutes=required_minutes,
        progress_minutes=progress,
        drops=_make_drops(drops_count),
        linked=True,
    )


def _browser_campaign(game_name: str, suffix: str = "aaa") -> DropCampaign:
    now = datetime.now(UTC)
    return DropCampaign(
        id=f"browser-{suffix}",
        game_name=game_name,
        title=f"{game_name} (browser)",
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=14),
        status="ACTIVE",
        required_minutes=0,
        progress_minutes=0,
        drops=[],
        linked=True,
    )


def _make_engine(
    whitelist: list[str] | None = None,
    blacklist: list[str] | None = None,
) -> FarmEngine:
    config = AppConfig(
        whitelist_games=whitelist or [],
        blacklist_games=blacklist or [],
        whitelist_channels=[],
        blacklist_channels=[],
        watchdog_enabled=False,
        alert_campaign_expiring_soon=False,
        alert_farm_complete=False,
        alert_no_progress=False,
        alert_token_invalid=False,
    )
    client = MagicMock()
    client.consume_diagnostics.return_value = []
    client.fetch_streams.return_value = []
    return FarmEngine(client=client, config=config)


class TestFarmEnginePipeline(unittest.TestCase):

    def test_A_inventory_campaigns_reach_fetch_streams(self):
        """
        Test A: Given a mix of browser-only and inventory campaigns,
        poll() must call fetch_streams() for each actionable inventory campaign.
        """
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)
        nikki = _inventory_campaign("Infinity Nikki", "real-nikki-001", 120, 6)
        finals = _inventory_campaign("THE FINALS", "real-finals-001", 240, 1)
        wow_browser = _browser_campaign("World of Warcraft", "wow1")
        ow_browser = _browser_campaign("Overwatch", "ow1")

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [wow_browser, ow_browser, arknights, nikki, finals]

        engine.poll()

        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertIn("ARKNIGHTS: ENDFIELD", fetched)
        self.assertIn("Infinity Nikki", fetched)
        self.assertIn("THE FINALS", fetched)

    def test_B_browser_only_zero_drop_active_campaigns_reach_fetch_streams(self):
        """
        Test B: Active browser-only campaigns (required_minutes=0, drops=[]) must
        reach fetch_streams() so they show LIVE or SEM CANAIS instead of INATIVO.
        When no streams are available they must get no_valid_stream.
        Inactive browser campaigns (no activity or no actionable data and not active)
        may still get no_actionable_drop_data, but active ones must not.
        """
        campaigns = [
            _browser_campaign("World of Warcraft", "wow1"),
            _browser_campaign("Overwatch", "ow1"),
            _browser_campaign("Apex Legends", "apex1"),
        ]
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = campaigns

        snapshot = engine.poll()

        # Active campaigns without drop data must now try stream detection.
        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertEqual(fetched, {"World of Warcraft", "Overwatch", "Apex Legends"})
        # With fetch_streams returning [] (no live streams), reason_code must be no_valid_stream.
        for decision in snapshot.decisions:
            self.assertEqual(
                decision.reason_code,
                "no_valid_stream",
                f"Active browser campaign {decision.campaign.game_name!r} with no streams "
                f"must be no_valid_stream, got {decision.reason_code!r}",
            )

    def test_C_whitelist_excludes_inventory_campaigns_not_in_list(self):
        """
        Test C: Whitelist applies to Inventory campaigns.
        Games not in the whitelist must be game_filtered — no bypass for Inventory.
        """
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)
        nikki = _inventory_campaign("Infinity Nikki", "real-nikki-001", 120, 6)

        engine = _make_engine(whitelist=["World of Warcraft"])
        engine.client.fetch_campaigns.return_value = [arknights, nikki]

        snapshot = engine.poll()

        engine.client.fetch_streams.assert_not_called()
        for decision in snapshot.decisions:
            self.assertEqual(
                decision.reason_code, "game_filtered",
                f"{decision.campaign.game_name!r} not in whitelist must be game_filtered",
            )

    def test_C_inventory_in_whitelist_reaches_fetch_streams(self):
        """
        Test C2: Whitelist includes the Inventory game → reaches fetch_streams normally.
        """
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)
        nikki = _inventory_campaign("Infinity Nikki", "real-nikki-001", 120, 6)

        engine = _make_engine(whitelist=["ARKNIGHTS: ENDFIELD"])
        engine.client.fetch_campaigns.return_value = [arknights, nikki]

        snapshot = engine.poll()

        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertIn("ARKNIGHTS: ENDFIELD", fetched,
                      "Whitelisted Inventory game must reach fetch_streams")
        self.assertNotIn("Infinity Nikki", fetched,
                         "Non-whitelisted Infinity Nikki must be game_filtered")
        nikki_d = [d for d in snapshot.decisions if d.campaign.id == "real-nikki-001"]
        self.assertEqual(nikki_d[0].reason_code, "game_filtered")

    def test_C_blacklisted_inventory_campaign_is_rejected(self):
        """
        Test C (extension): Blacklisted Inventory campaigns must be game_filtered
        even when they have actionable drops.
        """
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)

        engine = _make_engine(blacklist=["ARKNIGHTS: ENDFIELD"])
        engine.client.fetch_campaigns.return_value = [arknights]

        snapshot = engine.poll()

        engine.client.fetch_streams.assert_not_called()
        self.assertEqual(snapshot.decisions[0].reason_code, "game_filtered")

    def test_D_inventory_campaign_selected_when_stream_available(self):
        """
        Test D: When an inventory campaign has a live stream,
        the farming decision must select that stream.
        """
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)
        wow_browser = _browser_campaign("World of Warcraft", "wow1")

        stream = StreamCandidate(
            login="arknightschannel",
            display_name="ArknightsChannel",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=1000,
            drops_enabled=True,
        )

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights, wow_browser]

        def _mock_fetch_streams(campaign):
            if campaign.game_name == "ARKNIGHTS: ENDFIELD":
                return [stream]
            return []

        engine.client.fetch_streams.side_effect = _mock_fetch_streams

        snapshot = engine.poll()

        ark_decisions = [d for d in snapshot.decisions if d.campaign.id == "real-ark-001"]
        self.assertEqual(len(ark_decisions), 1)
        ark = ark_decisions[0]
        self.assertIsNotNone(ark.stream)
        self.assertEqual(ark.stream.login, "arknightschannel")
        self.assertEqual(ark.reason_code, "stream_selected")

    def test_regression_missing_timestamps_inventory_still_reaches_fetch_streams(self):
        """
        Regression: inventory campaign where both startAt and endAt were absent from the
        Twitch Inventory GQL response causes _parse_timestamp(None) to return datetime.now()
        for both fields.  _parse_campaign then sees ends_at <= now and sets status='EXPIRED',
        making campaign.active=False.  poll() used to emit campaign_not_active and skip the
        campaign entirely.

        After the fix:
        - _parse_campaign uses a safe 30-day default window when both timestamps are absent
        - poll() has an active bypass for inventory campaigns with actionable drops

        Both defences must be in place.  This test exercises the poll() bypass specifically
        by constructing a DropCampaign with ends_at=now and status='EXPIRED' directly.
        """
        now = datetime.now(UTC)
        arknights = DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS: ENDFIELD Campaign",
            starts_at=now,
            ends_at=now,
            status="EXPIRED",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=True,
            timestamps_are_synthetic=True,
        )

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights]

        snapshot = engine.poll()

        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertIn(
            "ARKNIGHTS: ENDFIELD",
            fetched,
            "Inventory campaign with missing timestamps must bypass active=False and reach fetch_streams",
        )
        ark_decisions = [d for d in snapshot.decisions if d.campaign.id == "real-ark-001"]
        self.assertEqual(len(ark_decisions), 1)
        self.assertNotEqual(
            ark_decisions[0].reason_code,
            "campaign_not_active",
            "Inventory campaign must not be silently dropped as campaign_not_active",
        )
        # The campaign object itself must have active=True after poll() so that
        # _decision_is_farmable_now() in the UI also returns True.
        self.assertTrue(
            ark_decisions[0].campaign.active,
            "campaign.active must be True after poll() so the UI can select it for farming",
        )

    def test_subscription_only_zero_minute_campaign_is_marked_subscription_required(self):
        """
        Regression: campaigns whose drops all report requiredMinutesWatched=0 are
        subscription-locked in Twitch's inventory UI and must not be treated as
        generic no-data campaigns.
        """
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="sub-only-001",
            game_name="SUB-ONLY GAME",
            title="SUB-ONLY GAME Campaign",
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1),
            status="ACTIVE",
            required_minutes=0,
            progress_minutes=0,
            drops=[
                {
                    "name": "Subscriber Drop",
                    "requiredMinutesWatched": 0,
                    "currentMinutesWatched": 0,
                    "remaining_minutes": 0,
                    "claimed": False,
                }
            ],
            linked=True,
        )

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [campaign]

        snapshot = engine.poll()

        engine.client.fetch_streams.assert_not_called()
        sub_decisions = [d for d in snapshot.decisions if d.campaign.id == "sub-only-001"]
        self.assertEqual(len(sub_decisions), 1)
        sub = sub_decisions[0]
        self.assertEqual(sub.reason_code, "subscription_required")
        self.assertTrue(sub.campaign.requires_subscription)
        self.assertFalse(sub.campaign.has_watchable_drops)
        self.assertTrue(sub.campaign.active)

    def test_integration_real_world_shape(self):
        """
        Integration test: 69-campaign snapshot (3 inventory + 66 browser-only) with
        NO whitelist active (empty list = farm everything that qualifies).

        Proves:
        1. poll() calls fetch_streams() for all 3 inventory campaigns.
        2. After poll(), inventory campaign decisions have campaign.active=True and
           stream is not None when a stream is available.
        3. The first farmable decision (what _current_farm_decision returns) is an
           inventory campaign, never a browser-only campaign.
        4. No browser-only campaign ever has reason_code='stream_selected'.
        """
        now = datetime.now(UTC)

        # 3 inventory campaigns with bad timestamps (simulate missing startAt/endAt)
        inv_games = [
            ("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5),
            ("Infinity Nikki",      "real-nikki-001", 120, 6),
            ("THE FINALS",          "real-finals-001", 240, 1),
        ]
        inventory_campaigns = []
        for game_name, cid, req_min, drops in inv_games:
            # Simulate missing timestamps: status='EXPIRED' and active=False.
            # poll() synthetic bypass must repair these.
            c = DropCampaign(
                id=cid,
                game_name=game_name,
                title=f"{game_name} Campaign",
                starts_at=now,
                ends_at=now,
                status="EXPIRED",
                required_minutes=req_min,
                progress_minutes=0,
                drops=_make_drops(drops),
                linked=True,
                timestamps_are_synthetic=True,
            )
            inventory_campaigns.append(c)

        # 66 browser-only campaigns with no drop data
        browser_game_names = [
            "World of Warcraft", "Overwatch", "Apex Legends", "Valorant",
            "League of Legends", "Fortnite", "Call of Duty", "Minecraft",
            "Path of Exile", "Lost Ark", "Diablo IV", "Starcraft II",
            "Counter-Strike 2", "Dota 2", "PUBG", "Rust", "ARK: Survival",
            "Escape from Tarkov", "Rainbow Six Siege", "The Division 2",
            "Ghost Recon Breakpoint", "Far Cry 6", "Watch Dogs Legion",
            "Assassin Creed Valhalla", "Anno 1800", "For Honor", "Hyper Scape",
            "Tom Clancy XDefiant", "Division Heartland", "Crew Motorfest",
        ]
        browser_campaigns = []
        for i in range(66):
            game_name = browser_game_names[i % len(browser_game_names)]
            browser_campaigns.append(_browser_campaign(game_name, suffix=f"{i:03d}"))

        all_campaigns = inventory_campaigns + browser_campaigns
        self.assertEqual(len(all_campaigns), 69)

        # No whitelist: farm all qualifying campaigns.
        engine = _make_engine()

        # Provide a live stream for each inventory campaign.
        def _mock_fetch_streams(campaign: DropCampaign):
            inv_ids = {c.id for c in inventory_campaigns}
            if campaign.id in inv_ids:
                return [StreamCandidate(
                    login=f"{campaign.game_name.lower().replace(' ', '_').replace(':', '')}ch",
                    display_name=campaign.game_name,
                    game_name=campaign.game_name,
                    viewer_count=500,
                    drops_enabled=True,
                )]
            return []

        engine.client.fetch_campaigns.return_value = all_campaigns
        engine.client.fetch_streams.side_effect = _mock_fetch_streams

        snapshot = engine.poll()

        # 1. fetch_streams called for all 3 inventory campaigns.
        fetched_games = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        for game_name, _, _, _ in inv_games:
            self.assertIn(game_name, fetched_games,
                          f"fetch_streams must be called for inventory campaign {game_name!r}")

        # 2. Inventory decisions have active=True and stream selected.
        inv_ids = {cid for _, cid, _, _ in inv_games}
        inv_decisions = [d for d in snapshot.decisions if d.campaign.id in inv_ids]
        self.assertEqual(len(inv_decisions), 3, "All 3 inventory campaigns must produce a decision")
        for d in inv_decisions:
            self.assertTrue(d.campaign.active,
                            f"{d.campaign.game_name!r} must have campaign.active=True after poll()")
            self.assertIsNotNone(d.stream,
                                 f"{d.campaign.game_name!r} must have a stream selected")
            self.assertEqual(d.reason_code, "stream_selected",
                             f"{d.campaign.game_name!r} must have reason_code='stream_selected'")

        # 3. No browser-only campaign has a stream selected.
        for d in snapshot.decisions:
            if d.campaign.id.startswith("browser-"):
                self.assertIsNone(d.stream,
                                  f"Browser campaign {d.campaign.game_name!r} must never have a stream")
                self.assertNotEqual(d.reason_code, "stream_selected",
                                    f"Browser campaign must never be stream_selected")

        # 4. The best farmable candidate is one of the inventory campaigns
        #    (replicates what _current_farm_decision returns: first farmable decision).
        def _is_farmable(d) -> bool:
            c = d.campaign
            if c.requires_subscription and not c.all_drops_claimed:
                return False
            if not (c.active and c.eligible and d.stream is not None):
                return False
            if c.required_minutes > 0 and c.remaining_minutes <= 0:
                return False
            return True

        farmable = [d for d in snapshot.decisions if _is_farmable(d)]
        self.assertTrue(len(farmable) > 0, "At least one farmable decision must exist")
        for d in farmable:
            self.assertFalse(d.campaign.id.startswith("browser-"),
                             f"No browser campaign must appear in farmable decisions")
        # All farmable decisions must be inventory campaigns
        farmable_ids = {d.campaign.id for d in farmable}
        self.assertTrue(farmable_ids.issubset(inv_ids),
                        f"All farmable decisions must be inventory campaigns, got {farmable_ids}")


    def test_E_inventory_campaign_with_no_stream_is_not_farmable(self):
        """
        Test E: When fetch_streams() returns [] for an inventory campaign
        (e.g. game_slug is empty and slug resolution fails, or simply no live
        stream exists), the decision must have reason_code='no_valid_stream' and
        stream=None.  The campaign.active flag must remain True so that only the
        missing stream — not a broken active state — is the blocking condition.

        This test reproduces the real failure scenario: campaign is present in
        Inventory, timestamps are fixed, the pipeline reaches fetch_streams(),
        but fetch_streams() returns nothing → nothing is farmed.
        """
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights]
        engine.client.fetch_streams.return_value = []  # No stream available / slug resolution failed

        snapshot = engine.poll()

        # fetch_streams was still called — the campaign reached it
        engine.client.fetch_streams.assert_called_once()

        ark_decisions = [d for d in snapshot.decisions if d.campaign.id == "real-ark-001"]
        self.assertEqual(len(ark_decisions), 1)
        ark = ark_decisions[0]

        self.assertIsNone(ark.stream, "stream must be None when fetch_streams returns []")
        self.assertEqual(ark.reason_code, "no_valid_stream",
                         "reason_code must be no_valid_stream, not campaign_not_active or game_filtered")

        # campaign.active must be True — only the stream is missing, the campaign itself is valid
        self.assertTrue(ark.campaign.active,
                        "campaign.active must be True; only the stream is missing")

        # Replicate _decision_is_farmable_now() — must return False because stream is None
        farmable = (
            ark.campaign.active
            and ark.campaign.eligible
            and ark.stream is not None
        )
        self.assertFalse(farmable,
                         "Decision must not be farmable when stream is None")


class TestFetchStreamsSlugResolution(unittest.TestCase):
    """
    Unit tests for TwitchClient.fetch_streams() and related methods.

    Methods are called as unbound functions on a MagicMock standing in for
    'self' so _post_gql, resolve_game_slug and _stream_info can be controlled
    without network access or a full TwitchClient instance.
    """

    def _make_mock_client(self) -> MagicMock:
        client = MagicMock()
        client._clone_query.side_effect = lambda _q: {"variables": {}}
        client._note = MagicMock()
        client._dbg = MagicMock()
        return client

    def _make_campaign(
        self,
        game_slug: str = "",
        allowed_channels: list[str] | None = None,
    ) -> DropCampaign:
        return DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            ends_at=datetime.now(UTC) + timedelta(days=14),
            starts_at=datetime.now(UTC) - timedelta(days=1),
            game_slug=game_slug,
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=True,
            allowed_channels=allowed_channels or [],
        )

    def test_resolve_slug_called_when_game_slug_empty(self):
        """
        When campaign.game_slug is empty, fetch_streams must call
        resolve_game_slug(game_name) as fallback and use the returned slug.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        client.resolve_game_slug.return_value = "arknights-endfield"
        client._fetch_streams_for_slug.return_value = [
            StreamCandidate(
                login="arkchan",
                display_name="ArkChan",
                game_name="ARKNIGHTS: ENDFIELD",
                viewer_count=500,
                drops_enabled=True,
                channel_id="ch456",
                broadcast_id="bcast123",
            )
        ]
        client._fetch_streams_from_allowed_channels.return_value = []

        result = TwitchClient.fetch_streams(client, self._make_campaign(game_slug=""))

        client.resolve_game_slug.assert_called_once_with("ARKNIGHTS: ENDFIELD")
        client._fetch_streams_for_slug.assert_called_once()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].login, "arkchan")

    def test_empty_result_when_slug_resolution_fails(self):
        """
        Reproduces the real failure: game_slug is empty AND resolve_game_slug()
        cannot find a slug (returns '').  fetch_streams must return [] without
        calling _fetch_streams_for_slug.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        client.resolve_game_slug.return_value = ""  # Slug resolution failed
        client._fetch_streams_from_allowed_channels.return_value = []

        result = TwitchClient.fetch_streams(client, self._make_campaign(game_slug=""))

        self.assertEqual(result, [], "Must return [] when slug cannot be resolved")
        client._fetch_streams_for_slug.assert_not_called()

    def test_resolve_slug_not_called_when_game_slug_present(self):
        """
        When campaign.game_slug is already populated, fetch_streams must NOT call
        resolve_game_slug — the existing slug must be used directly.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        client._fetch_streams_for_slug.return_value = []
        client._fetch_streams_from_allowed_channels.return_value = []

        TwitchClient.fetch_streams(
            client, self._make_campaign(game_slug="arknights-endfield")
        )

        client.resolve_game_slug.assert_not_called()

    def test_allowed_channels_used_first_when_present(self):
        """
        When campaign.allowed_channels is non-empty, fetch_streams queries the
        directory first and filters results to the allowed set.  If the allowed
        channel appears in the directory result, _fetch_streams_from_allowed_channels
        must NOT be called (no extra per-channel API round-trips needed).
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        live_stream = StreamCandidate(
            login="ark_official",
            display_name="ark_official",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=1200,
            drops_enabled=True,
            channel_id="99001",
            broadcast_id="77002",
        )
        client = self._make_mock_client()
        # Directory returns the allowed channel — filter should match it.
        client._fetch_streams_for_slug.return_value = [live_stream]

        result = TwitchClient.fetch_streams(
            client,
            self._make_campaign(
                game_slug="arknights-endfield",
                allowed_channels=["ark_official"],
            ),
        )

        client._fetch_streams_for_slug.assert_called_once()
        client._fetch_streams_from_allowed_channels.assert_not_called()
        client.resolve_game_slug.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].login, "ark_official")
        self.assertEqual(result[0].channel_id, "99001")
        self.assertEqual(result[0].broadcast_id, "77002")

    def test_fallback_to_allowed_channels_when_not_in_directory(self):
        """
        When campaign.allowed_channels is non-empty but none of the top directory
        streams are in that list, fetch_streams falls back to
        _fetch_streams_from_allowed_channels().  If those are also all offline,
        the final result must be [] — no ineligible channels ever returned.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        # Directory returns a stream that is NOT in the allowed list.
        unrelated_stream = StreamCandidate(
            login="random_channel",
            display_name="random_channel",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=1000,
            drops_enabled=True,
        )
        client = self._make_mock_client()
        client._fetch_streams_for_slug.return_value = [unrelated_stream]
        client._fetch_streams_from_allowed_channels.return_value = []  # all offline

        result = TwitchClient.fetch_streams(
            client,
            self._make_campaign(
                game_slug="arknights-endfield",
                allowed_channels=["ark_official", "ark_stream2"],
            ),
        )

        self.assertEqual(result, [], "No allowed channels live anywhere → must return []")
        client._fetch_streams_for_slug.assert_called_once()
        client._fetch_streams_from_allowed_channels.assert_called_once()
        client.resolve_game_slug.assert_not_called()

    def test_fetch_streams_for_slug_returns_stream_candidates_with_ids(self):
        """
        _fetch_streams_for_slug must populate channel_id (broadcaster.id) and
        broadcast_id (node.id) from the GQL response.  Empty IDs cause
        streamless_watch_heartbeat() to fall back to _stream_info(), which is
        a second network round-trip and can fail on private channels.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        client._post_gql.return_value = {
            "data": {"game": {"streams": {"edges": [
                {"node": {
                    "id": "broadcast-id-999",
                    "viewersCount": 1000,
                    "broadcaster": {
                        "login": "testchannel",
                        "displayName": "TestChannel",
                        "id": "channel-id-777",
                    },
                }}
            ]}}}
        }

        result = TwitchClient._fetch_streams_for_slug(
            client, self._make_campaign(game_slug="arknights-endfield"), "arknights-endfield"
        )

        self.assertEqual(len(result), 1)
        stream = result[0]
        self.assertEqual(stream.channel_id, "channel-id-777")
        self.assertEqual(stream.broadcast_id, "broadcast-id-999")
        self.assertTrue(stream.channel_id, "channel_id must not be empty")
        self.assertTrue(stream.broadcast_id, "broadcast_id must not be empty")

    def test_fetch_streams_from_allowed_channels_skips_offline(self):
        """
        _fetch_streams_from_allowed_channels must skip channels where
        _stream_info() returns an empty broadcast_id (channel offline).
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        def _mock_stream_info(login):
            if login == "livechannel":
                return {"channel_id": "100", "broadcast_id": "200"}
            return {"channel_id": "101", "broadcast_id": ""}  # offline

        client._stream_info.side_effect = _mock_stream_info

        campaign = self._make_campaign(
            allowed_channels=["offlinechannel", "livechannel"]
        )
        result = TwitchClient._fetch_streams_from_allowed_channels(client, campaign)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].login, "livechannel")
        self.assertEqual(result[0].channel_id, "100")
        self.assertEqual(result[0].broadcast_id, "200")


class TestGQLWatchPayloadTypes(unittest.TestCase):
    """
    Tests that _streamless_gql_payload() encodes channel_id, broadcast_id,
    and user_id as JSON strings.

    Twitch's sendSpadeEvents pipeline accepts the mutation with status 204,
    but watch-time attribution expects these identifiers as strings inside the
    encoded event body.
    """

    def _make_mock_client(self) -> MagicMock:
        client = MagicMock()
        client.login_state = MagicMock()
        client.login_state.user_id = "987654321"
        return client

    def _decode_payload(self, result: dict) -> list:
        import base64, gzip, json
        raw = gzip.decompress(base64.b64decode(result["variables"]["input"]["data"]))
        return json.loads(raw)

    def test_numeric_ids_are_encoded_as_strings(self):
        """
        channel_id='123', broadcast_id='456', user_id='789' must appear as
        JSON strings "123", "456", "789" in the gzip+base64-encoded GQL payload.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        client.login_state.user_id = "789"

        result = TwitchClient._streamless_gql_payload(
            client,
            channel_login="testchannel",
            channel_id="123",
            broadcast_id="456",
        )

        events = self._decode_payload(result)
        props = events[0]["properties"]
        self.assertIsInstance(props["channel_id"], str,
                      "channel_id must be str")
        self.assertIsInstance(props["broadcast_id"], str,
                      "broadcast_id must be str")
        self.assertIsInstance(props["user_id"], str,
                      "user_id must be str")
        self.assertEqual(props["channel_id"], "123")
        self.assertEqual(props["broadcast_id"], "456")
        self.assertEqual(props["user_id"], "789")

    def test_event_name_and_required_fields_present(self):
        """GQL payload must include event='minute-watched' and all required fields."""
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        result = TwitchClient._streamless_gql_payload(
            client,
            channel_login="mychannel",
            channel_id="111",
            broadcast_id="222",
        )

        events = self._decode_payload(result)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event"], "minute-watched")
        props = event["properties"]
        for key in ("channel_id", "broadcast_id", "channel", "user_id",
                    "is_live", "live", "minutes_logged", "game", "game_id"):
            self.assertIn(key, props, f"Required field '{key}' missing from GQL payload")
        self.assertEqual(props["channel"], "mychannel")
        self.assertTrue(props["live"])
        self.assertTrue(props["is_live"])
        self.assertEqual(props["minutes_logged"], 1)
        # Mutation structure must have query and variables
        self.assertIn("query", result)
        self.assertIn("sendSpadeEvents", result["query"])
        self.assertIn("variables", result)
        input_obj = result["variables"]["input"]
        self.assertIsInstance(input_obj, dict, "input must be an object, not a string")
        self.assertIn("data", input_obj)
        self.assertEqual(input_obj.get("repository"), "twilight")
        self.assertEqual(input_obj.get("encoding"), "GZIP_B64")

    def test_non_numeric_ids_kept_as_strings(self):
        """
        If an ID is non-numeric (malformed data), the payload must still be
        produced — the value is kept as-is rather than crashing.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = self._make_mock_client()
        client.login_state.user_id = "not-a-number"

        result = TwitchClient._streamless_gql_payload(
            client,
            channel_login="ch",
            channel_id="bad-id",
            broadcast_id="also-bad",
        )

        events = self._decode_payload(result)
        props = events[0]["properties"]
        self.assertEqual(props["user_id"], "not-a-number")
        self.assertEqual(props["channel_id"], "bad-id")
        self.assertEqual(props["broadcast_id"], "also-bad")


class TestHeartbeatIntegration(unittest.TestCase):
    """
    Integration-level test: proves the full path from poll() to heartbeat.

    1. 3 Inventory campaigns + no streams from directory.
    2. Each campaign has allowed_channels that are live.
    3. _current_farm_decision() equivalent selects an Inventory campaign.
    4. The selected stream has non-empty channel_id and broadcast_id.
    5. A call to streamless_watch_heartbeat with that stream produces a valid
         Spade payload with string IDs.
    """

    def test_full_path_inventory_to_heartbeat_payload(self):
        """
        End-to-end: Inventory campaign → allowed_channels fallback → stream
        selected → heartbeat payload contains string IDs.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)
        arknights.allowed_channels = ["arkofficialstream"]
        arknights.game_slug = "arknights-endfield"

        # Engine: directory returns no streams, allowed_channels fallback returns one
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights]

        def _mock_fetch_streams(campaign):
            # Simulate: directory empty, allowed_channels fallback produces a stream
            return [StreamCandidate(
                login="arkofficialstream",
                display_name="ArkOfficialStream",
                game_name="ARKNIGHTS: ENDFIELD",
                viewer_count=0,
                drops_enabled=True,
                channel_id="55001",
                broadcast_id="77002",
            )]

        engine.client.fetch_streams.side_effect = _mock_fetch_streams

        snapshot = engine.poll()

        # Verify campaign is selected
        ark = next(d for d in snapshot.decisions if d.campaign.id == "real-ark-001")
        self.assertEqual(ark.reason_code, "stream_selected")
        self.assertIsNotNone(ark.stream)
        self.assertEqual(ark.stream.login, "arkofficialstream")
        self.assertEqual(ark.stream.channel_id, "55001")
        self.assertEqual(ark.stream.broadcast_id, "77002")

        # Verify the GQL payload uses string IDs
        mock_client = MagicMock()
        mock_client.login_state = MagicMock()
        mock_client.login_state.user_id = "12345"

        import base64, gzip, json as _json
        gql_result = TwitchClient._streamless_gql_payload(
            mock_client,
            channel_login=ark.stream.login,
            channel_id=ark.stream.channel_id,
            broadcast_id=ark.stream.broadcast_id,
        )
        events = _json.loads(gzip.decompress(base64.b64decode(gql_result["variables"]["input"]["data"])))
        props = events[0]["properties"]

        self.assertIsInstance(props["channel_id"], str)
        self.assertIsInstance(props["broadcast_id"], str)
        self.assertIsInstance(props["user_id"], str)
        self.assertEqual(props["channel_id"], "55001")
        self.assertEqual(props["broadcast_id"], "77002")
        self.assertEqual(props["user_id"], "12345")
        self.assertEqual(props["channel"], "arkofficialstream")


class TestStreamlessHlsFallback(unittest.TestCase):
    """Regression tests for the streamless HLS fallback path."""

    def test_media_playlist_resolver_remains_callable_and_caches_url(self):
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = TwitchClient()
        client._post_gql_web = MagicMock(return_value={
            "data": {
                "streamPlaybackAccessToken": {
                    "signature": "signature-123",
                    "value": "token-456",
                }
            }
        })

        class _Response:
            def __init__(self, text: str, url: str) -> None:
                self.text = text
                self.url = url

            def raise_for_status(self) -> None:
                return None

        def _mock_get(url, headers=None, timeout=None):
            self.assertIn("usher.ttvnw.net/api/channel/hls/livechannel.m3u8", url)
            return _Response(
                "#EXTM3U\n#EXT-X-VERSION:3\nhttps://example.com/livechannel/playlist.m3u8\n",
                "https://usher.ttvnw.net/api/channel/hls/livechannel.m3u8",
            )

        client.session.get = MagicMock(side_effect=_mock_get)

        self.assertTrue(callable(client._streamless_media_playlist))

        playlist_url = client._streamless_media_playlist("livechannel")

        self.assertEqual(playlist_url, "https://example.com/livechannel/playlist.m3u8")
        self.assertEqual(
            client._streamless_media_playlist_cache.get("livechannel"),
            "https://example.com/livechannel/playlist.m3u8",
        )


def _make_parse_campaign_client():
    """Mock TwitchClient suitable for calling _parse_campaign() without network or Qt."""
    client = MagicMock()
    client._parse_timestamp.side_effect = lambda raw: (
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if raw
        else datetime.now(UTC)
    )
    client._note.return_value = None
    client._extract_drop_like_entries.return_value = []
    client._drop_totals.return_value = (120, 120)
    client._next_drop_info.return_value = ("Test Drop", 120, 120)
    client._all_drops_claimed.return_value = False
    client._campaign_requires_subscription.return_value = False
    client._extract_campaign_progress_data.return_value = (0, 0)
    client._campaign_claimed_from_payload.return_value = False
    client._channel_login_from_acl.return_value = ""
    client._drop_progress_items.return_value = []
    client._campaign_has_badge_or_emote.return_value = False
    client._game_box_art_url.return_value = ""
    return client


class TestParseCampaignDropTimestamps(unittest.TestCase):
    """
    Unit tests for _parse_campaign() timestamp extraction logic.

    Verifies that when campaign-level timestamps are absent:
    - Drop-level endAt in the future → active campaign, timestamps_are_synthetic=False
    - Drop-level endAt in the past → expired campaign, timestamps_are_synthetic=False
    - No timestamps anywhere → synthetic window applied, timestamps_are_synthetic=True
    """

    def _call_parse(self, data: dict) -> "DropCampaign | None":
        from twitch_drop_farmer.twitch_client import TwitchClient
        client = _make_parse_campaign_client()
        return TwitchClient._parse_campaign(client, data)

    def _base_data(self, drops_extra: list | None = None) -> dict:
        return {
            "id": "real-camp-001",
            "name": "Test Campaign",
            "status": "ACTIVE",
            "game": {"displayName": "Test Game", "slug": "test-game"},
            "timeBasedDrops": drops_extra or [],
            "allow": {},
        }

    def test_parse_drop_level_future_endAt_produces_active_campaign(self):
        """
        Test 2 (_parse_campaign level): No campaign-level timestamps, drop-level endAt
        is 7 days in the future.
        Expected: campaign.active=True, timestamps_are_synthetic=False.
        The drop-level timestamp is used to set a real (non-synthetic) window.
        """
        future_iso = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self._base_data(drops_extra=[{"id": "drop-1", "endAt": future_iso}])

        result = self._call_parse(data)

        self.assertIsNotNone(result)
        self.assertTrue(result.active,
                        "Campaign with future drop-level endAt must be active")
        self.assertFalse(result.timestamps_are_synthetic,
                         "timestamps_are_synthetic must be False when drop-level endAt was found")

    def test_parse_drop_level_past_endAt_produces_expired_campaign(self):
        """
        Test 3 (_parse_campaign level): No campaign-level timestamps, drop-level endAt
        is 1 hour in the past.
        Expected: campaign.active=False, status='EXPIRED', timestamps_are_synthetic=False.
        The expiry is real — it must not be treated as synthetic.
        """
        past_iso = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self._base_data(drops_extra=[{"id": "drop-1", "endAt": past_iso}])

        result = self._call_parse(data)

        self.assertIsNotNone(result)
        self.assertFalse(result.active,
                         "Campaign with past drop-level endAt must be expired/inactive")
        self.assertEqual(result.status, "EXPIRED")
        self.assertFalse(result.timestamps_are_synthetic,
                         "timestamps_are_synthetic must be False when drop-level endAt was found")

    def test_parse_no_timestamps_anywhere_sets_synthetic_true(self):
        """
        Complement: No timestamps at campaign level OR drop level.
        Expected: campaign.active=True (synthetic 30-day window), timestamps_are_synthetic=True.
        """
        data = self._base_data(drops_extra=[{"id": "drop-1"}])  # drop has no endAt

        result = self._call_parse(data)

        self.assertIsNotNone(result)
        self.assertTrue(result.active,
                        "Campaign with no timestamps anywhere must get synthetic active window")
        self.assertTrue(result.timestamps_are_synthetic,
                        "timestamps_are_synthetic must be True when no timestamps found anywhere")


class TestCampaignExpiryGuard(unittest.TestCase):
    """
    Tests for the timestamps_are_synthetic guard in poll().

    Regression: THE FINALS (explicit endAt May 12, expired) was still reaching
    channel_lookup and farm_selected because poll() had no guard to distinguish
    synthetic timestamps from explicitly expired ones.

    Fix: poll() only bypasses expiry check when campaign.timestamps_are_synthetic=True.
    """

    def test_1_explicitly_expired_inventory_gets_campaign_expired(self):
        """
        Test 1: Inventory campaign with explicit endAt in past, timestamps_are_synthetic=False.
        Expected: reason_code='campaign_expired', fetch_streams NOT called, campaign.active=False.
        """
        now = datetime.now(UTC)
        the_finals = DropCampaign(
            id="real-finals-001",
            game_name="THE FINALS",
            title="THE FINALS Ape Squad Classics",
            starts_at=now - timedelta(days=7),
            ends_at=now - timedelta(hours=2),
            status="EXPIRED",
            required_minutes=240,
            progress_minutes=0,
            drops=_make_drops(1),
            linked=True,
            timestamps_are_synthetic=False,
        )
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [the_finals]

        snapshot = engine.poll()

        engine.client.fetch_streams.assert_not_called()
        finals_d = [d for d in snapshot.decisions if d.campaign.id == "real-finals-001"]
        self.assertEqual(len(finals_d), 1)
        self.assertEqual(finals_d[0].reason_code, "campaign_expired",
                         "Explicitly expired campaign must be campaign_expired, not bypassed")
        self.assertFalse(finals_d[0].campaign.active)

    def test_2_synthetic_timestamps_bypass_still_reaches_fetch_streams(self):
        """
        Test 2 (poll level): Inventory campaign with timestamps_are_synthetic=True.
        Expected: timestamps repaired, fetch_streams called, reason_code != 'campaign_expired'.
        This is the legitimate missing-timestamps bypass case.
        """
        now = datetime.now(UTC)
        arknights = DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            starts_at=now,
            ends_at=now,
            status="EXPIRED",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=True,
            timestamps_are_synthetic=True,
        )
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights]

        snapshot = engine.poll()

        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertIn("ARKNIGHTS: ENDFIELD", fetched,
                      "Campaign with synthetic timestamps must bypass expiry and reach fetch_streams")
        ark_d = [d for d in snapshot.decisions if d.campaign.id == "real-ark-001"]
        self.assertNotEqual(ark_d[0].reason_code, "campaign_expired")
        self.assertTrue(ark_d[0].campaign.active,
                        "Timestamps must be repaired to active after synthetic bypass")

    def test_3_drop_level_expired_timestamp_treated_as_real_expiry(self):
        """
        Test 3 (poll level): Campaign where _parse_campaign() found drop-level past endAt
        sets timestamps_are_synthetic=False. At poll() level this is identical to Test 1 —
        no bypass, reason_code='campaign_expired'.
        """
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-droplevel-exp-001",
            game_name="SOME GAME",
            title="Some Game Campaign",
            starts_at=now - timedelta(days=30),
            ends_at=now - timedelta(hours=1),
            status="EXPIRED",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(3),
            linked=True,
            timestamps_are_synthetic=False,
        )
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [campaign]

        snapshot = engine.poll()

        engine.client.fetch_streams.assert_not_called()
        self.assertEqual(snapshot.decisions[0].reason_code, "campaign_expired",
                         "Campaign with expired drop-level timestamp must be campaign_expired")

    def test_4_real_world_mix_expired_finals_never_farm_selected(self):
        """
        Test 4: THE FINALS expired (explicit endAt, timestamps_are_synthetic=False) +
        ARKNIGHTS active + Infinity Nikki active.
        THE FINALS must be campaign_expired and NOT reach fetch_streams.
        farm_selected must be ARKNIGHTS or Infinity Nikki only.
        """
        now = datetime.now(UTC)
        the_finals = DropCampaign(
            id="real-finals-001",
            game_name="THE FINALS",
            title="THE FINALS Ape Squad Classics",
            starts_at=now - timedelta(days=7),
            ends_at=now - timedelta(hours=2),
            status="EXPIRED",
            required_minutes=240,
            progress_minutes=0,
            drops=_make_drops(1),
            linked=True,
            timestamps_are_synthetic=False,
        )
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)
        nikki = _inventory_campaign("Infinity Nikki", "real-nikki-001", 120, 6)

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [the_finals, arknights, nikki]

        def _mock_fetch_streams(campaign):
            if campaign.game_name == "ARKNIGHTS: ENDFIELD":
                return [StreamCandidate(login="arkchan", display_name="ArkChan",
                                        game_name="ARKNIGHTS: ENDFIELD", viewer_count=1000,
                                        drops_enabled=True)]
            if campaign.game_name == "Infinity Nikki":
                return [StreamCandidate(login="nikkichan", display_name="NikkiChan",
                                        game_name="Infinity Nikki", viewer_count=500,
                                        drops_enabled=True)]
            return []

        engine.client.fetch_streams.side_effect = _mock_fetch_streams
        snapshot = engine.poll()

        fetched_games = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertNotIn("THE FINALS", fetched_games,
                         "fetch_streams must NOT be called for explicitly expired THE FINALS")

        finals_d = [d for d in snapshot.decisions if d.campaign.id == "real-finals-001"]
        self.assertEqual(len(finals_d), 1)
        self.assertEqual(finals_d[0].reason_code, "campaign_expired")

        selected = [d for d in snapshot.decisions if d.reason_code == "stream_selected"]
        self.assertGreater(len(selected), 0, "At least one game must be stream_selected")
        for d in selected:
            self.assertNotEqual(d.campaign.game_name, "THE FINALS",
                                "THE FINALS must never be stream_selected")


class TestManualGameSelectionLogic(unittest.TestCase):
    """
    Tests for the forced-game selection logic of _current_farm_decision().

    Uses a pure-Python helper replicating the logic to verify WHAT HAPPENS after
    _force_farm_game() correctly sets _forced_farm_game (the production fix).

    After the fix, _force_farm_game() sets _forced_farm_game before checking stream
    availability, so the selection logic must honor or clear it as appropriate.
    """

    @staticmethod
    def _pick(decisions: list, forced_game: str = "") -> "FarmDecision | None":
        """Replica of _current_farm_decision() forced-game path, without Qt."""
        def _is_farmable(d):
            c = d.campaign
            if c.requires_subscription and not c.all_drops_claimed:
                return False
            if not (c.active and c.eligible and d.stream is not None):
                return False
            if c.required_minutes > 0 and c.remaining_minutes <= 0:
                return False
            return True

        def _has_actionable(c):
            return c.required_minutes > 0 or c.next_drop_required_minutes > 0 or bool(c.drops)

        def _is_displayable_active(d):
            c = d.campaign
            if c.requires_subscription and not c.all_drops_claimed:
                return False
            if not (c.active and c.eligible):
                return False
            if c.required_minutes > 0 and c.remaining_minutes <= 0:
                return False
            return True

        candidates = [d for d in decisions if _is_farmable(d)]
        if forced_game:
            forced_key = forced_game.casefold()
            forced_decisions = [d for d in decisions
                                if d.campaign.game_name.casefold() == forced_key]
            forced_candidates = [d for d in forced_decisions if _is_farmable(d)]
            if forced_candidates:
                candidates = forced_candidates
            else:
                # Only keep the forced target sticky if it has actionable drop data.
                # Browser-only campaigns with no drops must not block automatic farming.
                forced_still_relevant = any(
                    _is_displayable_active(d) and _has_actionable(d.campaign)
                    for d in forced_decisions
                )
                if forced_still_relevant:
                    return None
                forced_game = ""
        if not candidates:
            return None
        return candidates[0]

    def _browser_decision(self, game_name: str) -> "FarmDecision":
        """Browser-only campaign: required_minutes=0, drops=[], no stream."""
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id=f"browser-{game_name[:8].replace(' ', '_')}",
            game_name=game_name,
            title=f"{game_name} (browser)",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=14),
            status="ACTIVE",
            required_minutes=0,
            progress_minutes=0,
            drops=[],
            linked=True,
            timestamps_are_synthetic=False,
        )
        return FarmDecision(campaign=campaign, stream=None, reason_code="no_actionable_drop_data")

    def _active_decision(self, game_name: str, campaign_id: str) -> "FarmDecision":
        campaign = _inventory_campaign(game_name, campaign_id)
        stream = StreamCandidate(
            login=f"{campaign_id}_ch",
            display_name=f"{campaign_id}_Ch",
            game_name=game_name,
            viewer_count=500,
            drops_enabled=True,
        )
        return FarmDecision(campaign=campaign, stream=stream, reason_code="stream_selected")

    def _expired_decision(self, game_name: str, campaign_id: str) -> "FarmDecision":
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id=campaign_id,
            game_name=game_name,
            title=f"{game_name} Campaign",
            starts_at=now - timedelta(days=7),
            ends_at=now - timedelta(hours=2),
            status="EXPIRED",
            required_minutes=240,
            progress_minutes=0,
            drops=_make_drops(1),
            linked=True,
            timestamps_are_synthetic=False,
        )
        return FarmDecision(campaign=campaign, stream=None, reason_code="campaign_expired")

    def test_5_forced_game_preferred_over_unlisted_first_candidate(self):
        """
        Test 5: forced_game="ARKNIGHTS: ENDFIELD" with Nikki listed first.
        Expected: _current_farm_decision returns ARKNIGHTS, not Nikki.
        """
        nikki_d = self._active_decision("Infinity Nikki", "real-nikki-001")
        ark_d = self._active_decision("ARKNIGHTS: ENDFIELD", "real-ark-001")
        decisions = [nikki_d, ark_d]  # Nikki is first but ARKNIGHTS is forced

        result = self._pick(decisions, forced_game="ARKNIGHTS: ENDFIELD")

        self.assertIsNotNone(result)
        self.assertEqual(result.campaign.game_name, "ARKNIGHTS: ENDFIELD",
                         "Forced ARKNIGHTS must be selected even when Nikki appears first")

    def test_6_forced_expired_game_not_selected_falls_through_to_farmable(self):
        """
        Test 6: forced_game="THE FINALS" but THE FINALS is expired and not displayable_active.
        Expected: forced_game cleared, first farmable (ARKNIGHTS) returned instead.
        THE FINALS must never appear as the selected target.
        """
        finals_d = self._expired_decision("THE FINALS", "real-finals-001")
        ark_d = self._active_decision("ARKNIGHTS: ENDFIELD", "real-ark-001")
        decisions = [finals_d, ark_d]

        result = self._pick(decisions, forced_game="THE FINALS")

        self.assertIsNotNone(result, "When forced expired game is cleared, first farmable must return")
        self.assertNotEqual(result.campaign.game_name, "THE FINALS",
                            "Expired THE FINALS must not be selected even when forced")
        self.assertEqual(result.campaign.game_name, "ARKNIGHTS: ENDFIELD")

    def test_7_forced_game_matching_is_case_insensitive(self):
        """
        Test 7: forced_game in lowercase must match game_name in uppercase.
        """
        ark_d = self._active_decision("ARKNIGHTS: ENDFIELD", "real-ark-001")
        nikki_d = self._active_decision("Infinity Nikki", "real-nikki-001")
        decisions = [nikki_d, ark_d]  # Nikki is first

        result = self._pick(decisions, forced_game="arknights: endfield")

        self.assertIsNotNone(result)
        self.assertEqual(result.campaign.game_name, "ARKNIGHTS: ENDFIELD",
                         "Case-insensitive forced_game must match 'ARKNIGHTS: ENDFIELD'")

    def test_A_forced_browser_only_wow_does_not_block_inventory_farming(self):
        """
        Test A: User clicks World of Warcraft (browser-only, required_minutes=0, drops=[]).
        _forced_farm_game='World of Warcraft'.
        _current_farm_decision must NOT be blocked: WoW has no actionable drop data,
        so it is not 'still relevant' as a forced target.
        ARKNIGHTS: ENDFIELD (inventory, active, has stream) must be returned instead.
        """
        wow_d = self._browser_decision("World of Warcraft")
        ark_d = self._active_decision("ARKNIGHTS: ENDFIELD", "real-ark-001")
        decisions = [wow_d, ark_d]

        result = self._pick(decisions, forced_game="World of Warcraft")

        self.assertIsNotNone(result,
                             "Farming must not be blocked by a browser-only forced target")
        self.assertNotEqual(result.campaign.game_name, "World of Warcraft",
                            "WoW browser-only must not be returned as the farming target")
        self.assertEqual(result.campaign.game_name, "ARKNIGHTS: ENDFIELD",
                         "ARKNIGHTS must be selected when WoW is browser-only with no drops")

    def test_B_forced_inventory_with_stream_is_selected(self):
        """
        Test B: Forced game is ARKNIGHTS (inventory, active, has stream).
        _current_farm_decision must return ARKNIGHTS even when Nikki is listed first.
        """
        nikki_d = self._active_decision("Infinity Nikki", "real-nikki-001")
        ark_d = self._active_decision("ARKNIGHTS: ENDFIELD", "real-ark-001")
        decisions = [nikki_d, ark_d]

        result = self._pick(decisions, forced_game="ARKNIGHTS: ENDFIELD")

        self.assertIsNotNone(result)
        self.assertEqual(result.campaign.game_name, "ARKNIGHTS: ENDFIELD",
                         "Forced Inventory ARKNIGHTS must be selected over first-listed Nikki")

    def test_C_forced_expired_the_finals_clears_and_falls_through(self):
        """
        Test C: forced_game='THE FINALS' but THE FINALS is expired (not displayable_active).
        Forced target is cleared; ARKNIGHTS is returned as the first farmable candidate.
        (Duplicates test_6 from a different angle for clarity.)
        """
        finals_d = self._expired_decision("THE FINALS", "real-finals-001")
        ark_d = self._active_decision("ARKNIGHTS: ENDFIELD", "real-ark-001")
        decisions = [finals_d, ark_d]

        result = self._pick(decisions, forced_game="THE FINALS")

        self.assertIsNotNone(result)
        self.assertNotEqual(result.campaign.game_name, "THE FINALS")
        self.assertEqual(result.campaign.game_name, "ARKNIGHTS: ENDFIELD")

    def test_D_forced_browser_only_with_no_stream_does_not_stop_farming(self):
        """
        Test D: forced browser-only WoW with no stream + no valid Inventory candidates.
        When there are NO farmable candidates at all, return None — but this must be
        because there truly are no candidates, not because WoW is blocking.
        Distinct from Test A: here there ARE no Inventory campaigns, so None is correct.
        """
        wow_d = self._browser_decision("World of Warcraft")
        decisions = [wow_d]  # Only WoW, no inventory candidates

        result = self._pick(decisions, forced_game="World of Warcraft")

        # WoW has no actionable data → forced_still_relevant=False → forced_game cleared
        # → candidates = [d for d if _is_farmable(d)] = [] (WoW has no stream)
        # → return None (correctly — nothing to farm)
        self.assertIsNone(result,
                          "When there are truly no farmable candidates, return None")


class TestInventoryEligibleBypass(unittest.TestCase):
    """
    Tests that Inventory campaigns with linked=False (isAccountConnected=False) still reach
    fetch_streams() in poll().

    Root cause: Twitch's Inventory response may have isAccountConnected=False for games that
    don't require game-account linking for watch-time accumulation (e.g. ARKNIGHTS: ENDFIELD,
    Infinity Nikki). The eligible bypass treats dropCampaignsInProgress membership as proof
    that watch-time can accumulate; account linking is required only at claim time.
    """

    def test_inventory_linked_false_still_reaches_fetch_streams(self):
        """
        Inventory campaign with linked=False (isAccountConnected=False in API response)
        must bypass the eligible gate and reach fetch_streams() in poll().
        """
        now = datetime.now(UTC)
        arknights = DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            starts_at=now - timedelta(days=7),
            ends_at=now + timedelta(days=7),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=False,
            timestamps_are_synthetic=False,
        )
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights]

        snapshot = engine.poll()

        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertIn("ARKNIGHTS: ENDFIELD", fetched,
                      "Inventory campaign with linked=False must bypass eligible check and reach fetch_streams")
        ark_d = [d for d in snapshot.decisions if d.campaign.id == "real-ark-001"]
        self.assertNotEqual(ark_d[0].reason_code, "account_not_linked",
                            "Inventory campaigns must not be account_not_linked")

    def test_inventory_linked_false_with_stream_becomes_stream_selected(self):
        """
        Inventory campaign with linked=False + stream available → reason_code='stream_selected'.
        """
        now = datetime.now(UTC)
        nikki = DropCampaign(
            id="real-nikki-001",
            game_name="Infinity Nikki",
            title="Infinity Nikki Campaign",
            starts_at=now - timedelta(days=7),
            ends_at=now + timedelta(days=7),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(6),
            linked=False,
            timestamps_are_synthetic=False,
        )
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [nikki]
        engine.client.fetch_streams.return_value = [StreamCandidate(
            login="nikkichan",
            display_name="NikkiChan",
            game_name="Infinity Nikki",
            viewer_count=500,
            drops_enabled=True,
        )]

        snapshot = engine.poll()

        nikki_d = [d for d in snapshot.decisions if d.campaign.id == "real-nikki-001"]
        self.assertEqual(nikki_d[0].reason_code, "stream_selected",
                         "Inventory campaign with linked=False + stream must be stream_selected")
        self.assertIsNotNone(nikki_d[0].stream)

    def test_real_world_mix_linked_false_arknights_nikki_active_finals_expired(self):
        """
        Real-world scenario: ARKNIGHTS + Nikki (linked=False, active) + THE FINALS (expired).
        ARKNIGHTS and Nikki must reach fetch_streams; THE FINALS must be campaign_expired.
        At least one of ARKNIGHTS/Nikki must be stream_selected if streams are available.
        """
        now = datetime.now(UTC)
        arknights = DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            starts_at=now - timedelta(days=7),
            ends_at=now + timedelta(days=7),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=False,
            timestamps_are_synthetic=False,
        )
        nikki = DropCampaign(
            id="real-nikki-001",
            game_name="Infinity Nikki",
            title="Infinity Nikki Campaign",
            starts_at=now - timedelta(days=7),
            ends_at=now + timedelta(days=7),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(6),
            linked=False,
            timestamps_are_synthetic=False,
        )
        the_finals = DropCampaign(
            id="real-finals-001",
            game_name="THE FINALS",
            title="THE FINALS Ape Squad Classics",
            starts_at=now - timedelta(days=7),
            ends_at=now - timedelta(hours=2),
            status="EXPIRED",
            required_minutes=240,
            progress_minutes=0,
            drops=_make_drops(1),
            linked=True,
            timestamps_are_synthetic=False,
        )
        browser_wow = _browser_campaign("World of Warcraft", "wow1")

        def _mock_fetch_streams(campaign):
            if campaign.game_name == "ARKNIGHTS: ENDFIELD":
                return [StreamCandidate(login="arkchan", display_name="ArkChan",
                                        game_name="ARKNIGHTS: ENDFIELD", viewer_count=1000,
                                        drops_enabled=True)]
            if campaign.game_name == "Infinity Nikki":
                return [StreamCandidate(login="nikkichan", display_name="NikkiChan",
                                        game_name="Infinity Nikki", viewer_count=500,
                                        drops_enabled=True)]
            return []

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights, nikki, the_finals, browser_wow]
        engine.client.fetch_streams.side_effect = _mock_fetch_streams

        snapshot = engine.poll()

        # THE FINALS must be campaign_expired
        finals_d = [d for d in snapshot.decisions if d.campaign.id == "real-finals-001"]
        self.assertEqual(finals_d[0].reason_code, "campaign_expired")

        # fetch_streams must NOT be called for THE FINALS
        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertNotIn("THE FINALS", fetched)

        # ARKNIGHTS and Nikki must reach fetch_streams
        self.assertIn("ARKNIGHTS: ENDFIELD", fetched,
                      "ARKNIGHTS (linked=False) must reach fetch_streams after eligible bypass")
        self.assertIn("Infinity Nikki", fetched,
                      "Infinity Nikki (linked=False) must reach fetch_streams after eligible bypass")

        # Both must be stream_selected
        selected_games = {d.campaign.game_name for d in snapshot.decisions if d.reason_code == "stream_selected"}
        self.assertIn("ARKNIGHTS: ENDFIELD", selected_games)
        self.assertIn("Infinity Nikki", selected_games)


class TestSubscriptionFilterLogic(unittest.TestCase):
    """
    Tests for subscription-only filtering logic.
    The dashboard checkbox count must reflect campaigns with requires_subscription=True.
    These tests verify the poll()-level gate behavior and decision attributes.
    """

    def test_subscription_required_campaign_gets_correct_reason_code(self):
        """
        Test A: requires_subscription=True campaign gets reason_code='subscription_required'
        from poll(), so the UI filter can count and hide it.
        """
        now = datetime.now(UTC)
        sub_campaign = DropCampaign(
            id="real-sub-001",
            game_name="SubGame",
            title="SubGame Campaign",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=14),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(3),
            linked=True,
            requires_subscription=True,
            timestamps_are_synthetic=False,
        )
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [sub_campaign]

        snapshot = engine.poll()

        engine.client.fetch_streams.assert_not_called()
        sub_d = [d for d in snapshot.decisions if d.campaign.id == "real-sub-001"]
        self.assertEqual(len(sub_d), 1)
        self.assertEqual(sub_d[0].reason_code, "subscription_required",
                         "Sub-only campaign must have reason_code='subscription_required'")
        self.assertTrue(sub_d[0].campaign.requires_subscription,
                        "requires_subscription must be True on the decision's campaign")

    def test_subscription_flag_preserved_in_snapshot_campaigns(self):
        """
        Test B: The FarmSnapshot.campaigns list must preserve requires_subscription=True
        so the dashboard filter can count subscription-only games.
        """
        now = datetime.now(UTC)
        sub_campaign = DropCampaign(
            id="real-sub-001",
            game_name="SubGame",
            title="SubGame Campaign",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=14),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(3),
            linked=True,
            requires_subscription=True,
            timestamps_are_synthetic=False,
        )
        normal = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)

        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [sub_campaign, normal]

        snapshot = engine.poll()

        sub_in_snapshot = [c for c in snapshot.campaigns if c.id == "real-sub-001"]
        self.assertEqual(len(sub_in_snapshot), 1)
        self.assertTrue(sub_in_snapshot[0].requires_subscription,
                        "requires_subscription=True must be preserved in FarmSnapshot.campaigns")

        normal_in_snapshot = [c for c in snapshot.campaigns if c.id == "real-ark-001"]
        self.assertFalse(normal_in_snapshot[0].requires_subscription,
                         "Normal campaign must have requires_subscription=False")

    def test_non_subscription_campaigns_remain_visible(self):
        """
        Test C: Normal campaigns (requires_subscription=False) must not be affected
        by the subscription filter — they must reach fetch_streams and be farm-eligible.
        """
        arknights = _inventory_campaign("ARKNIGHTS: ENDFIELD", "real-ark-001", 120, 5)
        engine = _make_engine()
        engine.client.fetch_campaigns.return_value = [arknights]

        snapshot = engine.poll()

        fetched = {c.args[0].game_name for c in engine.client.fetch_streams.call_args_list}
        self.assertIn("ARKNIGHTS: ENDFIELD", fetched,
                      "Non-subscription campaign must reach fetch_streams")


class TestSubscriptionDetectionHeuristics(unittest.TestCase):
    """Regression tests for subscription-only detection logic in TwitchClient."""

    def test_missing_required_minutes_does_not_infer_subscription_only(self):
        """
        If a drop payload is incomplete and omits requiredMinutesWatched, the
        campaign must NOT be inferred as subscription-only.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        payload = {}
        drops = [{"id": "drop-1", "name": "Incomplete Drop"}]

        result = TwitchClient._campaign_requires_subscription(MagicMock(), payload, drops)

        self.assertFalse(
            result,
            "Missing requiredMinutesWatched must not auto-classify campaign as subscription-only",
        )

    def test_explicit_zero_required_minutes_still_marks_subscription_only(self):
        """
        Campaigns where all known drop requirements are explicit zeros remain
        classified as subscription-only.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        payload = {}
        drops = [
            {"id": "drop-1", "requiredMinutesWatched": 0},
            {"id": "drop-2", "requiredMinutesWatched": 0},
        ]

        result = TwitchClient._campaign_requires_subscription(MagicMock(), payload, drops)

        self.assertTrue(result)

    def test_watchable_drop_overrides_payload_subscription_flags(self):
        """
        Mixed campaigns can contain subscription metadata but still have watchable
        drops; those must not be globally flagged as subscription-only.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        payload = {"requires_subscription": True}
        drops = [{"id": "drop-1", "requiredMinutesWatched": 30}]

        result = TwitchClient._campaign_requires_subscription(MagicMock(), payload, drops)

        self.assertFalse(
            result,
            "Campaign with watchable drops must not be marked subscription-only",
        )


class TestStreamCandidateEligibility(unittest.TestCase):
    """
    Tests for stream source priority and eligibility filtering.

    Root cause of "smugslav" being selected for ARKNIGHTS:
    - fetch_streams() was calling the game directory first even when allowed_channels was set.
    - choose_stream() fell back from filtered (no allowed-channel match) to ALL directory
      streams, picking any DROPS_ENABLED channel regardless of campaign eligibility.

    Fixes:
    - fetch_streams(): if allowed_channels non-empty, use _fetch_streams_from_allowed_channels
      exclusively (no directory fallback).
    - choose_stream(): when campaign.allowed_channels is set, reject streams not in the list.
    """

    def _make_campaign_with_allowed(
        self, allowed_channels: list[str], game_slug: str = "arknights-endfield"
    ) -> DropCampaign:
        now = datetime.now(UTC)
        return DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=14),
            game_slug=game_slug,
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=False,
            allowed_channels=allowed_channels,
        )

    def test_allowed_channels_used_exclusively_when_present(self):
        """
        When campaign.allowed_channels is non-empty and the directory returns that
        channel, fetch_streams() must return it without calling
        _fetch_streams_from_allowed_channels (directory-first, filter-by-allowed).
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = MagicMock()
        client._note = MagicMock()
        live = StreamCandidate(
            login="arkofficialstream",
            display_name="arkofficialstream",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=800,
            drops_enabled=True,
            channel_id="55001",
            broadcast_id="77002",
        )
        # Directory returns the allowed channel
        client._fetch_streams_for_slug.return_value = [live]
        campaign = self._make_campaign_with_allowed(["arkofficialstream"])

        result = TwitchClient.fetch_streams(client, campaign)

        client._fetch_streams_for_slug.assert_called_once()
        client._fetch_streams_from_allowed_channels.assert_not_called()
        client.resolve_game_slug.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].login, "arkofficialstream")

    def test_returns_empty_when_allowed_channels_all_offline(self):
        """
        When allowed_channels is non-empty but the directory has no matching channel
        and the direct fallback also finds nothing live, fetch_streams returns [].
        No ineligible directory stream is ever returned.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = MagicMock()
        client._note = MagicMock()
        # Directory returns a stream NOT in the allowed list.
        unrelated = StreamCandidate(
            login="some_other_channel",
            display_name="some_other_channel",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=200,
            drops_enabled=True,
        )
        client._fetch_streams_for_slug.return_value = [unrelated]
        client._fetch_streams_from_allowed_channels.return_value = []
        campaign = self._make_campaign_with_allowed(["arkofficialstream", "arkstream2"])

        result = TwitchClient.fetch_streams(client, campaign)

        self.assertEqual(result, [])
        client._fetch_streams_for_slug.assert_called_once()
        client._fetch_streams_from_allowed_channels.assert_called_once()

    def test_directory_used_for_open_campaign(self):
        """
        When campaign.allowed_channels is empty (open campaign), the game directory
        is used.  _fetch_streams_from_allowed_channels must NOT be called.
        """
        from twitch_drop_farmer.twitch_client import TwitchClient

        client = MagicMock()
        client._note = MagicMock()
        dir_stream = StreamCandidate(
            login="somechannel",
            display_name="SomeChannel",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=100,
            drops_enabled=True,
        )
        client._fetch_streams_for_slug.return_value = [dir_stream]
        campaign = self._make_campaign_with_allowed([])  # open campaign

        result = TwitchClient.fetch_streams(client, campaign)

        client._fetch_streams_for_slug.assert_called_once()
        client._fetch_streams_from_allowed_channels.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].login, "somechannel")

    def test_choose_stream_rejects_non_allowed_channel(self):
        """
        When campaign.allowed_channels is non-empty and the stream is not in that list,
        choose_stream() must return None.  This prevents farming "smugslav" for ARKNIGHTS
        when "smugslav" is not a campaign-eligible channel.
        """
        engine = _make_engine()
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=14),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=True,
            allowed_channels=["ark_official", "arknights_stream"],
        )
        wrong_stream = StreamCandidate(
            login="smugslav",
            display_name="smugslav",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=1000,
            drops_enabled=True,
        )

        result = engine.choose_stream(campaign, [wrong_stream])

        self.assertIsNone(result,
                          "Non-allowed stream must be rejected when campaign has allowed_channels")

    def test_choose_stream_accepts_allowed_channel(self):
        """
        When a stream IS in allowed_channels, choose_stream must select it.
        """
        engine = _make_engine()
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=14),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(5),
            linked=True,
            allowed_channels=["ark_official"],
        )
        eligible_stream = StreamCandidate(
            login="ark_official",
            display_name="ark_official",
            game_name="ARKNIGHTS: ENDFIELD",
            viewer_count=500,
            drops_enabled=True,
            channel_id="55001",
            broadcast_id="77002",
        )

        result = engine.choose_stream(campaign, [eligible_stream])

        self.assertIsNotNone(result)
        self.assertEqual(result.login, "ark_official")

    def test_choose_stream_open_campaign_accepts_any_drops_enabled(self):
        """
        When campaign.allowed_channels is empty (open campaign), choose_stream
        must accept any non-blacklisted drops-enabled stream.
        """
        engine = _make_engine()
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-open-001",
            game_name="OpenGame",
            title="OpenGame Campaign",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=14),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(3),
            linked=True,
            allowed_channels=[],  # open campaign
        )
        stream = StreamCandidate(
            login="anychannel",
            display_name="AnyChannel",
            game_name="OpenGame",
            viewer_count=200,
            drops_enabled=True,
        )

        result = engine.choose_stream(campaign, [stream])

        self.assertIsNotNone(result)
        self.assertEqual(result.login, "anychannel")


class TestExpiringAlertTimestampSource(unittest.TestCase):
    """
    The campaign_expiring_soon alert must only fire when:
    1. campaign.timestamp_source == "campaign" (real campaign-level endAt)
    2. campaign.seconds_until_end < 3600 (< 60 minutes until the actual campaign end)

    It must NOT fire for:
    - timestamp_source == "drop" (endAt derived from drop-level, not campaign expiry)
    - timestamp_source == "synthetic" (no real timestamps — window is fabricated)
    - campaign.remaining_minutes < 60 (watch time remaining ≠ campaign expiry time)

    Root cause: ARKNIGHTS showed "54 minutes remaining" for days because
    campaign.remaining_minutes (remaining WATCH TIME = required - progress) was
    mistakenly treated as "minutes until campaign expires".  The correct expiry
    metric is campaign.seconds_until_end / 60.
    """

    def _make_expiry_engine(self) -> FarmEngine:
        from twitch_drop_farmer.alerts import AlertType as _AlertType
        config = AppConfig(
            whitelist_games=[],
            blacklist_games=[],
            whitelist_channels=[],
            blacklist_channels=[],
            watchdog_enabled=False,
            alert_campaign_expiring_soon=True,
            alert_farm_complete=False,
            alert_no_progress=False,
            alert_token_invalid=False,
        )
        client = MagicMock()
        client.consume_diagnostics.return_value = []
        client.fetch_streams.return_value = []
        engine = FarmEngine(client=client, config=config)
        engine.alert_manager = MagicMock()
        return engine

    def _was_expiry_alert_raised(self, engine: FarmEngine) -> bool:
        from twitch_drop_farmer.alerts import AlertType as _AlertType
        for call in engine.alert_manager.raise_alert.call_args_list:
            args = call.args
            if args and args[0] == _AlertType.CAMPAIGN_EXPIRING_SOON:
                return True
        return False

    def test_campaign_level_timestamp_near_expiry_triggers_alert(self):
        """
        timestamp_source='campaign', endAt 30 min away → campaign_expiring_soon fires.
        """
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-exp-001",
            game_name="TestGame",
            title="TestGame Campaign",
            starts_at=now - timedelta(days=7),
            ends_at=now + timedelta(minutes=30),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=60,  # 60 watch minutes remaining — must NOT be the trigger
            drops=_make_drops(5),
            linked=True,
            timestamp_source="campaign",
        )
        engine = self._make_expiry_engine()
        engine.client.fetch_campaigns.return_value = [campaign]

        engine.poll()

        self.assertTrue(
            self._was_expiry_alert_raised(engine),
            "campaign_expiring_soon must fire when campaign-level endAt < 60 min away",
        )

    def test_drop_level_timestamp_near_expiry_does_not_trigger_alert(self):
        """
        timestamp_source='drop', endAt 30 min away → NO campaign_expiring_soon.
        ARKNIGHTS: drop has an endAt 30 min away but campaign itself runs for weeks.
        This was the bug causing "54 minutes remaining" for days.
        """
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-ark-001",
            game_name="ARKNIGHTS: ENDFIELD",
            title="ARKNIGHTS Campaign",
            starts_at=now - timedelta(days=30),
            ends_at=now + timedelta(minutes=30),  # from drop-level endAt
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=66,  # ~54 min remaining WATCH TIME — not campaign expiry
            drops=_make_drops(5),
            linked=False,
            timestamp_source="drop",
        )
        engine = self._make_expiry_engine()
        engine.client.fetch_campaigns.return_value = [campaign]

        engine.poll()

        self.assertFalse(
            self._was_expiry_alert_raised(engine),
            "campaign_expiring_soon must NOT fire when timestamp_source='drop'",
        )

    def test_synthetic_timestamp_does_not_trigger_alert(self):
        """
        timestamp_source='synthetic' (no real timestamps) → NO campaign_expiring_soon.
        Synthetic windows are fabricated and must not be used as expiry signals.
        """
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-synth-001",
            game_name="SynthGame",
            title="SynthGame Campaign",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(minutes=30),  # synthetic — not real expiry
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=0,
            drops=_make_drops(3),
            linked=True,
            timestamps_are_synthetic=True,
            timestamp_source="synthetic",
        )
        engine = self._make_expiry_engine()
        engine.client.fetch_campaigns.return_value = [campaign]

        engine.poll()

        self.assertFalse(
            self._was_expiry_alert_raised(engine),
            "campaign_expiring_soon must NOT fire when timestamp_source='synthetic'",
        )

    def test_campaign_level_with_plenty_of_time_does_not_trigger_alert(self):
        """
        timestamp_source='campaign', endAt 7 days away → NO campaign_expiring_soon.
        """
        now = datetime.now(UTC)
        campaign = DropCampaign(
            id="real-ok-001",
            game_name="LongGame",
            title="LongGame Campaign",
            starts_at=now - timedelta(days=7),
            ends_at=now + timedelta(days=7),
            status="ACTIVE",
            required_minutes=120,
            progress_minutes=66,
            drops=_make_drops(5),
            linked=True,
            timestamp_source="campaign",
        )
        engine = self._make_expiry_engine()
        engine.client.fetch_campaigns.return_value = [campaign]

        engine.poll()

        self.assertFalse(
            self._was_expiry_alert_raised(engine),
            "campaign_expiring_soon must NOT fire when endAt is 7 days away",
        )


if __name__ == "__main__":
    unittest.main()
