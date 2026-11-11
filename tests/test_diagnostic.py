"""The system diagnostic: its checks must be able to pass, and must tell failures apart."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.diagnostic import DiagnosticEngine, DiagnosticStatus  # noqa: E402
from twitch_drop_farmer.twitch_client import TwitchClient  # noqa: E402

PLAYLIST = "#EXTM3U\n#EXTINF:2.0,live\nseg1.ts\n#EXTINF:2.0,live\nseg2.ts\n"
BASE = "https://video-edge.example/v1/playlist.m3u8"


def _engine() -> tuple[DiagnosticEngine, TwitchClient]:
    client = TwitchClient()
    return DiagnosticEngine(client), client


def _run(coro):
    return asyncio.run(coro)


def _http_error(code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = code
    return requests.HTTPError(f"{code}", response=response)


def _directory(login: str | None) -> dict:
    edges = [{"node": {"broadcaster": {"login": login}}}] if login else []
    return {"data": {"game": {"streams": {"edges": edges}}}}


class TestApiConnectivity(unittest.TestCase):
    def _check(self, *, response=None, error: Exception | None = None):
        engine, client = _engine()
        with patch.object(client, "_post_gql", side_effect=error, return_value=response) as post:
            _run(engine._test_twitch_api_connectivity())
        return engine.report.results[0], post

    def test_it_passes_when_twitch_answers_a_real_query(self):
        result, _ = self._check(response={"data": {"game": {"slug": "just-chatting", "id": "509658"}}})

        self.assertEqual(result.status, DiagnosticStatus.SUCCESS)
        self.assertIn("reachable", result.message)

    def test_the_query_it_sends_is_a_real_one_not_a_made_up_hash(self):
        """Regression: it sent operation 'GetUser' with a hash of 32 zeros (a SHA-256 has 64
        characters), Twitch answered HTTP 400 and the app reported 'API unreachable' on a
        connection that was working, so the check could never pass."""
        _, post = self._check(response={"data": {"game": {"slug": "just-chatting"}}})

        payload = post.call_args.args[0]
        sha = payload["extensions"]["persistedQuery"]["sha256Hash"]
        self.assertRegex(sha, r"^[0-9a-f]{64}$")
        self.assertNotEqual(sha, "0" * 64)
        self.assertEqual(payload["operationName"], "DirectoryGameRedirect")
        self.assertEqual(payload["variables"]["name"], "Just Chatting")

    def test_a_graphql_error_is_a_warning_that_explains_what_it_may_mean(self):
        result, _ = self._check(response={"errors": [{"message": "PersistedQueryNotFound"}], "data": None})

        self.assertEqual(result.status, DiagnosticStatus.WARNING)
        self.assertIn("PersistedQueryNotFound", result.message)
        self.assertIn("needs an update", result.message)

    def test_an_answer_with_no_data_is_a_warning_not_a_failure(self):
        result, _ = self._check(response={"data": {"game": None}})

        self.assertEqual(result.status, DiagnosticStatus.WARNING)

    def test_a_refusal_is_reported_as_reachable_but_refused_with_the_code(self):
        result, _ = self._check(error=_http_error(403))

        self.assertEqual(result.status, DiagnosticStatus.FAILED)
        self.assertIn("reachable but refused", result.message)
        self.assertIn("403", result.message)

    def test_no_connection_is_reported_as_unreachable(self):
        for error in (requests.ConnectionError("no route"), requests.Timeout("slow")):
            with self.subTest(type(error).__name__):
                result, _ = self._check(error=error)

                self.assertEqual(result.status, DiagnosticStatus.FAILED)
                self.assertIn("unreachable", result.message)


class TestWatchPipeline(unittest.TestCase):
    def _check(self, *, directory=None, playlist=None, touch_error: Exception | None = None):
        engine, client = _engine()
        touched = MagicMock(side_effect=touch_error)
        with patch.object(client, "_post_gql", return_value=directory if directory is not None else _directory("somechannel")), \
                patch.object(client, "hls_playlist_snapshot", side_effect=playlist if isinstance(playlist, Exception) else None,
                             return_value=(PLAYLIST, BASE) if playlist is None else playlist), \
                patch.object(client, "hls_touch_segment", touched):
            _run(engine._test_heartbeat_system())
        return engine.report.results[0], touched

    def test_it_passes_when_the_token_playlist_and_a_segment_all_answer(self):
        result, touched = self._check()

        self.assertEqual(result.status, DiagnosticStatus.SUCCESS)
        self.assertIn("2 segments", result.message)
        touched.assert_called_once_with("somechannel", "https://video-edge.example/v1/seg2.ts")  # the newest one

    def test_it_really_checks_something_unlike_the_old_always_ready_message(self):
        result, _ = self._check(playlist=requests.ConnectionError("video edge unreachable"))

        self.assertEqual(result.status, DiagnosticStatus.FAILED)
        self.assertIn("video edge unreachable", result.message)

    def test_a_failing_segment_request_is_a_failure(self):
        result, _ = self._check(touch_error=requests.ConnectionError("segment refused"))

        self.assertEqual(result.status, DiagnosticStatus.FAILED)
        self.assertIn("segment refused", result.message)

    def test_no_live_channel_to_test_with_is_a_warning(self):
        result, touched = self._check(directory=_directory(None))

        self.assertEqual(result.status, DiagnosticStatus.WARNING)
        touched.assert_not_called()

    def test_a_playlist_without_segments_is_a_warning(self):
        result, touched = self._check(playlist=("#EXTM3U\n", BASE))

        self.assertEqual(result.status, DiagnosticStatus.WARNING)
        touched.assert_not_called()

    def test_it_sends_no_watch_event_so_no_channel_is_credited(self):
        engine, client = _engine()
        with patch.object(client, "_post_gql", return_value=_directory("somechannel")), \
                patch.object(client, "hls_playlist_snapshot", return_value=(PLAYLIST, BASE)), \
                patch.object(client, "hls_touch_segment"), \
                patch.object(client, "streamless_watch_heartbeat") as heartbeat:
            _run(engine._test_heartbeat_system())

        heartbeat.assert_not_called()


class TestWholeReport(unittest.TestCase):
    def test_when_every_check_can_pass_the_overall_status_is_success(self):
        engine, client = _engine()
        client.login_state.oauth_token = "x" * 30
        with patch.object(client, "validate_oauth_token", return_value=MagicMock(login_name="someone")), \
                patch.object(client, "_post_gql", side_effect=lambda payload: (
                    _directory("somechannel") if payload["operationName"] == "DirectoryPage_Game"
                    else {"data": {"game": {"slug": "just-chatting"}}})), \
                patch.object(client, "fetch_campaigns", return_value=[MagicMock()]), \
                patch.object(client, "hls_playlist_snapshot", return_value=(PLAYLIST, BASE)), \
                patch.object(client, "hls_touch_segment"):
            report = _run(engine.run_all_diagnostics())

        self.assertEqual([r.status for r in report.results], [DiagnosticStatus.SUCCESS] * 4)
        self.assertEqual(report.overall_status, DiagnosticStatus.SUCCESS)

    def test_one_real_failure_makes_the_overall_status_failed(self):
        engine, client = _engine()
        client.login_state.oauth_token = ""
        with patch.object(client, "_post_gql", side_effect=requests.ConnectionError("offline")), \
                patch.object(client, "fetch_campaigns", return_value=[]):
            report = _run(engine.run_all_diagnostics())

        self.assertEqual(report.overall_status, DiagnosticStatus.FAILED)
        self.assertTrue(re.search(r"critical issue", report.summary))


if __name__ == "__main__":
    unittest.main()
