"""A cover nobody has must not be searched for again and again (the overnight log: 511 Google searches)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer import twitch_client as tc  # noqa: E402

GAME = "LEGO Batman Legacy of the Dark Knight"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class BoxArtRetryCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        for name, value in (
            ("CONFIG_DIR", base), ("COOKIE_FILE", base / "cookies.json"), ("SESSION_FILE", base / "session.json"),
            ("CAMPAIGN_CACHE_FILE", base / "c.json"), ("REGISTRY_REWARDS_FILE", base / "r.json"),
        ):
            patcher = patch.object(tc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = tc.TwitchClient()
        self.addCleanup(self.client.segment_watcher.stop)
        self.clock = _Clock()
        self.client._box_art_clock = self.clock
        self.requests: list[str] = []
        self.mode = "nobody_has_it"
        # Twitch does not know the game; every other source is a simulated HTTP answer.
        self.client.resolve_game = MagicMock(return_value=None)
        self.client.resolve_game_slug = MagicMock(return_value="lego-batman")
        self.client._post_gql = MagicMock(side_effect=lambda payload: self.record("twitch-gql") or {"data": {"game": None}})
        self.client.session.get = MagicMock(side_effect=self.get)
        self.client.session.head = MagicMock(side_effect=lambda url, **kw: self.record("head") or MagicMock(status_code=200))

    def record(self, what: str) -> None:
        self.requests.append(what)

    def get(self, url: str, **_kwargs):
        if self.mode == "network_down":
            self.record("failed")
            raise requests.ConnectionError("down")
        response = MagicMock(status_code=200)
        response.raise_for_status = lambda: None
        if "twitch.tv/directory" in url:
            self.record("twitch-page")
            response.text = "<html>no image</html>"
        elif "steampowered" in url:
            self.record("steam")
            items = [{"id": 1, "name": GAME}] if self.mode == "steam_has_it" else []
            response.json = lambda: {"items": items}
        elif "google.com" in url:
            self.record("google")
            response.text = "<html>nothing usable</html>"
        else:
            self.record("other")
            response.text = ""
            response.json = lambda: {}
        return response

    def lookups(self) -> int:
        return len(self.requests)


class TestNobodyHasTheCover(BoxArtRetryCase):
    def test_the_second_lookup_makes_no_request_at_all(self):
        self.assertEqual(self.client.resolve_game_box_art_url(GAME), "")
        first = self.lookups()
        self.assertGreater(first, 0)

        self.assertEqual(self.client.resolve_game_box_art_url(GAME), "")

        self.assertEqual(self.lookups(), first)

    def test_the_ui_second_call_to_the_external_resolver_is_covered_too(self):
        """The window asks the full chain and then the external resolver directly: both must stay quiet."""
        self.client.resolve_game_box_art_url(GAME)
        self.client.resolve_external_box_art_url(GAME)
        after_first_round = self.lookups()

        for _ in range(5):  # five more dashboard refreshes
            self.client.resolve_game_box_art_url(GAME)
            self.client.resolve_external_box_art_url(GAME)

        self.assertEqual(self.lookups(), after_first_round)
        self.assertEqual(self.requests.count("google"), 1)

    def test_it_is_tried_again_after_six_hours(self):
        self.client.resolve_game_box_art_url(GAME)
        first = self.lookups()

        self.clock.now += tc.BOX_ART_RETRY_SEC - 1
        self.client.resolve_game_box_art_url(GAME)
        self.assertEqual(self.lookups(), first)

        self.clock.now += 2
        self.client.resolve_game_box_art_url(GAME)
        self.assertGreater(self.lookups(), first)

    def test_a_manual_refresh_is_an_explicit_try_again(self):
        self.client.resolve_game_box_art_url(GAME)
        first = self.lookups()

        self.client.clear_box_art_caches()
        self.client.resolve_game_box_art_url(GAME)

        self.assertGreater(self.lookups(), first)

    def test_one_game_having_no_cover_does_not_block_another(self):
        self.client.resolve_game_box_art_url(GAME)
        before = self.lookups()

        self.client.resolve_game_box_art_url("Some Other Game")

        self.assertGreater(self.lookups(), before)


class TestNetworkTrouble(BoxArtRetryCase):
    def test_a_failure_caused_by_the_network_is_only_remembered_briefly(self):
        """Wi-Fi off at start-up must not leave the cover blank for six hours."""
        self.mode = "network_down"
        self.client.resolve_game_box_art_url(GAME)
        first = self.lookups()

        self.client.resolve_game_box_art_url(GAME)  # right away: still quiet
        self.assertEqual(self.lookups(), first)

        self.clock.now += tc.BOX_ART_RETRY_AFTER_ERROR_SEC + 1
        self.mode = "steam_has_it"
        self.client.session.get = MagicMock(side_effect=self.get)
        found = self.client.resolve_game_box_art_url(GAME)

        self.assertGreater(self.lookups(), first)
        self.assertIn("library_600x900_2x.jpg", found)  # the cover appears as soon as the network is back

    def test_the_short_wait_is_much_shorter_than_the_long_one(self):
        self.assertLess(tc.BOX_ART_RETRY_AFTER_ERROR_SEC * 10, tc.BOX_ART_RETRY_SEC)


class TestFoundCoversAreUnaffected(BoxArtRetryCase):
    def test_a_cover_that_is_found_is_cached_and_never_looked_up_again(self):
        self.mode = "steam_has_it"

        first = self.client.resolve_game_box_art_url(GAME)
        requests_after_first = self.lookups()
        second = self.client.resolve_game_box_art_url(GAME)

        self.assertIn("library_600x900_2x.jpg", first)
        self.assertEqual(second, first)
        self.assertEqual(self.lookups(), requests_after_first)
        self.assertEqual(self.client._box_art_failures, {})  # a success remembers no failure


if __name__ == "__main__":
    unittest.main()
