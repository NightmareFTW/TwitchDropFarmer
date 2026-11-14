"""The dashboard query Twitch always rejects is not repeated every cycle (2 failing requests per 10 minutes)."""
from __future__ import annotations

import copy
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
from twitch_drop_farmer.models import DropCampaign  # noqa: E402

UTC = timezone.utc
BLOCKED = {"data": {"currentUser": {"dropCampaigns": []}}, "errors": [{"message": "failed integrity check"}]}
ANSWERED = {"data": {"currentUser": None}}  # a real answer that is not a rejection


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        for name, value in (
            ("CONFIG_DIR", base), ("COOKIE_FILE", base / "c.json"), ("SESSION_FILE", base / "s.json"),
            ("CAMPAIGN_CACHE_FILE", base / "cc.json"), ("REGISTRY_REWARDS_FILE", base / "rr.json"),
            ("COMPLETED_CAMPAIGNS_FILE", base / "d.json"),
        ):
            patcher = patch.object(tc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = tc.TwitchClient()
        self.addCleanup(self.client.segment_watcher.stop)
        c = self.client
        c.login_state.oauth_token = "t" * 30
        c.validate_oauth_token = MagicMock()
        self.dashboard_calls = 0
        self.answer: dict | Exception = BLOCKED

        def route(payload, **_kw):
            operation = payload.get("operationName")
            if operation == "Inventory":
                return {"data": {"currentUser": {"inventory": {"dropCampaignsInProgress": []}}}}
            if operation == "ViewerDropsDashboard":
                self.dashboard_calls += 1
                if isinstance(self.answer, Exception):
                    raise self.answer
                return copy.deepcopy(self.answer)
            raise AssertionError(f"unexpected operation {operation}")

        c._post_gql = MagicMock(side_effect=route)
        now = datetime.now(UTC)
        c._campaigns_from_external_registry = MagicMock(side_effect=lambda: [
            DropCampaign(id="external-x", game_name="Some Game", title="Some Game", starts_at=now - timedelta(hours=1),
                         ends_at=now + timedelta(days=3), status="ACTIVE", source="external_registry")
        ])
        c._campaigns_from_drops_page = MagicMock(return_value={})
        c._campaigns_from_browser_page = MagicMock(return_value=[])
        c._retry_dashboard_with_harvested_integrity = MagicMock(return_value=None)

    def cycle(self, **kwargs) -> list[str]:
        return [item.game_name for item in self.client.fetch_campaigns(allow_browser_fallback=False, **kwargs)]


class TestBackoff(_Case):
    def test_the_first_cycle_asks_and_the_next_ones_do_not(self):
        self.cycle()
        self.assertEqual(self.dashboard_calls, 1)

        for _ in range(5):  # five more 10-minute cycles
            self.cycle()

        self.assertEqual(self.dashboard_calls, 1)

    def test_the_campaigns_found_are_the_same_whether_it_asked_or_not(self):
        asked = self.cycle()
        replayed = self.cycle()

        self.assertEqual(asked, replayed)
        self.assertEqual(asked, ["Some Game"])

    def test_the_log_says_why_it_did_not_ask(self):
        self.cycle()
        self.client.consume_diagnostics()

        self.cycle()

        notes = " ".join(self.client.consume_diagnostics())
        self.assertIn("não se repete", notes)

    def test_it_asks_again_when_the_wait_is_over(self):
        self.cycle()
        self.client._dashboard_blocked_until = tc.time.monotonic() - 1  # an hour later

        self.cycle()

        self.assertEqual(self.dashboard_calls, 2)

    def test_the_wait_is_an_hour(self):
        self.assertEqual(tc.DASHBOARD_BLOCK_BACKOFF_SEC, 3600.0)
        self.cycle()

        remaining = self.client._dashboard_blocked_until - tc.time.monotonic()
        self.assertGreater(remaining, 3500)
        self.assertLessEqual(remaining, 3600)

    def test_a_refresh_asked_by_the_user_always_asks(self):
        self.cycle()

        with patch.object(self.client, "_campaigns_from_browser_page", return_value=[]):
            self.client.fetch_campaigns(allow_browser_fallback=True, full_scan=True)

        self.assertEqual(self.dashboard_calls, 2)

    def test_it_asks_again_as_soon_as_the_browser_has_a_token_that_may_change_the_answer(self):
        self.cycle()
        self.client._harvested_integrity_token = "tok"
        self.client._harvested_integrity_token_captured_mono = tc.time.monotonic()

        self.cycle()

        self.assertEqual(self.dashboard_calls, 2)

    def test_a_new_login_forgets_the_rejection(self):
        self.cycle()
        self.client.validate_oauth_token = MagicMock()

        self.client.set_oauth_token("n" * 30)
        self.cycle()

        self.assertEqual(self.dashboard_calls, 2)

    def test_importing_a_session_with_another_token_forgets_it_too(self):
        self.cycle()

        self.client.import_session_json('[{"name": "auth-token", "value": "%s", "domain": ".twitch.tv"}]' % ("z" * 30))
        self.cycle()

        self.assertEqual(self.dashboard_calls, 2)

    def test_an_answer_that_is_not_a_rejection_is_asked_again_every_cycle(self):
        self.answer = ANSWERED

        self.cycle()
        self.cycle()
        self.cycle()

        self.assertEqual(self.dashboard_calls, 3)
        self.assertEqual(self.client._dashboard_blocked_until, 0.0)

    def test_a_network_failure_is_not_taken_for_a_rejection(self):
        self.answer = requests.ConnectionError("down")

        self.cycle()
        self.cycle()

        self.assertEqual(self.dashboard_calls, 2)
        self.assertEqual(self.client._dashboard_blocked_until, 0.0)

    def test_when_twitch_stops_rejecting_the_wait_is_cleared(self):
        self.cycle()
        self.client._dashboard_blocked_until = tc.time.monotonic() - 1
        self.answer = ANSWERED

        self.cycle()

        self.assertEqual(self.client._dashboard_blocked_until, 0.0)
        self.assertEqual(self.client._dashboard_blocked_response, {})

    def test_one_hour_is_far_fewer_requests_than_every_ten_minutes(self):
        """A night: 60 cycles used to be 60 asks (120 failing requests with the retry)."""
        for _ in range(60):
            self.cycle()
            self.client._dashboard_blocked_until -= 600  # ten minutes pass

        self.assertLessEqual(self.dashboard_calls, 11)
        self.assertGreaterEqual(self.dashboard_calls, 9)


class TestCampaignCacheWrites(_Case):
    """fetch_campaigns() runs on the background thread and on the main thread: two saves can overlap."""

    def test_overlapping_saves_do_not_lose_each_other(self):
        """Unlocked, two saves share one temp file: the first rename takes it from under the second, whose save is
        lost in silence (the cache writer swallows every error) and the file is invalid while they overlap.
        Made deterministic with a slow disk (the writer pauses in the middle) and by counting the lost saves."""
        import json
        import threading
        import time
        from pathlib import Path

        now = datetime.now(UTC)
        real_write_text, real_replace = Path.write_text, os.replace
        lost: list[str] = []

        def slow_write_text(path, data, *args, **kwargs):
            if path.suffix == ".tmp" and path.stem == tc.CAMPAIGN_CACHE_FILE.stem:
                half = len(data) // 2
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(data[:half])
                    handle.flush()
                    time.sleep(0.01)  # another writer gets in here unless it is kept out
                    handle.write(data[half:])
                return len(data)
            return real_write_text(path, data, *args, **kwargs)

        def counting_replace(source, destination):
            try:
                real_replace(source, destination)
            except FileNotFoundError:
                lost.append(str(source))
                raise

        def campaigns(count: int) -> list[DropCampaign]:
            return [DropCampaign(id=f"c{index}", game_name=f"Game {index}", title="t", starts_at=now, ends_at=now + timedelta(days=1))
                    for index in range(count)]

        def work(size: int) -> None:
            for _ in range(6):
                self.client._save_campaign_cache(campaigns(size))

        with patch.object(Path, "write_text", slow_write_text), patch.object(os, "replace", counting_replace):
            threads = [threading.Thread(target=work, args=(size,)) for size in (5, 50, 200, 20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(lost, [], "saves were lost to overlapping writers")
        self.assertIn(len(json.loads(tc.CAMPAIGN_CACHE_FILE.read_text(encoding="utf-8"))), {5, 50, 200, 20})
        self.assertEqual([p.name for p in tc.CAMPAIGN_CACHE_FILE.parent.glob("*.tmp")], [])


if __name__ == "__main__":
    unittest.main()
