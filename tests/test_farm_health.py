"""Stall detection and recovery: the monitor, the engine's channel choice and the UI actions."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.alerts import AlertManager, AlertType  # noqa: E402
from twitch_drop_farmer.config import AppConfig  # noqa: E402
from twitch_drop_farmer.farm_health import (  # noqa: E402
    BLACKOUT_SEC,
    LEVEL_CAMPAIGN,
    LEVEL_CHANNEL,
    LEVEL_RESTART,
    Action,
    FarmHealth,
    thresholds,
)
from twitch_drop_farmer.farmer import FarmEngine  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, FarmDecision, StreamCandidate  # noqa: E402
from twitch_drop_farmer.twitch_client import TwitchClient  # noqa: E402
from twitch_drop_farmer.ui import (  # noqa: E402
    CAMPAIGN_HOLD_SEC,
    CHANNEL_PENALTY_SEC,
    TRANSLATIONS,
    MainWindow,
)

UTC = timezone.utc


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _run(health: FarmHealth, clock: _Clock, minutes: int, *, campaign="c1", channel="chan",
         progress=lambda minute: 100, start: int = 1) -> dict[int, Action]:
    """Observe once a minute and return the minute at which each step fired."""
    fired: dict[int, Action] = {}
    for minute in range(start, start + minutes):
        clock.advance(60)
        health.observe(campaign, channel, progress(minute))
        action = health.check()
        if action is not Action.NONE:
            fired[minute] = action
    return fired


def _health(timeout: float = 30.0) -> tuple[FarmHealth, _Clock]:
    clock = _Clock()
    health = FarmHealth(timeout, clock=clock)
    health.observe("c1", "chan", 100)  # first sight of the target, at minute 0
    return health, clock


class TestThresholds(unittest.TestCase):
    def test_the_steps_are_fractions_of_the_timeout(self):
        self.assertEqual(thresholds(30), (6.0, 15.0, 30.0))
        self.assertEqual(thresholds(120), (24.0, 60.0, 120.0))

    def test_a_tiny_timeout_is_clamped_and_the_steps_stay_in_order(self):
        restart, channel, campaign = thresholds(5)
        self.assertGreaterEqual(restart, 4.0)
        self.assertLess(restart, channel)
        self.assertLess(channel, campaign)


class TestFarmHealth(unittest.TestCase):
    def test_nothing_fires_while_progress_keeps_moving(self):
        health, clock = _health()

        fired = _run(health, clock, 90, progress=lambda minute: 100 + minute)

        self.assertEqual(fired, {})

    def test_a_stalled_campaign_escalates_restart_then_channel_then_campaign_once_each(self):
        health, clock = _health()

        fired = _run(health, clock, 45)

        self.assertEqual(fired, {6: Action.RESTART_WATCH, 15: Action.SWITCH_CHANNEL, 30: Action.SWITCH_CAMPAIGN})

    def test_progress_before_the_first_step_resets_the_clock(self):
        health, clock = _health()
        _run(health, clock, 5)  # stalled for 5 minutes: not yet

        fired = _run(health, clock, 10, start=6, progress=lambda minute: 101)  # minute 6 brings +1

        # The clock restarted at minute 6, so the first step comes 6 minutes later (minute 12),
        # not at minute 6 counted from the very first observation.
        self.assertEqual(fired, {12: Action.RESTART_WATCH})

    def test_recovery_is_reported_once_with_how_far_it_went(self):
        health, clock = _health()
        _run(health, clock, 7)  # the restart fired at minute 6
        self.assertEqual(health.take_recovered(), 0)

        _run(health, clock, 1, start=8, progress=lambda minute: 101)

        self.assertEqual(health.take_recovered(), LEVEL_RESTART)
        self.assertEqual(health.take_recovered(), 0)

    def test_a_channel_switch_gives_the_new_channel_fresh_steps_but_not_a_fresh_campaign_clock(self):
        health, clock = _health()
        _run(health, clock, 15)  # SWITCH_CHANNEL fired at minute 15

        fired = _run(health, clock, 20, start=16, channel="other")

        # The new channel gets its own restart (6 minutes after it appeared, minute 22) ...
        self.assertEqual(fired.get(22), Action.RESTART_WATCH)
        # ... but the campaign has gone 30 minutes without progress, so it is given up at minute 30.
        self.assertEqual(fired.get(30), Action.SWITCH_CAMPAIGN)

    def test_recovery_after_a_channel_switch_is_credited_to_the_new_channel(self):
        health, clock = _health()
        _run(health, clock, 15)
        _run(health, clock, 1, start=16, channel="other")

        _run(health, clock, 1, start=17, channel="other", progress=lambda minute: 101)

        self.assertEqual(health.take_recovered(), LEVEL_CHANNEL)

    def test_giving_up_on_a_campaign_is_reported_as_the_furthest_level(self):
        health, clock = _health()
        _run(health, clock, 31)

        _run(health, clock, 1, start=32, campaign="c2", progress=lambda minute: 5)
        _run(health, clock, 1, start=33, campaign="c2", progress=lambda minute: 6)

        self.assertEqual(health.take_recovered(), LEVEL_CAMPAIGN)

    def test_a_different_campaign_starts_with_a_clean_slate(self):
        health, clock = _health()
        _run(health, clock, 31)

        fired = _run(health, clock, 5, start=32, campaign="c2", progress=lambda minute: 5)

        self.assertEqual(fired, {})
        self.assertEqual(health.campaign_stalled_minutes(), 4.0)

    def test_time_when_nothing_was_observed_is_not_counted_as_a_stall(self):
        health, clock = _health()
        _run(health, clock, 5)

        clock.advance(BLACKOUT_SEC * 7)  # the app was offline / asleep for 21 minutes
        health.observe("c1", "chan", 100)

        self.assertEqual(health.check(), Action.NONE)
        self.assertLess(health.stalled_minutes(), 6.0)

    def test_it_does_nothing_when_disabled(self):
        health, clock = _health()
        health.enabled = False

        self.assertEqual(_run(health, clock, 45), {})

    def test_reset_forgets_the_target_and_the_pending_recovery(self):
        health, clock = _health()
        _run(health, clock, 7)

        health.reset()

        self.assertEqual(health.check(), Action.NONE)
        self.assertEqual(health.take_recovered(), 0)
        self.assertEqual(health.stalled_minutes(), 0.0)


def _stream(login: str, viewers: int, *, drops: bool = True) -> StreamCandidate:
    return StreamCandidate(login=login, display_name=login, game_name="G", viewer_count=viewers,
                           drops_enabled=drops, channel_id="1")


def _campaign(campaign_id: str = "c1", game: str = "Game") -> DropCampaign:
    return DropCampaign(
        id=campaign_id, game_name=game, title=game, starts_at=datetime.now(UTC) - timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=3), status="ACTIVE", required_minutes=360,
        progress_minutes=100, has_watchable_drops=True,
        drops=[{"id": "d", "name": "r", "required_minutes": 360, "current_minutes": 100, "claimed": False}],
    )


def _engine(**config) -> tuple[FarmEngine, _Clock]:
    clock = _Clock()
    client = MagicMock()
    client.consume_diagnostics.side_effect = lambda: []
    return FarmEngine(client, AppConfig(**config), clock=clock), clock


class TestChannelChoice(unittest.TestCase):
    def test_without_a_current_channel_the_biggest_one_wins(self):
        engine, _ = _engine()
        self.assertEqual(engine.choose_stream(_campaign(), [_stream("a", 100), _stream("b", 500)]).login, "b")

    def test_the_current_channel_is_kept_even_when_a_bigger_one_appears(self):
        engine, _ = _engine()
        engine.set_current_channel("A")  # case does not matter

        chosen = engine.choose_stream(_campaign(), [_stream("a", 100), _stream("b", 500)])

        self.assertEqual(chosen.login, "a")

    def test_a_whitelisted_channel_still_beats_the_current_one(self):
        engine, _ = _engine(whitelist_channels=["b"])
        engine.set_current_channel("a")

        self.assertEqual(engine.choose_stream(_campaign(), [_stream("a", 100), _stream("b", 5)]).login, "b")

    def test_being_current_does_not_rescue_a_channel_without_drops(self):
        engine, _ = _engine()
        engine.set_current_channel("a")

        chosen = engine.choose_stream(_campaign(), [_stream("a", 100, drops=False), _stream("b", 5)])

        self.assertEqual(chosen.login, "b")

    def test_a_current_channel_that_left_the_list_is_replaced(self):
        engine, _ = _engine()
        engine.set_current_channel("gone")

        self.assertEqual(engine.choose_stream(_campaign(), [_stream("b", 5), _stream("c", 50)]).login, "c")

    def test_a_penalized_channel_is_skipped_until_the_penalty_ends(self):
        engine, clock = _engine()
        engine.set_current_channel("a")
        engine.penalize_channel("A", 600)
        streams = [_stream("a", 500), _stream("b", 5)]

        self.assertEqual(engine.choose_stream(_campaign(), streams).login, "b")
        clock.advance(601)
        self.assertEqual(engine.choose_stream(_campaign(), streams).login, "a")

    def test_when_every_channel_is_penalized_there_is_no_stream(self):
        engine, _ = _engine()
        engine.penalize_channel("a", 600)

        self.assertIsNone(engine.choose_stream(_campaign(), [_stream("a", 500)]))

    def test_reselect_moves_a_decision_to_another_channel_without_asking_twitch(self):
        engine, _ = _engine()
        campaign = _campaign()
        streams = [_stream("a", 500), _stream("b", 5)]
        engine.remember_streams(campaign, streams)
        decision = FarmDecision(campaign=campaign, stream=streams[0], reason_code="stream_selected")
        engine.penalize_channel("a", 600)

        engine.reselect(decision)

        self.assertEqual(decision.stream.login, "b")
        self.assertEqual(decision.reason_code, "stream_selected")
        engine.client.fetch_streams.assert_not_called()

    def test_reselect_with_no_alternative_leaves_the_decision_without_a_stream(self):
        engine, _ = _engine()
        campaign = _campaign()
        engine.remember_streams(campaign, [_stream("a", 500)])
        decision = FarmDecision(campaign=campaign, stream=_stream("a", 500), reason_code="stream_selected")
        engine.penalize_channel("a", 600)

        engine.reselect(decision)

        self.assertIsNone(decision.stream)
        self.assertEqual(decision.reason_code, "no_valid_stream")

    def test_a_channel_is_live_while_the_last_lookup_lists_it(self):
        engine, _ = _engine()
        campaign = _campaign()
        engine.remember_streams(campaign, [_stream("Alpha", 5), _stream("beta", 9)])

        self.assertTrue(engine.is_channel_live(campaign.id, "alpha"))  # case does not matter
        self.assertFalse(engine.is_channel_live(campaign.id, "gone"))

    def test_with_no_lookup_yet_a_channel_is_not_reported_as_offline(self):
        engine, _ = _engine()

        self.assertTrue(engine.is_channel_live("never-looked-up", "anything"))

    def test_the_penalty_is_visible_from_outside(self):
        engine, clock = _engine()
        engine.penalize_channel("Chan", 60)

        self.assertTrue(engine.is_channel_penalized("chan"))
        clock.advance(61)
        self.assertFalse(engine.is_channel_penalized("chan"))

    def test_the_old_poll_time_watchdog_is_gone(self):
        engine, _ = _engine()
        self.assertFalse(hasattr(engine, "watchdog"))


def _window(*decisions: FarmDecision) -> MagicMock:
    fake = MagicMock()
    fake._t = lambda key, **kw: TRANSLATIONS["pt_PT"][key].format(**kw)
    fake.latest_snapshot = MagicMock(decisions=list(decisions))
    fake._campaign_hold = {}
    fake._sticky_campaign_id = ""
    fake._forced_farm_campaign_id = ""
    fake._forced_farm_channel = ""
    fake._forced_farm_game = ""
    fake._farm_health = MagicMock()
    fake._farm_health.stalled_minutes.return_value = 12.0
    fake._farm_health.campaign_stalled_minutes.return_value = 30.0
    for name in ("_run_recovery", "_watch_farm_health", "_announce_recovered", "_watchdog_alert",
                 "_decision_for_campaign", "_campaign_on_hold"):
        setattr(fake, name, (lambda n: lambda *a, **kw: getattr(MainWindow, n)(fake, *a, **kw))(name))
    return fake


class TestRecoveryActions(unittest.TestCase):
    def setUp(self):
        self.manager = AlertManager(dedupe_window_sec=0)
        patcher = patch("twitch_drop_farmer.ui.get_alert_manager", return_value=self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_restart_forgets_the_watch_session_and_restarts_the_watcher_without_an_alert(self):
        fake = _window()

        MainWindow._run_recovery(fake, Action.RESTART_WATCH, "c1", "Game", "chan")

        fake.client.reset_watch_session.assert_called_once_with("chan")
        fake.client.segment_watcher.stop.assert_called_once()
        fake.client.segment_watcher.set_channel.assert_called_once_with("chan")
        self.assertEqual(self.manager.alerts, [])
        self.assertIn("a reiniciar a vigilância", fake._log.call_args[0][0])

    def test_switching_channel_penalizes_it_picks_another_at_once_and_alerts(self):
        decision = FarmDecision(campaign=_campaign(), stream=_stream("chan", 5), reason_code="stream_selected")
        fake = _window(decision)
        fake._forced_farm_channel = "chan"

        MainWindow._run_recovery(fake, Action.SWITCH_CHANNEL, "c1", "Game", "chan")

        fake.engine.penalize_channel.assert_called_once_with("chan", CHANNEL_PENALTY_SEC)
        fake.engine.reselect.assert_called_once_with(decision)
        fake.client.reset_watch_session.assert_called_once_with("chan")
        fake._streamless_heartbeat_tick.assert_called_once()
        fake.refresh_snapshot.assert_called_once()
        self.assertEqual(fake._forced_farm_channel, "")
        self.assertEqual([a.alert_type for a in self.manager.alerts], [AlertType.NO_PROGRESS])
        self.assertIn("chan", self.manager.alerts[0].message)

    def test_giving_up_on_a_campaign_holds_it_and_drops_a_manual_pick_of_it(self):
        fake = _window()
        fake._sticky_campaign_id = "c1"
        fake._forced_farm_campaign_id = "c1"
        fake._forced_farm_game = "Game"
        fake._forced_farm_channel = "chan"

        with patch("twitch_drop_farmer.ui.time.monotonic", return_value=5000.0):
            MainWindow._run_recovery(fake, Action.SWITCH_CAMPAIGN, "c1", "Game", "chan")

        self.assertEqual(fake._campaign_hold, {"c1": 5000.0 + CAMPAIGN_HOLD_SEC})
        self.assertEqual((fake._sticky_campaign_id, fake._forced_farm_campaign_id, fake._forced_farm_game), ("", "", ""))
        fake._streamless_heartbeat_tick.assert_called_once()
        self.assertEqual([a.alert_type for a in self.manager.alerts], [AlertType.NO_PROGRESS])

    def test_a_manual_pick_of_another_campaign_is_left_alone(self):
        fake = _window()
        fake._forced_farm_campaign_id = "other"

        MainWindow._run_recovery(fake, Action.SWITCH_CAMPAIGN, "c1", "Game", "chan")

        self.assertEqual(fake._forced_farm_campaign_id, "other")

    def test_a_held_campaign_is_not_picked_and_comes_back_when_the_hold_ends(self):
        alpha, beta = _campaign("c1", "Alpha"), _campaign("c2", "Beta")
        decisions = [FarmDecision(campaign=c, stream=_stream(f"{c.id}-ch", 5), reason_code="stream_selected")
                     for c in (alpha, beta)]
        fake = _window(*decisions)
        fake._decision_is_farmable_now = lambda d: True
        fake._decision_is_displayable_active = lambda d: True
        fake._campaign_hold = {"c1": 5000.0}

        with patch("twitch_drop_farmer.ui.time.monotonic", return_value=4000.0):
            self.assertEqual(MainWindow._pick_farm_decision(fake).campaign.id, "c2")
        with patch("twitch_drop_farmer.ui.time.monotonic", return_value=5001.0):
            self.assertEqual(MainWindow._pick_farm_decision(fake).campaign.id, "c1")
        self.assertEqual(fake._campaign_hold, {})

    def test_a_recovery_after_a_switch_raises_a_notice_but_after_a_restart_only_logs(self):
        fake = _window()

        MainWindow._announce_recovered(fake, "Game", LEVEL_RESTART)
        self.assertEqual(self.manager.alerts, [])
        fake._log.assert_called_once()

        MainWindow._announce_recovered(fake, "Game", LEVEL_CHANNEL)
        self.assertEqual([a.alert_type for a in self.manager.alerts], [AlertType.WATCHDOG_RECOVERED])


class TestHeartbeatFeedsTheMonitor(unittest.TestCase):
    def _beat(self, *, ok: bool = True) -> MagicMock:
        fake = MagicMock()
        future = MagicMock()
        future.done.return_value = True
        reconciled = MagicMock(progress_minutes=160, required_minutes=360, id="cid")
        future.result.return_value = (ok, [], reconciled if ok else None, None)
        fake._heartbeat_future = future
        fake._heartbeat_pending_campaign_id = "cid"
        fake._heartbeat_pending_game_name = "MARVEL SNAP"
        fake._heartbeat_pending_channel = "somechannel"
        fake._heartbeat_no_progress_cycles = 0
        fake._apply_reconciled_campaign_progress.return_value = (159, "cid")
        MainWindow._poll_heartbeat_future(fake)
        return fake

    def test_the_farmed_campaign_progress_is_fed_after_each_reconcile(self):
        fake = self._beat()

        fake._watch_farm_health.assert_called_once_with("cid", "MARVEL SNAP", "somechannel", 160)

    def test_a_failed_heartbeat_is_not_blamed_on_the_channel(self):
        fake = self._beat(ok=False)

        fake._watch_farm_health.assert_not_called()


class TestWatchFarmHealth(unittest.TestCase):
    def test_the_monitor_is_fed_and_its_answer_is_acted_on(self):
        fake = _window()
        fake._farm_health.take_recovered.return_value = 0
        fake._farm_health.check.return_value = Action.SWITCH_CHANNEL
        fake._run_recovery = MagicMock()

        MainWindow._watch_farm_health(fake, "c1", "Game", "chan", 100)

        fake._farm_health.observe.assert_called_once_with("c1", "chan", 100)
        fake._run_recovery.assert_called_once_with(Action.SWITCH_CHANNEL, "c1", "Game", "chan")

    def test_nothing_happens_when_the_monitor_sees_no_stall(self):
        fake = _window()
        fake._farm_health.take_recovered.return_value = 0
        fake._farm_health.check.return_value = Action.NONE
        fake._run_recovery = MagicMock()

        MainWindow._watch_farm_health(fake, "c1", "Game", "chan", 100)

        fake._run_recovery.assert_not_called()

    def test_without_a_campaign_or_channel_it_is_ignored(self):
        fake = _window()

        MainWindow._watch_farm_health(fake, "", "Game", "chan", 100)
        MainWindow._watch_farm_health(fake, "c1", "Game", "", 100)

        fake._farm_health.observe.assert_not_called()

    def test_the_settings_reach_the_monitor(self):
        fake = MagicMock()
        fake.config = AppConfig()

        MainWindow.handle_watchdog_timeout_change(fake, 20)
        self.assertEqual(fake.config.watchdog_stall_timeout_min, 20)
        fake._farm_health.set_timeout.assert_called_once_with(20)

        MainWindow.handle_watchdog_toggle(fake, False)
        self.assertFalse(fake._farm_health.enabled)


class TestClientReset(unittest.TestCase):
    def test_reset_watch_session_forgets_the_cached_playlist_and_stream_info(self):
        client = TwitchClient()
        client._streamless_media_playlist_cache["somechannel"] = "https://edge/playlist.m3u8"
        client._streamless_stream_info_cache["somechannel"] = ("1", "2", "3", 0.0)
        client._streamless_media_playlist_cache["other"] = "keep"

        client.reset_watch_session("SomeChannel")

        self.assertNotIn("somechannel", client._streamless_media_playlist_cache)
        self.assertNotIn("somechannel", client._streamless_stream_info_cache)
        self.assertEqual(client._streamless_media_playlist_cache["other"], "keep")


class TestTranslations(unittest.TestCase):
    def test_every_new_text_exists_in_both_languages(self):
        keys = ("watchdog_title", "watchdog_restart", "watchdog_switch_channel", "watchdog_switch_campaign",
                "watchdog_recovered_title", "watchdog_recovered")
        for language in ("pt_PT", "en"):
            for key in keys:
                self.assertIn(key, TRANSLATIONS[language], f"{language} is missing {key}")


if __name__ == "__main__":
    unittest.main()
