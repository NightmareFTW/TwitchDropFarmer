"""A campaign the user already finished must stay finished (not come back as "new" from the registry)."""
from __future__ import annotations

import json
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
from twitch_drop_farmer.completions import (  # noqa: E402
    NO_CREDIT_TTL_SEC,
    REASON_COMPLETED,
    REASON_NO_CREDIT,
    CompletionMemory,
)
from twitch_drop_farmer.config import AppConfig  # noqa: E402
from twitch_drop_farmer.farmer import FarmEngine  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, StreamCandidate  # noqa: E402

UTC = timezone.utc
# Marvel Snap's real campaign of Nov 2026: three drops, ending 2026-11-12T18:59:59.999Z.
SNAP_END = datetime(2026, 11, 12, 18, 59, 59, 999000, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 12, 10, 0, tzinfo=UTC).timestamp()

    def __call__(self) -> float:
        return self.now


class TestMemory(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "completed.json"
        self.clock = _Clock()
        self.memory = CompletionMemory(self.path, clock=self.clock)

    def finished(self, reason: str = REASON_COMPLETED, drops: int = 3) -> None:
        self.assertTrue(self.memory.record("MARVEL SNAP", ends_at=SNAP_END, drops=drops, reason=reason))

    def test_the_same_campaign_is_recognised(self):
        self.finished()

        self.assertTrue(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END, drops=3))

    def test_a_new_campaign_of_the_same_game_is_not_hidden(self):
        """Different end date: "as long as there is no new one" it stays done, then it is back in the pool."""
        self.finished()

        self.assertFalse(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END + timedelta(days=6), drops=3))

    def test_a_campaign_added_to_the_game_is_not_hidden(self):
        """The registry now lists more drops than were finished: something new is on offer."""
        self.finished(drops=3)

        self.assertFalse(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END, drops=5))
        self.assertTrue(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END, drops=0))  # not said: judged by date

    def test_another_game_is_never_affected(self):
        self.finished()

        self.assertFalse(self.memory.is_completed("Marvel Rivals", ends_at=SNAP_END, drops=3))

    def test_the_name_is_matched_ignoring_case_accents_and_punctuation(self):
        self.finished()

        self.assertTrue(self.memory.is_completed("Marvel-Snap", ends_at=SNAP_END))

    def test_the_end_date_matches_within_a_few_minutes_not_hours(self):
        self.finished()

        self.assertTrue(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END + timedelta(minutes=4)))
        self.assertFalse(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END + timedelta(hours=1)))

    def test_a_naive_datetime_is_read_as_utc(self):
        self.finished()

        self.assertTrue(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END.replace(tzinfo=None)))

    def test_an_inference_expires_but_a_fact_does_not(self):
        self.memory.record("Inferred Game", ends_at=SNAP_END, drops=2, reason=REASON_NO_CREDIT)
        self.memory.record("Seen Game", ends_at=SNAP_END, drops=2, reason=REASON_COMPLETED)

        self.clock.now += NO_CREDIT_TTL_SEC + 60

        self.assertFalse(self.memory.is_completed("Inferred Game", ends_at=SNAP_END))
        self.assertTrue(self.memory.is_completed("Seen Game", ends_at=SNAP_END))

    def test_seeing_it_finished_for_real_replaces_the_inference(self):
        self.finished(reason=REASON_NO_CREDIT)

        self.assertTrue(self.memory.record("MARVEL SNAP", ends_at=SNAP_END, drops=3, reason=REASON_COMPLETED))
        self.clock.now += NO_CREDIT_TTL_SEC + 60

        self.assertTrue(self.memory.is_completed("MARVEL SNAP", ends_at=SNAP_END))

    def test_recording_the_same_campaign_twice_stores_it_once(self):
        self.finished()

        self.assertFalse(self.memory.record("MARVEL SNAP", ends_at=SNAP_END, drops=3, reason=REASON_COMPLETED))
        self.assertEqual(len(self.memory), 1)

    def test_the_user_can_clear_only_the_inferences(self):
        self.memory.record("Inferred Game", ends_at=SNAP_END, drops=2, reason=REASON_NO_CREDIT)
        self.memory.record("Seen Game", ends_at=SNAP_END, drops=2, reason=REASON_COMPLETED)

        self.assertEqual(self.memory.forget_no_credit(), 1)

        self.assertFalse(self.memory.is_completed("Inferred Game", ends_at=SNAP_END))
        self.assertTrue(self.memory.is_completed("Seen Game", ends_at=SNAP_END))

    def test_it_survives_a_restart(self):
        self.finished()
        self.memory.save()

        again = CompletionMemory(self.path, clock=self.clock)

        self.assertTrue(again.is_completed("MARVEL SNAP", ends_at=SNAP_END, drops=3))
        self.assertEqual([p.name for p in self.path.parent.glob("*.tmp")], [])

    def test_campaigns_long_over_are_forgotten_on_load(self):
        self.memory.record("Old Game", ends_at=SNAP_END - timedelta(days=30), drops=1, reason=REASON_COMPLETED)
        self.finished()
        self.memory.save()

        again = CompletionMemory(self.path, clock=self.clock)

        self.assertEqual(len(again), 1)

    def test_a_damaged_file_is_ignored_not_fatal(self):
        for bad in ("{ not json", "[]", '{"campaigns": 5}', '{"campaigns": [1, "x", {"game": "a"}]}'):
            with self.subTest(bad):
                self.path.write_text(bad, encoding="utf-8")

                self.assertEqual(len(CompletionMemory(self.path, clock=self.clock)), 0)

    def test_an_empty_game_name_stores_nothing(self):
        self.assertFalse(self.memory.record("", ends_at=SNAP_END, drops=1, reason=REASON_COMPLETED))


def _campaign(game: str, *, source: str = "twitch", end: datetime = SNAP_END, drops: int = 3, ts: str = "campaign",
              synthetic: bool = False, declared: int = 0) -> DropCampaign:
    return DropCampaign(
        id=f"id-{source}-{game}", game_name=game, title=game, starts_at=end - timedelta(days=6), ends_at=end, status="ACTIVE",
        required_minutes=360 if source == "twitch" else 0, progress_minutes=360 if source == "twitch" else 0,
        has_watchable_drops=True, source=source, timestamp_source=ts, timestamps_are_synthetic=synthetic,
        declared_drop_count=declared,
        drops=[{"id": str(i), "name": "r", "required_minutes": 120, "current_minutes": 120, "claimed": True} for i in range(drops)]
        if source == "twitch" else [],
    )


class _ClientCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.done_file = base / "completed_campaigns.json"
        for name, value in (
            ("CONFIG_DIR", base), ("COOKIE_FILE", base / "cookies.json"), ("SESSION_FILE", base / "session.json"),
            ("CAMPAIGN_CACHE_FILE", base / "campaign_cache.json"), ("REGISTRY_REWARDS_FILE", base / "rr.json"),
            ("COMPLETED_CAMPAIGNS_FILE", self.done_file),
        ):
            patcher = patch.object(tc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = self.new_client()

    def new_client(self) -> tc.TwitchClient:
        client = tc.TwitchClient()
        self.addCleanup(client.segment_watcher.stop)
        return client


class TestClientRemembers(_ClientCase):
    def test_a_finished_campaign_with_a_real_end_date_is_kept_on_disk(self):
        self.assertTrue(self.client.remember_completed(_campaign("MARVEL SNAP")))

        self.assertTrue(self.done_file.exists())
        self.assertIn("marvelsnap", self.done_file.read_text(encoding="utf-8").casefold().replace(" ", ""))

    def test_a_campaign_without_a_trustworthy_end_date_is_not_kept(self):
        """Nothing could match it again, and a made-up date could hide the wrong campaign."""
        self.assertFalse(self.client.remember_completed(_campaign("A", synthetic=True)))
        self.assertFalse(self.client.remember_completed(_campaign("B", ts="synthetic")))
        self.assertFalse(self.client.remember_completed(_campaign("C", ts="drop")))
        self.assertFalse(self.done_file.exists())

    def test_a_restart_remembers_and_marks_the_registry_campaign(self):
        self.client.remember_completed(_campaign("MARVEL SNAP"))
        restarted = self.new_client()
        registry = _campaign("MARVEL SNAP", source="external_registry", ts="registry", declared=3)

        marked = restarted.apply_completions([registry])

        self.assertEqual(marked, 1)
        self.assertTrue(registry.all_drops_claimed)

    def test_only_registry_campaigns_are_marked_never_real_ones(self):
        self.client.remember_completed(_campaign("MARVEL SNAP"))
        real = _campaign("MARVEL SNAP", source="twitch")
        real.all_drops_claimed = False

        self.assertEqual(self.client.apply_completions([real]), 0)
        self.assertFalse(real.all_drops_claimed)

    def test_a_new_campaign_from_the_registry_is_left_alone(self):
        self.client.remember_completed(_campaign("MARVEL SNAP"))
        new = _campaign("MARVEL SNAP", source="external_registry", ts="registry", declared=3, end=SNAP_END + timedelta(days=7))

        self.assertEqual(self.client.apply_completions([new]), 0)
        self.assertFalse(new.all_drops_claimed)

    def test_a_registry_campaign_with_an_invented_window_is_never_marked(self):
        self.client.remember_completed(_campaign("MARVEL SNAP"))
        invented = _campaign("MARVEL SNAP", source="external_registry", ts="", declared=3)

        self.assertEqual(self.client.apply_completions([invented]), 0)

    def test_the_registry_drop_count_comes_from_the_card(self):
        html = '<html><a href="/game/elden-ring" class="sb-item" data-game="elden ring" data-drops="1" data-end="2026-11-30T06:59:59.999Z" data-start="2026-11-02T07:00:00Z"><div class="sb-name-title">ELDEN RING</div></a></html>'
        with patch.object(tc.requests, "get", return_value=MagicMock(status_code=200, text=html)):
            campaign = self.client._campaigns_from_external_registry()[0]
        self.client.wait_for_registry_rewards(5)

        self.assertEqual(campaign.declared_drop_count, 1)

    def test_the_user_can_ask_to_try_the_inferred_ones_again(self):
        self.client.remember_completed(_campaign("Inferred", source="external_registry", ts="registry", declared=2), REASON_NO_CREDIT)
        self.client.remember_completed(_campaign("Seen"))

        self.assertEqual(self.client.forget_unproductive_campaigns(), 1)
        self.assertEqual(self.client.forget_unproductive_campaigns(), 0)
        again = self.new_client()
        self.assertEqual(again.apply_completions([_campaign("Inferred", source="external_registry", ts="registry", declared=2)]), 0)


class TestInventoryAnswered(_ClientCase):
    """"No campaign of mine is in the Inventory" only means something if the Inventory answered."""

    def answer(self, campaigns: list) -> dict:
        return {"data": {"currentUser": {"inventory": {"dropCampaignsInProgress": campaigns}}}}

    def test_it_is_not_known_before_the_first_answer(self):
        self.assertFalse(self.client.inventory_recently_ok())

    def test_it_is_known_after_an_answer_even_an_empty_one(self):
        self.client.login_state.oauth_token = "t" * 30
        self.client._post_gql = MagicMock(return_value=self.answer([]))

        self.client.fetch_inventory_progress()

        self.assertTrue(self.client.inventory_recently_ok())

    def test_a_failed_request_does_not_count_as_an_answer(self):
        self.client.login_state.oauth_token = "t" * 30
        self.client._post_gql = MagicMock(side_effect=requests.ConnectionError("down"))

        self.client.fetch_inventory_progress()

        self.assertFalse(self.client.inventory_recently_ok())

    def test_a_null_user_does_not_count_as_an_answer(self):
        self.client.login_state.oauth_token = "t" * 30
        self.client._post_gql = MagicMock(return_value={"data": {"currentUser": None}})

        self.client.fetch_inventory_progress()

        self.assertFalse(self.client.inventory_recently_ok())

    def test_an_old_answer_is_not_recent(self):
        self.client._inventory_ok_at = tc.time.monotonic() - 600

        self.assertFalse(self.client.inventory_recently_ok(180))
        self.assertTrue(self.client.inventory_recently_ok(900))


class TestEngine(_ClientCase):
    """End to end: finished for real, vanished from the Inventory, back from the registry as "new"."""

    def engine(self, campaigns: list[DropCampaign]) -> FarmEngine:
        self.client.fetch_campaigns = MagicMock(side_effect=lambda **_kw: list(campaigns))
        self.client.fetch_streams = MagicMock(side_effect=lambda c: [
            StreamCandidate(login=f"{c.id}-chan", display_name="x", game_name=c.game_name, viewer_count=5,
                            drops_enabled=True, channel_id="1")
        ])
        self.client.consume_diagnostics = MagicMock(return_value=[])
        return FarmEngine(self.client, AppConfig(watchdog_enabled=False))

    def reasons(self, engine: FarmEngine) -> dict[str, str]:
        return {d.campaign.id: d.reason_code for d in engine.poll().decisions}

    def live_end(self) -> datetime:
        return datetime.now(UTC) + timedelta(days=3)

    def test_a_campaign_seen_finished_stays_finished_after_twitch_stops_listing_it(self):
        end = self.live_end()
        real = _campaign("MARVEL SNAP", end=end)  # in the Inventory, every minute earned
        self.engine([real]).poll()
        self.assertTrue(self.done_file.exists(), "the finished campaign was not kept")

        # Next session: claimed, so Twitch lists nothing; the registry offers it again, with no data.
        again = self.new_client()
        self.client = again
        registry = _campaign("MARVEL SNAP", source="external_registry", ts="registry", declared=3, end=end)
        registry.starts_at = datetime.now(UTC) - timedelta(days=1)
        engine = self.engine([registry])
        decisions = engine.poll().decisions

        self.assertEqual(decisions[0].reason_code, "campaign_completed")
        self.assertIsNone(decisions[0].stream)
        self.assertTrue(registry.all_drops_claimed)

    def test_a_finished_campaign_is_not_in_the_pool_when_another_farm_ends(self):
        end = self.live_end()
        self.client._completions.record("MARVEL SNAP", ends_at=end, drops=3, reason=REASON_COMPLETED)
        snap = _campaign("MARVEL SNAP", source="external_registry", ts="registry", declared=3, end=end)
        other = _campaign("Other Game", source="external_registry", ts="registry", declared=1, end=end + timedelta(days=1))
        engine = self.engine([snap, other])

        reasons = self.reasons(engine)

        self.assertEqual(reasons[snap.id], "campaign_completed")
        self.assertEqual(reasons[other.id], "stream_selected")  # the rest of the pool is untouched

    def test_a_new_campaign_of_the_same_game_is_farmable_again(self):
        end = self.live_end()
        self.client._completions.record("MARVEL SNAP", ends_at=end, drops=3, reason=REASON_COMPLETED)
        new = _campaign("MARVEL SNAP", source="external_registry", ts="registry", declared=3, end=end + timedelta(days=7))
        new.starts_at = datetime.now(UTC) - timedelta(hours=2)  # it has started: a new campaign running now
        engine = self.engine([new])

        self.assertEqual(self.reasons(engine)[new.id], "stream_selected")

    def test_a_registry_campaign_is_never_recorded_as_finished_by_the_engine(self):
        """It can only be marked from what was remembered: the engine must not feed itself."""
        end = self.live_end()
        self.client._completions.record("X", ends_at=end, drops=1, reason=REASON_COMPLETED)
        registry = _campaign("X", source="external_registry", ts="registry", declared=1, end=end)
        engine = self.engine([registry])
        before = len(self.client._completions)

        engine.poll()
        engine.poll()

        self.assertEqual(len(self.client._completions), before)

    def test_a_campaign_flagged_as_claimed_is_recorded_too(self):
        """The other way a campaign is seen finished: Twitch says every drop is claimed (minutes left over)."""
        end = self.live_end()
        claimed = _campaign("MARVEL SNAP", end=end)
        claimed.progress_minutes = 100  # not every minute watched, but every drop already claimed
        claimed.all_drops_claimed = True
        self.engine([claimed]).poll()

        self.assertTrue(self.client._completions.is_completed("MARVEL SNAP", ends_at=end, drops=3))

    def test_the_engine_never_turns_an_inference_into_a_fact(self):
        """An inferred "no credit" must stay clearable and expire; the engine must not promote it by seeing it again."""
        end = self.live_end()
        self.client._completions.record("MARVEL SNAP", ends_at=end, drops=3, reason=REASON_NO_CREDIT)
        registry = _campaign("MARVEL SNAP", source="external_registry", ts="registry", declared=3, end=end)
        engine = self.engine([registry])

        engine.poll()
        engine.poll()

        self.assertEqual(self.client._completions.forget_no_credit(), 1, "the inference was promoted to a fact")

    def test_the_finished_campaign_is_recorded_once_not_on_every_poll(self):
        end = self.live_end()
        engine = self.engine([_campaign("MARVEL SNAP", end=end)])

        for _ in range(3):
            engine.poll()

        self.assertEqual(len(self.client._completions), 1)
        self.assertEqual(json.loads(self.done_file.read_text(encoding="utf-8"))["campaigns"][0]["reason"], REASON_COMPLETED)


if __name__ == "__main__":
    unittest.main()
