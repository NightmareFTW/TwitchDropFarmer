"""Alerts: de-duplication, the "drop ready to claim" notice and translation coverage."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.alerts import AlertManager, AlertSeverity, AlertType  # noqa: E402
from twitch_drop_farmer.models import DropCampaign  # noqa: E402
from twitch_drop_farmer.ui import TRANSLATIONS, MainWindow  # noqa: E402

UTC = timezone.utc


def _expiring_campaign(campaign_id: str, name: str, minutes_left: float) -> DropCampaign:
    now = datetime.now(UTC)
    return DropCampaign(
        id=campaign_id, game_name=name, title=f"{name} campaign", starts_at=now - timedelta(days=7),
        ends_at=now + timedelta(minutes=minutes_left), status="ACTIVE", required_minutes=120, progress_minutes=60,
        has_watchable_drops=True, linked=True, timestamp_source="campaign",
        drops=[{"id": "d", "name": "r", "required_minutes": 120, "current_minutes": 60, "claimed": False}],
    )


class TestExpiringAlertInTheEngine(unittest.TestCase):
    """The overnight log: "The Quinfall - termina em 0 minutos" every hour, and a new Albion alert every poll."""

    def poll_times(self, campaigns_per_poll: list[list[DropCampaign]]) -> list[str]:
        from twitch_drop_farmer.config import AppConfig
        from twitch_drop_farmer.farmer import FarmEngine

        manager = AlertManager(dedupe_window_sec=3600)
        delivered: list[str] = []
        manager.register_callback(lambda alert: delivered.append(alert.message))
        client = MagicMock()
        client.consume_diagnostics.return_value = []
        client.fetch_streams.return_value = []
        engine = FarmEngine(client, AppConfig(watchdog_enabled=False, alert_campaign_expiring_soon=True))
        engine.alert_manager = manager
        for campaigns in campaigns_per_poll:
            client.fetch_campaigns.return_value = campaigns
            engine.poll(force_campaigns=True)
        return delivered

    def test_a_countdown_alerts_once_per_campaign_not_once_per_poll(self):
        polls = [[_expiring_campaign("albion", "Albion Online", minutes)] for minutes in (35, 33, 31, 29, 27)]

        delivered = self.poll_times(polls)

        self.assertEqual(len(delivered), 1)
        self.assertIn("Albion Online", delivered[0])

    def test_two_campaigns_ending_soon_are_two_alerts(self):
        polls = [[_expiring_campaign("a", "Game A", 30), _expiring_campaign("b", "Game B", 40)]] * 3

        self.assertEqual(len(self.poll_times(polls)), 2)

    def test_a_campaign_that_has_already_ended_is_not_announced_as_ending_in_0_minutes(self):
        ended = _expiring_campaign("quinfall", "The Quinfall", -5)

        self.assertEqual(ended.seconds_until_end, 0)
        self.assertEqual(self.poll_times([[ended]]), [])


class TestFinishedAlertIsOncePerCampaign(unittest.TestCase):
    """The overnight log: "Where Winds Meet - Drop completado!" at 05h, 06h, 07h, 08h, 09h..."""

    def engine(self, campaigns):
        from twitch_drop_farmer.config import AppConfig
        from twitch_drop_farmer.farmer import FarmEngine

        manager = AlertManager(dedupe_window_sec=0)  # the manager lets everything through: only the engine decides
        self.delivered: list[str] = []
        manager.register_callback(lambda alert: self.delivered.append(alert.message))
        client = MagicMock()
        client.consume_diagnostics.return_value = []
        client.fetch_campaigns.side_effect = lambda **_kw: list(campaigns)
        engine = FarmEngine(client, AppConfig(watchdog_enabled=False, alert_farm_complete=True))
        engine.alert_manager = manager
        return engine

    @staticmethod
    def finished(name: str) -> DropCampaign:
        now = datetime.now(UTC)
        return DropCampaign(
            id=f"id-{name}", game_name=name, title=name, starts_at=now - timedelta(days=3), ends_at=now + timedelta(days=1),
            status="ACTIVE", required_minutes=120, progress_minutes=120, all_drops_claimed=True, has_watchable_drops=True,
            drops=[{"id": "d", "name": "r", "required_minutes": 120, "current_minutes": 120, "claimed": True}],
        )

    def test_a_finished_campaign_is_announced_once_not_on_every_poll(self):
        engine = self.engine([self.finished("Sea of Thieves")])

        for _ in range(12):  # an hour and a half of polls
            engine.poll(force_campaigns=True)

        self.assertEqual(len(self.delivered), 1)

    def test_each_finished_campaign_is_announced_once(self):
        engine = self.engine([self.finished("A"), self.finished("B"), self.finished("C")])

        for _ in range(5):
            engine.poll(force_campaigns=True)

        self.assertEqual(len(self.delivered), 3)

    def test_a_campaign_that_finishes_later_is_still_announced(self):
        late = self.finished("Late")
        late.all_drops_claimed, late.progress_minutes = False, 60
        campaigns = [self.finished("Early"), late]
        engine = self.engine(campaigns)
        engine.poll(force_campaigns=True)
        engine.poll(force_campaigns=True)
        self.assertEqual(len(self.delivered), 1)  # only "Early" so far

        late.all_drops_claimed, late.progress_minutes = True, 120  # it finishes while the app runs
        engine.poll(force_campaigns=True)
        engine.poll(force_campaigns=True)

        self.assertEqual(len(self.delivered), 2)
        self.assertTrue(any("Late" in message for message in self.delivered))

    def test_it_stays_off_when_the_user_turned_the_alert_off(self):
        engine = self.engine([self.finished("A")])
        engine.config.alert_farm_complete = False

        engine.poll(force_campaigns=True)

        self.assertEqual(self.delivered, [])


class TestWording(unittest.TestCase):
    """The user does not want "completado": say "concluído" (or "completo")."""

    def test_the_campaign_finished_alert_says_concluido(self):
        from twitch_drop_farmer.config import AppConfig
        from twitch_drop_farmer.farmer import FarmEngine

        manager = AlertManager(dedupe_window_sec=3600)
        delivered: list[tuple[str, str]] = []
        manager.register_callback(lambda alert: delivered.append((alert.title, alert.message)))
        now = datetime.now(UTC)
        finished = DropCampaign(
            id="done", game_name="Sea of Thieves", title="t", starts_at=now - timedelta(days=3), ends_at=now + timedelta(days=1),
            status="ACTIVE", required_minutes=120, progress_minutes=120, all_drops_claimed=True, has_watchable_drops=True,
            drops=[{"id": "d", "name": "r", "required_minutes": 120, "current_minutes": 120, "claimed": True}],
        )
        client = MagicMock()
        client.consume_diagnostics.return_value = []
        client.fetch_campaigns.return_value = [finished]
        engine = FarmEngine(client, AppConfig(watchdog_enabled=False, alert_farm_complete=True))
        engine.alert_manager = manager

        engine.poll(force_campaigns=True)

        self.assertEqual(len(delivered), 1)
        title, message = delivered[0]
        self.assertEqual(title, "Campanha Concluída")
        self.assertIn("Sea of Thieves", message)
        self.assertIn("concluídos", message)
        self.assertNotIn("completad", (title + message).casefold())

    def test_no_text_of_the_app_says_completado(self):
        """Every .py of the app (what it shows, logs and sends), not just the strings someone remembered."""
        from pathlib import Path

        offenders = [
            f"{path.name}:{number}"
            for path in sorted((Path(__file__).resolve().parents[1] / "src").rglob("*.py"))
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if "completad" in line.casefold()
        ]

        self.assertEqual(offenders, [])

    def test_no_translation_says_completado_in_either_language(self):
        for language, table in TRANSLATIONS.items():
            for key, text in table.items():
                with self.subTest(language=language, key=key):
                    self.assertNotIn("completad", str(text).casefold())


class TestAlertDeduplication(unittest.TestCase):
    def test_an_identical_alert_is_delivered_once_per_window(self):
        manager = AlertManager(dedupe_window_sec=3600)
        delivered = []
        manager.register_callback(delivered.append)

        for _ in range(3):  # the engine used to raise this on every poll
            manager.raise_alert(AlertType.FARM_COMPLETE, AlertSeverity.INFO, "Done", "Game X - done")

        self.assertEqual(len(delivered), 1)
        self.assertEqual(len(manager.alerts), 1)

    def test_a_different_message_is_not_suppressed(self):
        manager = AlertManager(dedupe_window_sec=3600)
        delivered = []
        manager.register_callback(delivered.append)

        manager.raise_alert(AlertType.FARM_COMPLETE, AlertSeverity.INFO, "Done", "Game X - done")
        manager.raise_alert(AlertType.FARM_COMPLETE, AlertSeverity.INFO, "Done", "Game Y - done")

        self.assertEqual(len(delivered), 2)

    def test_a_dedupe_key_judges_an_alert_by_what_it_is_about_not_by_its_wording(self):
        manager = AlertManager(dedupe_window_sec=3600)
        delivered = []
        manager.register_callback(delivered.append)

        for minutes in (35, 34, 33):  # a countdown: the text differs on every poll
            manager.raise_alert(AlertType.CAMPAIGN_EXPIRING_SOON, AlertSeverity.WARNING, "Expiring",
                                f"Game X - ends in {minutes} minutes", dedupe_key="expiring:campaign-1")
        manager.raise_alert(AlertType.CAMPAIGN_EXPIRING_SOON, AlertSeverity.WARNING, "Expiring",
                            "Game Y - ends in 20 minutes", dedupe_key="expiring:campaign-2")

        self.assertEqual(len(delivered), 2)

    def test_without_a_dedupe_key_a_changing_countdown_is_not_suppressed(self):
        """What the overnight log showed: Albion Online alerted on every poll for 35 minutes."""
        manager = AlertManager(dedupe_window_sec=3600)
        delivered = []
        manager.register_callback(delivered.append)

        for minutes in (35, 34, 33):
            manager.raise_alert(AlertType.CAMPAIGN_EXPIRING_SOON, AlertSeverity.WARNING, "Expiring", f"Game X - {minutes}")

        self.assertEqual(len(delivered), 3)

    def test_a_zero_window_delivers_every_alert(self):
        manager = AlertManager(dedupe_window_sec=0)
        delivered = []
        manager.register_callback(delivered.append)

        manager.raise_alert(AlertType.API_ERROR, AlertSeverity.ERROR, "Err", "boom")
        manager.raise_alert(AlertType.API_ERROR, AlertSeverity.ERROR, "Err", "boom")

        self.assertEqual(len(delivered), 2)

    def test_disabled_types_are_not_delivered(self):
        manager = AlertManager()
        delivered = []
        manager.register_callback(delivered.append)
        manager.set_alert_enabled(AlertType.DROP_READY, False)

        manager.raise_alert(AlertType.DROP_READY, AlertSeverity.INFO, "t", "m")

        self.assertEqual(delivered, [])

    def test_drop_ready_exists_and_is_enabled_by_default(self):
        self.assertTrue(AlertManager().is_alert_enabled(AlertType.DROP_READY))


def _campaign(*drops: dict) -> DropCampaign:
    return DropCampaign(
        id="11111111-2222-4333-8444-555555555555",
        game_name="MARVEL SNAP",
        title="Knights of Avalon Drops!",
        starts_at=datetime.now(UTC) - timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=2),
        status="ACTIVE",
        drops=list(drops),
    )


def _drop(name: str, current: int, required: int, claimed: bool = False) -> dict:
    return {
        "id": name.lower(),
        "name": name,
        "required_minutes": required,
        "current_minutes": current,
        "claimed": claimed,
    }


class TestDropReadyAnnouncement(unittest.TestCase):
    def _run(self, campaign: DropCampaign, *, manager=None, announced=None):
        manager = manager or AlertManager(dedupe_window_sec=0)
        fake = MagicMock()
        fake._announced_ready_drops = announced if announced is not None else set()
        fake._t = lambda key, **kw: TRANSLATIONS["pt_PT"][key].format(**kw)
        with patch("twitch_drop_farmer.ui.get_alert_manager", return_value=manager):
            MainWindow._announce_ready_drops(fake, campaign)
        return manager, fake

    def test_a_drop_at_100_percent_raises_one_alert_naming_game_and_drop(self):
        manager, _ = self._run(_campaign(_drop("155 Boosters", 120, 120)))

        self.assertEqual(len(manager.alerts), 1)
        alert = manager.alerts[0]
        self.assertEqual(alert.alert_type, AlertType.DROP_READY)
        self.assertIn("MARVEL SNAP", alert.message)
        self.assertIn("155 Boosters", alert.message)
        self.assertIn("twitch.tv/drops/inventory", alert.message)

    def test_it_is_announced_only_once_per_drop(self):
        manager = AlertManager(dedupe_window_sec=0)
        announced: set[str] = set()
        campaign = _campaign(_drop("155 Boosters", 120, 120))

        self._run(campaign, manager=manager, announced=announced)
        self._run(campaign, manager=manager, announced=announced)

        self.assertEqual(len(manager.alerts), 1)

    def test_drops_not_ready_or_already_claimed_are_ignored(self):
        manager, _ = self._run(
            _campaign(
                _drop("In progress", 36, 120),
                _drop("Already claimed", 120, 120, claimed=True),
                _drop("No requirement", 0, 0),
            )
        )

        self.assertEqual(manager.alerts, [])

    def test_each_ready_drop_gets_its_own_alert(self):
        manager, _ = self._run(_campaign(_drop("One", 60, 60), _drop("Two", 120, 120)))

        self.assertEqual(len(manager.alerts), 2)


class TestDesktopNotification(unittest.TestCase):
    """The Windows toast. The CI runner (Windows) was popping real ones during the tests and ended with a
    "WNDPROC return value cannot be converted to LRESULT" error from the toast's own thread."""

    def alert(self):
        from twitch_drop_farmer.alerts import Alert

        return Alert(alert_type=AlertType.DROP_READY, severity=AlertSeverity.INFO, title="Title", message="Message")

    def test_without_a_desktop_no_toast_is_made(self):
        fake = MagicMock()
        with patch("twitch_drop_farmer.alerts.sys.platform", "win32"), \
             patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}), \
             patch.dict(sys.modules, {"win10toast": fake}):
            shown = AlertManager().show_desktop_notification(self.alert())

        self.assertFalse(shown)
        fake.ToastNotifier.assert_not_called()

    def test_on_windows_with_a_desktop_it_still_shows_the_toast(self):
        fake = MagicMock()
        env = {key: value for key, value in os.environ.items() if key != "QT_QPA_PLATFORM"}
        with patch("twitch_drop_farmer.alerts.sys.platform", "win32"), \
             patch.dict(os.environ, env, clear=True), \
             patch.dict(sys.modules, {"win10toast": fake}):
            shown = AlertManager().show_desktop_notification(self.alert())

        self.assertTrue(shown)
        fake.ToastNotifier.return_value.show_toast.assert_called_once()
        self.assertEqual(fake.ToastNotifier.return_value.show_toast.call_args.kwargs["title"], "Title")

    def test_it_is_not_attempted_outside_windows(self):
        fake = MagicMock()
        with patch("twitch_drop_farmer.alerts.sys.platform", "linux"), patch.dict(sys.modules, {"win10toast": fake}):
            self.assertFalse(AlertManager().show_desktop_notification(self.alert()))

        fake.ToastNotifier.assert_not_called()


class TestAlertTranslations(unittest.TestCase):
    def test_every_alert_type_has_a_label_and_help_in_both_languages(self):
        for language in ("pt_PT", "en"):
            for alert_type in AlertType:
                for prefix in ("alert_type_", "alert_help_"):
                    self.assertIn(
                        f"{prefix}{alert_type.value}",
                        TRANSLATIONS[language],
                        f"missing {prefix}{alert_type.value} in {language}",
                    )

    def test_drop_ready_texts_format_in_both_languages(self):
        for language in ("pt_PT", "en"):
            body = TRANSLATIONS[language]["drop_ready_body"].format(game="G", drop="D")
            self.assertIn("G", body)
            self.assertIn("D", body)
            self.assertIn("twitch.tv/drops/inventory", body)


if __name__ == "__main__":
    unittest.main()
