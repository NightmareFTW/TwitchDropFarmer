"""Continuous, low-traffic HLS segment requests for the channel being farmed.

Why this exists: Twitch acknowledges the ``minute-watched`` event (HTTP 204) but may
only credit watch time to a viewer whose HLS traffic its video servers actually see.
The app used to touch ONE segment per minute, right after the heartbeat. A player
requests EVERY new segment (every couple of seconds). This watcher polls the media
playlist and requests each NEW segment with a tiny ranged GET, so traffic stays at a
few KB/s instead of the stream's several Mbit/s, and it runs on its own thread so it
no longer depends on the UI event loop.

The network access is injected (``fetch_playlist`` / ``touch_segment``), which keeps
the logic unit-testable without any HTTP.
"""

from __future__ import annotations

from collections import deque
import threading
import time
from typing import Callable
from urllib.parse import urljoin


def playlist_segment_urls(playlist_text: str, base_url: str) -> list[str]:
    """Absolute URLs of the media segments listed in an HLS media playlist."""
    urls: list[str] = []
    for raw in playlist_text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            urls.append(urljoin(base_url, line))
    return urls


class _RecentSet:
    """Remembers the most recent N items (so the 'seen' set cannot grow forever)."""

    def __init__(self, limit: int = 128) -> None:
        self._order: deque[str] = deque()
        self._items: set[str] = set()
        self._limit = limit

    def __contains__(self, item: str) -> bool:
        return item in self._items

    def add(self, item: str) -> None:
        if item in self._items:
            return
        self._items.add(item)
        self._order.append(item)
        while len(self._order) > self._limit:
            self._items.discard(self._order.popleft())


class SegmentWatcher:
    def __init__(
        self,
        fetch_playlist: Callable[[str], tuple[str, str]],
        touch_segment: Callable[[str, str], None],
        *,
        note: Callable[[str], None] | None = None,
        poll_interval_sec: float = 2.0,
        error_backoff_sec: float = 10.0,
        max_backoff_sec: float = 60.0,
        summary_every_sec: float = 60.0,
        slow_cycle_sec: float = 8.0,
        slow_note_every_sec: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch_playlist = fetch_playlist
        self._touch_segment = touch_segment
        self._note = note or (lambda _message: None)
        self._poll_interval = poll_interval_sec
        self._error_backoff = error_backoff_sec
        self._max_backoff = max_backoff_sec
        self._summary_every = summary_every_sec
        # Timing diagnostics: a normal cycle takes well under a second. A cycle that
        # takes ``slow_cycle_sec`` or more is reported (at most once per
        # ``slow_note_every_sec``) with the split between playlist and segment time,
        # so a stall can be pinned on the exact call that blocked.
        self._slow_cycle = slow_cycle_sec
        self._slow_note_every = slow_note_every_sec
        self._clock = clock
        self._last_slow_note: float | None = None
        self.last_fetch_sec = 0.0
        self.last_touch_sec = 0.0
        self._window_slowest = 0.0
        self._window_slow_cycles = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._login = ""
        self.segments_touched = 0
        self.errors = 0

    # ------------------------------------------------------------------ control
    @property
    def channel(self) -> str:
        return self._login if self.is_running else ""

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def set_channel(self, login: str) -> None:
        """Watch ``login``. A no-op if it is already being watched."""
        login = (login or "").strip()
        if not login:
            self.stop()
            return
        with self._lock:
            if self.is_running and self._login.casefold() == login.casefold():
                return
            self._stop_locked()
            self._login = login
            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                args=(login, self._stop_event),
                name=f"hls-watch-{login}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None
        self._login = ""

    # --------------------------------------------------------------------- work
    def _iteration(self, login: str, seen: _RecentSet, first_pass: bool) -> int:
        """One poll: fetch the playlist and request every segment not seen yet.

        On the first pass only the newest segment is requested (a player joins at the
        live edge); the rest of the window is just remembered. Returns the number of
        segments requested successfully. Raises when the playlist cannot be fetched or
        when every segment request failed, so the caller backs off (and the client
        re-resolves the expiring playback token).
        """
        self.last_fetch_sec = 0.0
        self.last_touch_sec = 0.0
        started = self._clock()
        try:
            text, base_url = self._fetch_playlist(login)
        finally:
            self.last_fetch_sec = self._clock() - started
        urls = playlist_segment_urls(text, base_url)
        if first_pass:
            fresh = urls[-1:]
            for url in urls:
                seen.add(url)
        else:
            fresh = [url for url in urls if url not in seen]
        touched = 0
        last_error: Exception | None = None
        touch_started = self._clock()
        try:
            for url in fresh:
                seen.add(url)
                try:
                    self._touch_segment(login, url)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    self.errors += 1
                    continue
                touched += 1
                self.segments_touched += 1
        finally:
            self.last_touch_sec = self._clock() - touch_started
        if fresh and touched == 0 and last_error is not None:
            raise last_error
        return touched

    def _record_cycle(self, login: str, elapsed: float) -> None:
        """Track how long one poll cycle took; report the slow ones (rate limited)."""
        self._window_slowest = max(self._window_slowest, elapsed)
        if elapsed < self._slow_cycle:
            return
        self._window_slow_cycles += 1
        now = self._clock()
        if self._last_slow_note is not None and now - self._last_slow_note < self._slow_note_every:
            return
        self._last_slow_note = now
        self._note(
            f"Vigilância HLS de {login}: ciclo lento de {elapsed:.1f} s "
            f"(playlist {self.last_fetch_sec:.1f} s, segmentos {self.last_touch_sec:.1f} s)."
        )

    def _run(self, login: str, stop_event: threading.Event) -> None:
        seen = _RecentSet()
        first_pass = True
        failures = 0
        window_started = self._clock()
        window_segments = self.segments_touched
        window_errors = self.errors
        self._window_slowest = 0.0
        self._window_slow_cycles = 0
        while not stop_event.is_set():
            cycle_started = self._clock()
            try:
                self._iteration(login, seen, first_pass)
                first_pass = False
                failures = 0
                wait = self._poll_interval
            except Exception as exc:  # noqa: BLE001
                failures += 1
                self.errors += 1
                if failures == 1 or failures % 10 == 0:
                    self._note(f"Vigilância HLS de {login}: {type(exc).__name__}: {exc}")
                # The playlist (or its token) may have expired: start from the live edge again.
                first_pass = True
                wait = min(self._error_backoff * failures, self._max_backoff)
            now = self._clock()
            self._record_cycle(login, now - cycle_started)
            if now - window_started >= self._summary_every:
                self._note(
                    f"Vigilância HLS de {login}: {self.segments_touched - window_segments} segmento(s) "
                    f"pedidos e {self.errors - window_errors} erro(s) em {int(now - window_started)} s "
                    f"(ciclo mais lento {self._window_slowest:.1f} s, {self._window_slow_cycles} lento(s))."
                )
                window_started = now
                window_segments = self.segments_touched
                window_errors = self.errors
                self._window_slowest = 0.0
                self._window_slow_cycles = 0
            stop_event.wait(wait)
