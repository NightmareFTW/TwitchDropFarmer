"""Which campaign is farmed: auto-claim must not move the target, and the target is sticky."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.farmer import FarmSnapshot  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, FarmDecision, StreamCandidate  # noqa: E402
from twitch_drop_farmer.ui import (  # noqa: E402
    AUTO_CLAIM_RETRY_SEC,
    TRANSLATIONS,
    MainWindow,
    ready_drops,
)

UTC = timezone.utc


def _drop(name: str, current: int, required: int, claimed: bool = False) -> dict:
    return {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "required_minutes": required,
        "current_minutes": current,
        "claimed": claimed,
    }


def _campaign(game: str, *drops: dict, required: int = 360, progress: int = 30) -> DropCampaign:
    return DropCampaign(
        id=f"id-{game.lower().replace(' ', '-')}",
        game_name=game,
        title=f"{game} campaign",
        starts_at=datetime.now(UTC) - timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=5),
        status="ACTIVE",
        required_minutes=required,
        progress_minutes=progress,
        has_watchable_drops=True,
        drops=list(drops) or [_drop("Reward", 10, 60)],
    )


def _decision(campaign: DropCampaign, *, stream: bool = True, reason: str = "stream_selected") -> FarmDecision:
    candidate = (
        StreamCandidate(
            login=f"{campaign.id}-chan",
            display_name="Chan",
            game_name=campaign.game_name,
            viewer_count=100,
            drops_enabled=True,
        )
        if stream
        else None
    )
    return FarmDecision(campaign=campaign, stream=candidate, reason_code=reason)


def _snapshot(*decisions: FarmDecision) -> FarmSnapshot:
    return FarmSnapshot(
        campaigns=[d.campaign for d in decisions],
        decisions=list(decisions),
        available_games=[],
        available_channels=[],
    )


def _window(*decisions: FarmDecision, auto_claim: bool = True) -> MagicMock:
    """A MainWindow stand-in whose farm-target logic is the real one (no Qt needed)."""
    fake = MagicMock()
    fake.config.auto_claim_drops = auto_claim
    fake.config.language = "pt_PT"
    fake.latest_snapshot = _snapshot(*decisions)
    fake._auto_claim_tried = {}
    fake._last_auto_claim_at = None  # only read by the old, removed implementation
    fake._sticky_campaign_id = ""
    fake._forced_farm_game = ""
    fake._forced_farm_campaign_id = ""
    fake._forced_farm_channel = ""
    fake._streamless_campaign_id = ""
    fake._streamless_game = ""
    fake._do_redeem_drops.return_value = 1
    fake._t = lambda key, **kw: TRANSLATIONS["pt_PT"][key].format(**kw)
    fake._campaign_is_known_subscription_locked = (
        lambda campaign: MainWindow._campaign_is_known_subscription_locked(fake, campaign)
    )
    fake._decision_is_farmable_now = lambda d: MainWindow._decision_is_farmable_now(fake, d)
    fake._decision_is_displayable_active = lambda d: MainWindow._decision_is_displayable_active(fake, d)
    fake._pick_farm_decision = lambda: MainWindow._pick_farm_decision(fake)
    fake._current_farm_decision = lambda: MainWindow._current_farm_decision(fake)
    fake._maybe_auto_claim = lambda now=None: MainWindow._maybe_auto_claim(fake, now)
    return fake


class TestReadyDrops(unittest.TestCase):
    def test_only_unclaimed_drops_at_100_percent_are_ready(self):
        campaign = _campaign(
            "MARVEL SNAP",
            _drop("Ready", 60, 60),
            _drop("In progress", 30, 120),
            _drop("Claimed", 60, 60, claimed=True),
            _drop("No requirement", 0, 0),
        )

        self.assertEqual([name for _key, name in ready_drops(campaign)], ["Ready"])


class TestAutoClaim(unittest.TestCase):
    def test_nothing_is_attempted_while_no_drop_is_ready(self):
        fake = _window(_decision(_campaign("MARVEL SNAP", _drop("Reward", 10, 60))))

        MainWindow._maybe_auto_claim(fake)

        fake._do_redeem_drops.assert_not_called()

    def test_nothing_is_attempted_when_auto_claim_is_off(self):
        fake = _window(_decision(_campaign("MARVEL SNAP", _drop("Reward", 60, 60))), auto_claim=False)

        MainWindow._maybe_auto_claim(fake)

        fake._do_redeem_drops.assert_not_called()

    def test_a_ready_drop_is_attempted_once_then_only_after_the_retry_window(self):
        fake = _window(_decision(_campaign("MARVEL SNAP", _drop("Reward", 60, 60))))
        start = datetime(2026, 11, 10, 14, 0, 0)

        MainWindow._maybe_auto_claim(fake, start)
        MainWindow._maybe_auto_claim(fake, start + timedelta(seconds=AUTO_CLAIM_RETRY_SEC - 1))
        self.assertEqual(fake._do_redeem_drops.call_count, 1)

        MainWindow._maybe_auto_claim(fake, start + timedelta(seconds=AUTO_CLAIM_RETRY_SEC))
        self.assertEqual(fake._do_redeem_drops.call_count, 2)

    def test_a_claimed_drop_is_forgotten(self):
        fake = _window(_decision(_campaign("MARVEL SNAP", _drop("Reward", 60, 60))))
        MainWindow._maybe_auto_claim(fake, datetime(2026, 11, 10, 14, 0, 0))
        self.assertEqual(len(fake._auto_claim_tried), 1)

        fake.latest_snapshot = _snapshot(_decision(_campaign("MARVEL SNAP", _drop("Reward", 60, 60, claimed=True))))
        MainWindow._maybe_auto_claim(fake, datetime(2026, 11, 10, 14, 1, 0))

        self.assertEqual(fake._auto_claim_tried, {})

    def test_a_snapshot_with_a_clicked_claim_does_not_move_the_farm_to_another_game(self):
        """Regression: every click used to force the next game, so the farm kept hopping."""
        fake = _window(_decision(_campaign("MARVEL SNAP", _drop("Reward", 60, 60))), _decision(_campaign("Other Game")))
        fake._do_redeem_drops.return_value = 1  # a button was clicked (Twitch may still refuse it)

        MainWindow._apply_snapshot(fake, fake.latest_snapshot, from_browser_enrichment=True)

        fake._do_redeem_drops.assert_called_once()
        fake._auto_advance_after_claim.assert_not_called()
        self.assertEqual(fake._forced_farm_campaign_id, "")
        self.assertEqual(fake._forced_farm_channel, "")
        self.assertEqual(fake._forced_farm_game, "")


class TestStickyTarget(unittest.TestCase):
    def setUp(self):
        self.alpha = _campaign("Alpha")
        self.beta = _campaign("Beta")

    def test_the_campaign_being_farmed_is_kept_when_the_order_changes(self):
        fake = _window(_decision(self.alpha), _decision(self.beta))
        self.assertEqual(fake._current_farm_decision().campaign.game_name, "Alpha")

        # The next snapshot sorts Beta first (e.g. its end date moved or a tie broke).
        fake.latest_snapshot = _snapshot(_decision(self.beta), _decision(self.alpha))

        self.assertEqual(fake._current_farm_decision().campaign.game_name, "Alpha")

    def test_it_moves_on_when_the_campaign_has_no_stream_and_does_not_bounce_back(self):
        fake = _window(_decision(self.alpha), _decision(self.beta))
        fake._current_farm_decision()

        fake.latest_snapshot = _snapshot(_decision(self.alpha, stream=False, reason="no_valid_stream"), _decision(self.beta))
        self.assertEqual(fake._current_farm_decision().campaign.game_name, "Beta")

        # Alpha is back at the top of the list, but Beta is now the one being farmed.
        fake.latest_snapshot = _snapshot(_decision(self.alpha), _decision(self.beta))
        self.assertEqual(fake._current_farm_decision().campaign.game_name, "Beta")

    def test_it_moves_on_when_the_campaign_has_nothing_left_to_watch(self):
        fake = _window(_decision(self.alpha), _decision(self.beta))
        fake._current_farm_decision()

        done = _campaign("Alpha", required=360, progress=360)
        fake.latest_snapshot = _snapshot(_decision(done), _decision(self.beta))

        self.assertEqual(fake._current_farm_decision().campaign.game_name, "Beta")

    def test_a_manual_selection_still_wins_over_the_sticky_campaign(self):
        fake = _window(_decision(self.alpha), _decision(self.beta))
        fake._current_farm_decision()
        fake._forced_farm_campaign_id = self.beta.id

        self.assertEqual(fake._current_farm_decision().campaign.game_name, "Beta")

    def test_no_target_keeps_the_previous_campaign_remembered(self):
        fake = _window(_decision(self.alpha), _decision(self.beta))
        fake._current_farm_decision()

        fake.latest_snapshot = _snapshot(_decision(self.alpha, stream=False), _decision(self.beta, stream=False))
        self.assertIsNone(fake._current_farm_decision())
        self.assertEqual(fake._sticky_campaign_id, self.alpha.id)


class TestTargetSwitchLog(unittest.TestCase):
    def setUp(self):
        self.alpha = _campaign("Alpha")
        self.beta = _campaign("Beta")

    def _switch(self, fake, decision):
        MainWindow._note_target_switch(fake, decision)

    def test_the_first_target_and_an_unchanged_target_are_not_reported(self):
        fake = _window(_decision(self.alpha))

        self._switch(fake, _decision(self.alpha))
        self._switch(fake, _decision(self.alpha))

        fake._log.assert_not_called()

    def test_a_switch_names_both_games_and_why_the_previous_one_was_left(self):
        fake = _window(_decision(self.alpha, stream=False, reason="no_valid_stream"), _decision(self.beta))
        self._switch(fake, _decision(self.alpha))

        self._switch(fake, _decision(self.beta))

        message = fake._log.call_args[0][0]
        self.assertIn("Alpha", message)
        self.assertIn("Beta", message)
        self.assertIn("no_valid_stream", message)

    def test_a_manual_switch_says_so(self):
        fake = _window(_decision(self.alpha), _decision(self.beta))
        self._switch(fake, _decision(self.alpha))
        fake._forced_farm_campaign_id = self.beta.id

        self._switch(fake, _decision(self.beta))

        self.assertIn(TRANSLATIONS["pt_PT"]["target_switch_manual"], fake._log.call_args[0][0])


class TestNewTranslations(unittest.TestCase):
    def test_every_new_key_exists_in_both_languages(self):
        keys = ("target_switch", "target_switch_manual", "target_switch_gone", "target_switch_priority")
        for language in ("pt_PT", "en"):
            for key in keys:
                self.assertIn(key, TRANSLATIONS[language], f"{language} is missing {key}")

    def test_the_redeem_messages_do_not_claim_a_click_was_a_successful_claim(self):
        for language in ("pt_PT", "en"):
            for key in ("redeem_done", "redeem_auto_done"):
                text = TRANSLATIONS[language][key].casefold()
                self.assertTrue("clic" in text, f"{language}.{key} should say buttons were clicked")


if __name__ == "__main__":
    unittest.main()
