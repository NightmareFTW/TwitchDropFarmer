"""Which campaigns the user has already finished, kept on disk.

When every drop of a campaign has been earned (and claimed) Twitch stops listing it among the
"in progress" campaigns of the Inventory. The public registry, which knows nothing about the user,
still lists it as running, so the app saw a brand new campaign with no data (0/0 min) and farmed it
for hours without any credit. This remembers the campaigns the app saw finished, and the ones that
credited nothing after a whole recovery (restart, other channels, give up), so they keep the
"done" label and stay out of the pool until a different campaign of the same game shows up.

Two kinds of memory, because they are not equally certain:

* ``completed``: the app saw the campaign finished in the Inventory. Remembered until it ends.
* ``no_credit``: the farm gave up on a campaign that never credited a minute. That is an inference
  (finished long ago, the account cannot earn it...), so it only lasts NO_CREDIT_TTL_SEC and the
  user can clear it.

A registry campaign is "the same" campaign when its game, end date and number of drops fit; a
later campaign of the same game ends on another date, or has more drops, and is not hidden.

Pure logic (no Qt, no network) with an injectable clock.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .game_names import loose_game_key

REASON_COMPLETED = "completed"
REASON_NO_CREDIT = "no_credit"

# The registry's end date is Twitch's own, so the same campaign matches to the millisecond; a
# few minutes of slack only covers rounding.
END_TOLERANCE = timedelta(minutes=5)
NO_CREDIT_TTL_SEC = 48 * 3600.0
KEEP_AFTER_END = timedelta(days=7)


def _iso(moment: datetime) -> str:
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).isoformat()


def _parse(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class CompletionMemory:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._entries: list[dict] = []
        # The engine's worker thread and the window's thread both write it.
        self._lock = threading.RLock()
        self.load()

    # ----------------------------------------------------------------- disk
    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = data.get("campaigns") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return
        now = datetime.fromtimestamp(self._clock(), timezone.utc)
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("game") or _parse(entry.get("ends_at")) is None:
                continue
            if _parse(entry["ends_at"]) + KEEP_AFTER_END < now:
                continue  # long over: nothing can match it any more
            kept.append(entry)
        self._entries = kept

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"campaigns": self._entries}, indent=1), encoding="utf-8")
            os.replace(tmp, self._path)

    # ----------------------------------------------------------------- writing
    def record(self, game_name: str, *, ends_at: datetime, drops: int, reason: str) -> bool:
        """Remember a finished campaign. True when something new was stored."""
        key = loose_game_key(game_name)
        if not key:
            return False
        with self._lock:
            return self._record(key, game_name, ends_at, drops, reason)

    def _record(self, key: str, game_name: str, ends_at: datetime, drops: int, reason: str) -> bool:
        existing = self._find(key, ends_at)
        if existing is not None:
            if existing["reason"] == REASON_NO_CREDIT and reason == REASON_COMPLETED:
                existing["reason"] = REASON_COMPLETED  # seen for real: the inference is replaced by the fact
                existing["drops"] = max(int(existing.get("drops", 0)), int(drops))
                return True
            return False
        self._entries.append(
            {
                "game": key,
                "label": game_name,
                "ends_at": _iso(ends_at),
                "drops": int(drops),
                "reason": reason,
                "recorded_at": self._clock(),
            }
        )
        return True

    def forget_no_credit(self) -> int:
        """Drop the inferences ("it credited nothing") so those campaigns are tried again."""
        with self._lock:
            before = len(self._entries)
            self._entries = [entry for entry in self._entries if entry["reason"] != REASON_NO_CREDIT]
            return before - len(self._entries)

    # ----------------------------------------------------------------- reading
    def is_completed(self, game_name: str, *, ends_at: datetime, drops: int = 0) -> bool:
        """True when this game's campaign ending at ``ends_at`` was seen finished.

        ``drops`` is how many drops the registry lists for it now (0 = unknown). More than what was
        finished means another campaign was added to the game, which must not be hidden.
        """
        key = loose_game_key(game_name)
        entry = self._find(key, ends_at)
        if entry is None:
            return False
        if entry["reason"] == REASON_NO_CREDIT and self._clock() - float(entry.get("recorded_at", 0)) > NO_CREDIT_TTL_SEC:
            return False
        known = int(entry.get("drops", 0))
        return not (drops and known and drops > known)

    def _find(self, key: str, ends_at: datetime) -> dict | None:
        target = ends_at if ends_at.tzinfo else ends_at.replace(tzinfo=timezone.utc)
        for entry in self._entries:
            if entry["game"] != key:
                continue
            ends = _parse(entry["ends_at"])
            if ends is not None and abs(ends - target) <= END_TOLERANCE:
                return entry
        return None

    def __len__(self) -> int:
        return len(self._entries)
