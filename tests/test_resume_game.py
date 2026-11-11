"""The farm carries on with the game it was last on (not with whatever the sort order puts first)."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.config import AppConfig  # noqa: E402
from twitch_drop_farmer.farmer import FarmEngine  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, StreamCandidate  # noqa: E402

UTC = timezone.utc


def _campaign(name: str, ends_in_days: float) -> DropCampaign:
    return DropCampaign(
        id=f"id-{name}", game_name=name, title=f"{name} campaign", starts_at=datetime.now(UTC) - timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=ends_in_days), status="ACTIVE", required_minutes=360,
        progress_minutes=10, has_watchable_drops=True,
        drops=[{"id": f"{name}-d", "name": "r", "required_minutes": 360, "current_minutes": 10, "claimed": False}],
    )


def _engine(campaigns: list[DropCampaign]) -> tuple[FarmEngine, MagicMock]:
    client = MagicMock()
    client.consume_diagnostics.side_effect = lambda: []
    client.fetch_campaigns.side_effect = lambda **_kw: list(campaigns)
    client.fetch_streams.side_effect = lambda c: [
        StreamCandidate(login=f"{c.id}-chan", display_name="x", game_name=c.game_name, viewer_count=5,
                        drops_enabled=True, channel_id="1")
    ]
    return FarmEngine(client, AppConfig(watchdog_enabled=False)), client


def _many(count: int = 40) -> list[DropCampaign]:
    """Campaigns ending later and later, so the last one is far from the front of the queue."""
    return [_campaign(f"Game {i:02d}", ends_in_days=1 + i * 0.1) for i in range(count)]


class TestEngineLooksTheLastGameUp(unittest.TestCase):
    def decisions(self, engine: FarmEngine) -> dict[str, str]:
        return {d.campaign.game_name: d.reason_code for d in engine.poll().decisions}

    def test_without_a_preferred_game_one_far_down_the_queue_is_not_checked_yet(self):
        """The setup that makes the next test mean something."""
        engine, _ = _engine(_many())

        self.assertEqual(self.decisions(engine)["Game 35"], "stream_unchecked")

    def test_the_preferred_game_has_its_channel_looked_up_in_the_very_first_poll(self):
        """Otherwise it has no stream yet, is not farmable, and the farm starts on another game."""
        engine, _ = _engine(_many())
        engine.set_preferred_game("Game 35")

        self.assertEqual(self.decisions(engine)["Game 35"], "stream_selected")

    def test_the_match_ignores_case_accents_and_punctuation(self):
        engine, _ = _engine(_many())
        engine.set_preferred_game("GAME-35!")

        self.assertEqual(self.decisions(engine)["Game 35"], "stream_selected")

    @staticmethod
    def four_campaigns_of_one_game() -> list[DropCampaign]:
        campaigns = _many() + [_campaign("Game 35", 6.0), _campaign("Game 35", 7.0), _campaign("Game 35", 8.0)]
        for index, campaign in enumerate(campaigns):
            campaign.id = f"id-{index}"  # four campaigns share "Game 35"
        return campaigns

    @staticmethod
    def looked_up(client: MagicMock, game: str) -> set[str]:
        return {call.args[0].id for call in client.fetch_streams.call_args_list if call.args[0].game_name == game}

    def test_only_two_of_its_campaigns_are_looked_up_not_all_of_them(self):
        engine, client = _engine(self.four_campaigns_of_one_game())
        engine.set_preferred_game("Game 35")

        engine.poll()

        looked_up = self.looked_up(client, "Game 35")
        self.assertGreaterEqual(len(looked_up), 1)
        self.assertLessEqual(len(looked_up), 2)

    def test_it_does_not_cost_more_requests_than_before(self):
        """The preferred game's lookups take the place of the front of the queue's: the total is not higher."""
        campaigns = self.four_campaigns_of_one_game()
        engine, client = _engine(campaigns)
        baseline_engine, baseline_client = _engine(campaigns)
        baseline_engine.poll()
        engine.set_preferred_game("Game 35")

        engine.poll()

        self.assertLessEqual(client.fetch_streams.call_count, baseline_client.fetch_streams.call_count)

    def test_nothing_extra_is_looked_up_when_the_farm_is_already_on_that_game(self):
        """One of its campaigns is already in focus: the others must not be pulled in as well."""
        campaigns = self.four_campaigns_of_one_game()
        engine, client = _engine(campaigns)
        engine.set_focus("id-40")  # the campaign being farmed
        engine.set_preferred_game("Game 35")

        engine.poll()

        self.assertEqual(self.looked_up(client, "Game 35"), {"id-40"})

    def test_a_game_that_is_not_in_the_list_changes_nothing(self):
        engine, client = _engine(_many())
        baseline_engine, baseline_client = _engine(_many())
        engine.set_preferred_game("A Game That Ended")

        engine.poll()
        baseline_engine.poll()

        self.assertEqual(client.fetch_streams.call_count, baseline_client.fetch_streams.call_count)

    def test_clearing_it_goes_back_to_the_normal_order(self):
        engine, _ = _engine(_many())
        engine.set_preferred_game("Game 35")
        engine.set_preferred_game("")

        self.assertEqual(engine.preferred_game, "")
        self.assertEqual(self.decisions(engine)["Game 35"], "stream_unchecked")


if __name__ == "__main__":
    unittest.main()
