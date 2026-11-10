"""Unit tests for the background HLS segment watcher (no network, no Qt)."""
from __future__ import annotations

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.stream_watcher import (  # noqa: E402
    SegmentWatcher,
    _RecentSet,
    playlist_segment_urls,
)

BASE = "https://video-edge.example.net/v1/playlist.m3u8"


def _playlist(*names: str) -> str:
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2"]
    for name in names:
        lines.append("#EXTINF:2.000,live")
        lines.append(name)
    return "\n".join(lines) + "\n"


class TestPlaylistParsing(unittest.TestCase):
    def test_resolves_relative_urls_and_skips_tags_and_blank_lines(self):
        text = "#EXTM3U\n\n#EXTINF:2.0,live\nseg1.ts\n  seg2.ts  \nhttps://other.example/seg3.ts\n"
        self.assertEqual(
            playlist_segment_urls(text, BASE),
            [
                "https://video-edge.example.net/v1/seg1.ts",
                "https://video-edge.example.net/v1/seg2.ts",
                "https://other.example/seg3.ts",
            ],
        )

    def test_recent_set_forgets_the_oldest_items(self):
        recent = _RecentSet(limit=3)
        for item in "abcd":
            recent.add(item)
        self.assertNotIn("a", recent)
        self.assertTrue(all(item in recent for item in "bcd"))


class TestIteration(unittest.TestCase):
    def _watcher(self, playlists, *, touch=None):
        feed = list(playlists)
        touched: list[str] = []

        def fetch(_login):
            item = feed.pop(0) if len(feed) > 1 else feed[0]
            if isinstance(item, Exception):
                raise item
            return item, BASE

        def default_touch(_login, url):
            touched.append(url)

        watcher = SegmentWatcher(fetch, touch or default_touch)
        return watcher, touched

    def test_first_pass_requests_only_the_live_edge_then_only_new_segments(self):
        watcher, touched = self._watcher(
            [_playlist("s1.ts", "s2.ts", "s3.ts"), _playlist("s2.ts", "s3.ts", "s4.ts", "s5.ts"), _playlist("s2.ts", "s3.ts", "s4.ts", "s5.ts")]
        )
        seen = _RecentSet()

        self.assertEqual(watcher._iteration("chan", seen, first_pass=True), 1)
        self.assertEqual([url.rsplit("/", 1)[1] for url in touched], ["s3.ts"])

        self.assertEqual(watcher._iteration("chan", seen, first_pass=False), 2)
        self.assertEqual([url.rsplit("/", 1)[1] for url in touched], ["s3.ts", "s4.ts", "s5.ts"])

        # Nothing new on the next poll: nothing is requested again.
        self.assertEqual(watcher._iteration("chan", seen, first_pass=False), 0)
        self.assertEqual(len(touched), 3)
        self.assertEqual(watcher.segments_touched, 3)

    def test_a_playlist_failure_propagates_so_the_caller_can_back_off(self):
        watcher, _touched = self._watcher([ConnectionError("playlist gone")])
        with self.assertRaises(ConnectionError):
            watcher._iteration("chan", _RecentSet(), first_pass=True)

    def test_partial_segment_failures_are_counted_but_not_fatal(self):
        calls: list[str] = []

        def flaky(_login, url):
            calls.append(url)
            if url.endswith("s4.ts"):
                raise OSError("expired")

        watcher, _ = self._watcher([_playlist("s3.ts"), _playlist("s3.ts", "s4.ts", "s5.ts")], touch=flaky)
        seen = _RecentSet()
        watcher._iteration("chan", seen, first_pass=True)

        self.assertEqual(watcher._iteration("chan", seen, first_pass=False), 1)  # s5 ok, s4 failed
        self.assertEqual(watcher.errors, 1)

    def test_when_every_segment_request_fails_it_raises(self):
        def always_fails(_login, _url):
            raise OSError("403")

        watcher, _ = self._watcher([_playlist("s1.ts")], touch=always_fails)
        with self.assertRaises(OSError):
            watcher._iteration("chan", _RecentSet(), first_pass=True)


class _FakeClock:
    """Manually advanced clock so timing behaviour can be tested without sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestTimingDiagnostics(unittest.TestCase):
    def _watcher(self, clock, notes, **kwargs):
        def fetch(_login):
            clock.advance(self.fetch_cost)
            return _playlist("s1.ts"), BASE

        def touch(_login, _url):
            clock.advance(self.touch_cost)

        return SegmentWatcher(fetch, touch, note=notes.append, clock=clock, **kwargs)

    fetch_cost = 0.0
    touch_cost = 0.0

    def test_iteration_records_the_playlist_and_segment_time_separately(self):
        clock, notes = _FakeClock(), []
        self.fetch_cost, self.touch_cost = 1.5, 4.0
        watcher = self._watcher(clock, notes)

        watcher._iteration("chan", _RecentSet(), first_pass=True)

        self.assertAlmostEqual(watcher.last_fetch_sec, 1.5)
        self.assertAlmostEqual(watcher.last_touch_sec, 4.0)

    def test_a_fast_cycle_is_not_reported(self):
        clock, notes = _FakeClock(), []
        watcher = self._watcher(clock, notes, slow_cycle_sec=8.0)

        watcher._record_cycle("chan", 0.4)

        self.assertEqual(notes, [])

    def test_a_slow_cycle_is_reported_with_where_the_time_went(self):
        clock, notes = _FakeClock(), []
        self.fetch_cost, self.touch_cost = 9.5, 0.2
        watcher = self._watcher(clock, notes, slow_cycle_sec=8.0)
        watcher._iteration("chan", _RecentSet(), first_pass=True)

        watcher._record_cycle("chan", watcher.last_fetch_sec + watcher.last_touch_sec)

        self.assertEqual(len(notes), 1)
        self.assertIn("chan", notes[0])
        self.assertIn("ciclo lento de 9.7 s", notes[0])
        self.assertIn("playlist 9.5 s", notes[0])
        self.assertIn("segmentos 0.2 s", notes[0])

    def test_slow_cycle_notes_are_rate_limited(self):
        clock, notes = _FakeClock(), []
        watcher = self._watcher(clock, notes, slow_cycle_sec=8.0, slow_note_every_sec=30.0)

        watcher._record_cycle("chan", 12.0)
        clock.advance(10)
        watcher._record_cycle("chan", 12.0)  # within 30 s of the previous note: silent
        clock.advance(25)
        watcher._record_cycle("chan", 12.0)  # 35 s after the first note: reported again

        self.assertEqual(len(notes), 2)

    def test_a_failing_playlist_still_records_how_long_it_blocked(self):
        clock, notes = _FakeClock(), []

        def fetch(_login):
            clock.advance(10.0)
            raise TimeoutError("read timed out")

        watcher = SegmentWatcher(fetch, lambda _l, _u: None, note=notes.append, clock=clock)

        with self.assertRaises(TimeoutError):
            watcher._iteration("chan", _RecentSet(), first_pass=True)

        self.assertAlmostEqual(watcher.last_fetch_sec, 10.0)

    def test_the_minute_summary_includes_the_slowest_cycle(self):
        clock, notes = _FakeClock(), []
        enough = threading.Event()
        cycles = {"n": 0}

        def fetch(_login):
            cycles["n"] += 1
            clock.advance(20.0 if cycles["n"] == 2 else 0.1)
            if cycles["n"] >= 3:
                enough.set()
            return _playlist(f"s{cycles['n']}.ts"), BASE

        watcher = SegmentWatcher(
            fetch,
            lambda _l, _u: None,
            note=notes.append,
            clock=clock,
            poll_interval_sec=0.01,
            summary_every_sec=15.0,
            slow_cycle_sec=8.0,
        )
        self.addCleanup(watcher.stop)

        watcher.set_channel("chan")
        self.assertTrue(enough.wait(timeout=5))
        watcher.stop()

        summaries = [note for note in notes if "segmento(s) pedidos" in note]
        self.assertTrue(summaries, notes)
        self.assertIn("ciclo mais lento 20.0 s", summaries[0])
        self.assertIn("1 lento(s)", summaries[0])


class TestThreadLifecycle(unittest.TestCase):
    def _make(self, *, fetch=None):
        touched: list[tuple[str, str]] = []
        enough = threading.Event()
        counter = {"n": 0}

        def default_fetch(_login):
            counter["n"] += 1
            return _playlist(f"s{counter['n']}.ts"), BASE

        def touch(login, url):
            touched.append((login, url))
            if len(touched) >= 3:
                enough.set()

        watcher = SegmentWatcher(
            fetch or default_fetch,
            touch,
            poll_interval_sec=0.01,
            error_backoff_sec=0.01,
            max_backoff_sec=0.02,
            summary_every_sec=3600,
        )
        return watcher, touched, enough

    def test_it_polls_in_the_background_and_stops_cleanly(self):
        watcher, touched, enough = self._make()
        self.addCleanup(watcher.stop)

        watcher.set_channel("somechannel")

        self.assertTrue(enough.wait(timeout=5), "the watcher never requested segments")
        self.assertTrue(watcher.is_running)
        self.assertEqual(watcher.channel, "somechannel")
        self.assertTrue(all(login == "somechannel" for login, _ in touched))

        watcher.stop()
        self.assertFalse(watcher.is_running)
        self.assertEqual(watcher.channel, "")

    def test_setting_the_same_channel_again_keeps_the_same_thread(self):
        watcher, _touched, _enough = self._make()
        self.addCleanup(watcher.stop)

        watcher.set_channel("Alpha")
        first_thread = watcher._thread
        watcher.set_channel("alpha")  # same channel, different case

        self.assertIs(watcher._thread, first_thread)

    def test_changing_channel_restarts_on_the_new_one(self):
        watcher, touched, _enough = self._make()
        self.addCleanup(watcher.stop)

        watcher.set_channel("one")
        first_thread = watcher._thread
        watcher.set_channel("two")

        self.assertIsNot(watcher._thread, first_thread)
        self.assertFalse(first_thread.is_alive())
        self.assertEqual(watcher.channel, "two")

    def test_an_empty_channel_stops_the_watcher(self):
        watcher, _touched, _enough = self._make()
        self.addCleanup(watcher.stop)
        watcher.set_channel("one")

        watcher.set_channel("")

        self.assertFalse(watcher.is_running)

    def test_errors_back_off_instead_of_spinning_and_are_reported_once(self):
        attempts = {"n": 0}
        enough = threading.Event()
        notes: list[str] = []

        def failing_fetch(_login):
            attempts["n"] += 1
            if attempts["n"] >= 3:
                enough.set()
            raise ConnectionError("offline")

        watcher = SegmentWatcher(
            failing_fetch,
            lambda _login, _url: None,
            note=notes.append,
            poll_interval_sec=0.01,
            error_backoff_sec=0.05,
            max_backoff_sec=0.05,
            summary_every_sec=3600,
        )
        self.addCleanup(watcher.stop)

        watcher.set_channel("offline-channel")

        self.assertTrue(enough.wait(timeout=5))
        watcher.stop()
        # Only the first failure is reported (then every 10th), so the log is not flooded.
        self.assertEqual(len(notes), 1)
        self.assertIn("offline-channel", notes[0])
        self.assertGreaterEqual(watcher.errors, 3)


if __name__ == "__main__":
    unittest.main()
