"""Request budget: how often the app talks to Twitch (campaign list, channel lookups, GraphQL pacing)."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.config import AppConfig  # noqa: E402
from twitch_drop_farmer.farmer import FarmEngine  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, FarmDecision, StreamCandidate  # noqa: E402
from twitch_drop_farmer.twitch_client import TwitchClient  # noqa: E402
from twitch_drop_farmer.ui import (  # noqa: E402
    FORCED_REFRESH_MIN_SEC,
    TRANSLATIONS,
    MainWindow,
)

UTC = timezone.utc


class _Clock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _campaign(name: str, *, data: bool = True, days: int = 5) -> DropCampaign:
    return DropCampaign(
        id=f"id-{name}",
        game_name=name,
        title=f"{name} campaign",
        starts_at=datetime.now(UTC) - timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=days),
        status="ACTIVE",
        required_minutes=120 if data else 0,
        progress_minutes=10 if data else 0,
        has_watchable_drops=data,
        drops=[{"id": f"{name}-d", "name": "Reward", "required_minutes": 120, "current_minutes": 10, "claimed": False}]
        if data
        else [],
    )


def _stream(campaign: DropCampaign, viewers: int = 100) -> StreamCandidate:
    return StreamCandidate(
        login=f"{campaign.id}-chan",
        display_name="Chan",
        game_name=campaign.game_name,
        viewer_count=viewers,
        drops_enabled=True,
        channel_id="1",
    )


class _World:
    """A fake Twitch: a list of campaigns and which of them have a live channel."""

    def __init__(self, campaigns: list[DropCampaign], live: set[str] | None = None) -> None:
        self.campaigns = campaigns
        self.live = {c.id for c in campaigns} if live is None else live
        self.client = MagicMock()
        self.client.consume_diagnostics.side_effect = lambda: []
        self.client.fetch_campaigns.side_effect = lambda **_kw: list(self.campaigns)
        self.client.fetch_streams.side_effect = lambda campaign: (
            [_stream(campaign)] if campaign.id in self.live else []
        )
        self.clock = _Clock()
        self.engine = FarmEngine(self.client, AppConfig(watchdog_enabled=False), clock=self.clock)

    @property
    def lookups(self) -> list[str]:
        return [call.args[0].id for call in self.client.fetch_streams.call_args_list]


class TestCampaignListCache(unittest.TestCase):
    def test_the_campaign_list_is_not_fetched_again_inside_the_refresh_window(self):
        world = _World([_campaign("A")])

        world.engine.poll()
        world.clock.advance(FarmEngine.CAMPAIGN_REFRESH_SEC - 1)
        world.engine.poll()

        self.assertEqual(world.client.fetch_campaigns.call_count, 1)

    def test_it_is_fetched_again_once_the_window_has_passed(self):
        world = _World([_campaign("A")])

        world.engine.poll()
        world.clock.advance(FarmEngine.CAMPAIGN_REFRESH_SEC + 1)
        world.engine.poll()

        self.assertEqual(world.client.fetch_campaigns.call_count, 2)

    def test_force_and_full_scan_bypass_the_cache(self):
        world = _World([_campaign("A")])
        world.engine.poll()

        world.engine.poll(force_campaigns=True)
        world.engine.poll(full_scan=True)

        self.assertEqual(world.client.fetch_campaigns.call_count, 3)

    def test_a_failed_refresh_keeps_the_previous_list_instead_of_emptying_the_dashboard(self):
        world = _World([_campaign("A")])
        world.engine.poll()
        world.campaigns = []  # Twitch is unreachable: fetch_campaigns comes back empty

        snapshot = world.engine.poll(force_campaigns=True)

        self.assertEqual([c.game_name for c in snapshot.campaigns], ["A"])
        self.assertTrue(any("lista anterior" in message for message in snapshot.messages))

    def test_with_nothing_cached_an_empty_answer_is_just_empty(self):
        world = _World([])

        snapshot = world.engine.poll()

        self.assertEqual(snapshot.campaigns, [])

    def test_progress_the_ui_merged_into_a_campaign_survives_the_next_light_poll(self):
        world = _World([_campaign("A")])
        first = world.engine.poll().campaigns[0]
        first.progress_minutes = 77  # what the UI does after a heartbeat reconcile

        second = world.engine.poll().campaigns[0]

        self.assertIs(second, first)
        self.assertEqual(second.progress_minutes, 77)


class TestChannelLookupBudget(unittest.TestCase):
    def test_a_poll_does_not_ask_about_every_game(self):
        world = _World([_campaign(f"G{i:03d}") for i in range(100)])

        snapshot = world.engine.poll()

        budget = FarmEngine.MAX_FRONT_LOOKUPS + FarmEngine.MAX_BACKGROUND_LOOKUPS
        self.assertLessEqual(world.client.fetch_streams.call_count, budget)
        unchecked = [d for d in snapshot.decisions if d.reason_code == "stream_unchecked"]
        self.assertGreater(len(unchecked), 80)
        self.assertTrue(all(d.stream is None for d in unchecked))

    def test_the_farmed_campaign_is_looked_up_on_every_poll(self):
        world = _World([_campaign("A"), _campaign("B"), _campaign("C")])
        world.engine.poll()  # everything is looked up once
        world.engine.set_focus("id-B")
        before = len(world.lookups)

        world.clock.advance(60)
        world.engine.poll()
        world.clock.advance(60)
        world.engine.poll()

        self.assertEqual(world.lookups[before:], ["id-B", "id-B"])

    def test_games_not_in_focus_keep_their_last_answer_until_it_goes_stale(self):
        world = _World([_campaign("A"), _campaign("B"), _campaign("C")])
        world.engine.poll()
        looked_up = len(world.lookups)

        world.clock.advance(FarmEngine.FRONT_TTL_SEC - 1)
        snapshot = world.engine.poll()

        self.assertEqual(len(world.lookups), looked_up)
        self.assertTrue(all(d.reason_code == "stream_selected" for d in snapshot.decisions))

    def test_the_next_candidates_are_re_checked_after_the_front_ttl(self):
        world = _World([_campaign("A"), _campaign("B"), _campaign("C")])
        world.engine.poll()
        looked_up = len(world.lookups)

        world.clock.advance(FarmEngine.FRONT_TTL_SEC + 1)
        world.engine.poll()

        self.assertGreater(len(world.lookups), looked_up)

    def test_campaigns_with_real_drop_data_are_looked_up_before_registry_only_ones(self):
        no_data = [_campaign(f"R{i:02d}", data=False, days=1) for i in range(20)]  # end sooner
        with_data = [_campaign("Progress", data=True, days=10)]
        world = _World(no_data + with_data, live=set())

        world.engine.poll()

        self.assertEqual(world.lookups[0], "id-Progress")

    def test_the_walk_goes_on_until_it_finds_live_channels_for_the_next_candidates(self):
        campaigns = [_campaign(f"G{i:02d}", days=1 + i) for i in range(10)]
        # Only the 4th and 5th have a live channel: the farm must still find them at once.
        world = _World(campaigns, live={"id-G03", "id-G04"})

        snapshot = world.engine.poll()

        selected = [d.campaign.game_name for d in snapshot.decisions if d.reason_code == "stream_selected"]
        self.assertEqual(selected, ["G03", "G04"])

    def test_a_first_failed_lookup_is_reported_as_no_stream_and_retried_next_poll(self):
        world = _World([_campaign("A")])
        world.client.fetch_streams.side_effect = RuntimeError("network down")

        first = world.engine.poll()
        self.assertEqual(first.decisions[0].reason_code, "no_valid_stream")

        world.client.fetch_streams.side_effect = lambda campaign: [_stream(campaign)]
        world.engine.set_focus("id-A")
        second = world.engine.poll()
        self.assertEqual(second.decisions[0].reason_code, "stream_selected")

    def test_a_failed_refresh_keeps_the_last_known_streams(self):
        world = _World([_campaign("A")])
        world.engine.poll()
        world.engine.set_focus("id-A")
        world.client.fetch_streams.side_effect = RuntimeError("network down")

        snapshot = world.engine.poll()

        self.assertEqual(snapshot.decisions[0].reason_code, "stream_selected")

    def test_a_lookup_made_by_the_ui_is_remembered(self):
        world = _World([_campaign("A")], live=set())
        campaign = world.campaigns[0]
        world.engine.poll()
        looked_up = len(world.lookups)

        world.engine.remember_streams(campaign, [_stream(campaign)])
        snapshot = world.engine.poll()

        self.assertEqual(len(world.lookups), looked_up)
        self.assertEqual(snapshot.decisions[0].reason_code, "stream_selected")

    def test_each_poll_says_how_many_channel_lookups_it_made(self):
        world = _World([_campaign(f"G{i:02d}") for i in range(30)])

        snapshot = world.engine.poll()

        line = next(m for m in snapshot.messages if m.startswith("Canais:"))
        self.assertIn(f"{world.client.fetch_streams.call_count} consulta(s)", line)
        self.assertIn("por verificar", line)


class _ClientWithFakeTime(TwitchClient):
    pass


def _client() -> tuple[TwitchClient, _Clock, list[float]]:
    client = TwitchClient()
    clock, sleeps = _Clock(), []
    client._clock = clock
    client._sleep = lambda seconds: (sleeps.append(round(seconds, 3)), clock.advance(seconds))
    return client, clock, sleeps


def _http_error(status: int, headers: dict[str, str] | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    return requests.HTTPError(f"{status}", response=response)


def _ok_response(data: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = data
    return response


class TestGraphqlPacing(unittest.TestCase):
    def test_back_to_back_requests_are_spaced_out(self):
        client, _clock, sleeps = _client()

        for _ in range(3):
            client._gql_wait_turn()

        self.assertEqual(sleeps, [0.3, 0.3])

    def test_requests_that_are_already_far_apart_do_not_wait(self):
        client, clock, sleeps = _client()

        client._gql_wait_turn()
        clock.advance(5)
        client._gql_wait_turn()

        self.assertEqual(sleeps, [])

    def test_a_429_stops_at_once_without_trying_the_other_profile(self):
        client, _clock, _sleeps = _client()
        post = MagicMock(side_effect=_http_error(429, {"Retry-After": "30"}))
        client.session.post = post

        with self.assertRaises(requests.HTTPError):
            client._post_gql({"operationName": "X"})

        self.assertEqual(post.call_count, 1)

    def test_every_request_waits_out_the_pause_and_none_is_sent(self):
        client, clock, _sleeps = _client()
        post = MagicMock(side_effect=_http_error(429, {"Retry-After": "30"}))
        client.session.post = post
        with self.assertRaises(requests.HTTPError):
            client._post_gql({"operationName": "X"})

        clock.advance(10)
        with self.assertRaises(requests.RequestException) as caught:
            client._post_gql({"operationName": "X"})
        self.assertIn("Pausa", str(caught.exception))
        with self.assertRaises(requests.RequestException):
            client._post_gql_web({"operationName": "X"})

        self.assertEqual(post.call_count, 1)

    def test_requests_resume_after_the_pause(self):
        client, clock, _sleeps = _client()
        client.session.post = MagicMock(side_effect=_http_error(429, {"Retry-After": "30"}))
        with self.assertRaises(requests.HTTPError):
            client._post_gql({"operationName": "X"})

        clock.advance(31)
        client.session.post = MagicMock(return_value=_ok_response({"data": {"ok": True}}))

        self.assertEqual(client._post_gql({"operationName": "X"}), {"data": {"ok": True}})

    def test_a_missing_retry_after_uses_the_default_pause(self):
        client, clock, _sleeps = _client()
        client.session.post = MagicMock(side_effect=_http_error(429))
        with self.assertRaises(requests.HTTPError):
            client._post_gql({"operationName": "X"})

        self.assertAlmostEqual(client._gql_paused_until - clock.now, 60.0)

    def test_a_huge_retry_after_is_capped(self):
        client, clock, _sleeps = _client()
        client.session.post = MagicMock(side_effect=_http_error(429, {"Retry-After": "999999"}))
        with self.assertRaises(requests.HTTPError):
            client._post_gql({"operationName": "X"})

        self.assertAlmostEqual(client._gql_paused_until - clock.now, 900.0)

    def test_other_http_errors_still_fall_back_to_the_other_profile(self):
        client, _clock, _sleeps = _client()
        post = MagicMock(side_effect=_http_error(500))
        client.session.post = post

        with self.assertRaises(requests.HTTPError):
            client._post_gql({"operationName": "X"})

        self.assertEqual(post.call_count, 2)


def _window() -> MagicMock:
    fake = MagicMock()
    fake._snap_future = None
    fake._heartbeat_future = None
    fake._last_forced_refresh_at = None
    fake._sticky_campaign_id = "sticky"
    fake._forced_farm_campaign_id = "forced"
    fake._t = lambda key, **kw: TRANSLATIONS["pt_PT"][key].format(**kw)
    return fake


class TestUiRefresh(unittest.TestCase):
    def test_a_normal_refresh_is_light_and_focuses_the_campaign_being_farmed(self):
        fake = _window()

        MainWindow.refresh_snapshot(fake)

        fake.engine.set_focus.assert_called_once_with("sticky", "forced")
        fake.executor.submit.assert_called_once_with(fake.engine.poll, force_campaigns=False)

    def test_a_forced_refresh_fetches_the_campaigns_but_not_twice_in_a_row(self):
        fake = _window()
        with patch("twitch_drop_farmer.ui.time.monotonic") as monotonic:
            monotonic.return_value = 1000.0
            MainWindow.refresh_snapshot(fake, force=True)
            monotonic.return_value = 1000.0 + FORCED_REFRESH_MIN_SEC - 1
            MainWindow.refresh_snapshot(fake, force=True)
            monotonic.return_value = 1000.0 + FORCED_REFRESH_MIN_SEC + 1
            MainWindow.refresh_snapshot(fake, force=True)

        forced = [call.kwargs["force_campaigns"] for call in fake.executor.submit.call_args_list]
        self.assertEqual(forced, [True, False, True])

    def test_a_refresh_is_skipped_while_another_is_running(self):
        fake = _window()
        fake._snap_future = MagicMock()
        fake._snap_future.done.return_value = False

        MainWindow.refresh_snapshot(fake)

        fake.executor.submit.assert_not_called()

    def test_picking_a_game_looks_its_channel_up_again(self):
        fake = _window()
        campaign = _campaign("A")
        decision = FarmDecision(campaign=campaign, stream=None, reason_code="stream_unchecked")
        live = _stream(campaign)
        fake.client.fetch_streams.return_value = [live]
        fake.engine.choose_stream.return_value = live

        ok = MainWindow._verify_decision_stream(fake, decision)

        self.assertTrue(ok)
        self.assertIs(decision.stream, live)
        self.assertEqual(decision.reason_code, "stream_selected")
        fake.engine.remember_streams.assert_called_once_with(campaign, [live])

    def test_a_game_that_went_offline_is_not_selected(self):
        fake = _window()
        campaign = _campaign("A")
        decision = FarmDecision(campaign=campaign, stream=_stream(campaign), reason_code="stream_selected")
        fake.client.fetch_streams.return_value = []
        fake.engine.choose_stream.return_value = None

        self.assertFalse(MainWindow._verify_decision_stream(fake, decision))
        self.assertIsNone(decision.stream)
        self.assertEqual(decision.reason_code, "no_valid_stream")

    def test_a_failed_check_does_not_discard_the_known_channel(self):
        fake = _window()
        campaign = _campaign("A")
        known = _stream(campaign)
        decision = FarmDecision(campaign=campaign, stream=known, reason_code="stream_selected")
        fake.client.fetch_streams.side_effect = RuntimeError("network down")

        self.assertTrue(MainWindow._verify_decision_stream(fake, decision))
        self.assertIs(decision.stream, known)

    def test_the_unchecked_state_has_a_text_in_both_languages(self):
        for language in ("pt_PT", "en"):
            self.assertIn("reason_stream_unchecked", TRANSLATIONS[language])
        fake = MagicMock()
        fake._t = lambda key, **kw: TRANSLATIONS["pt_PT"][key].format(**kw)
        decision = FarmDecision(campaign=_campaign("A"), stream=None, reason_code="stream_unchecked")
        self.assertEqual(MainWindow._reason_text(fake, decision), TRANSLATIONS["pt_PT"]["reason_stream_unchecked"])


if __name__ == "__main__":
    unittest.main()
