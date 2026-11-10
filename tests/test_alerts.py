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
