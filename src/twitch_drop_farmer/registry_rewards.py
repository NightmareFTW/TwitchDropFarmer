"""What a twitchdrops.app game page says about a game's drops: watch time, or a subscription.

Twitch's own campaign details are integrity-gated for many accounts, so the app falls back to
the public registry for the list of games. The registry's game pages do say, for every drop,
what it takes to earn it:

    <div class="drop-card">
      <img ... class="drop-img">
      <div class="drop-name">Scout Shield</div>
      <div class="drop-time">Watch 3h</div>            <- or "Watch 30m", "Watch 1h 30m", "1 sub"
      <div class="drop-campaign">Crimson Desert Drops #1</div>   <- optional
    </div>

and finished drops carry the extra class ``drop-expired``. A game whose active drops are all
"N sub" cannot be farmed by watching, so the app must not try (it would sit there with no
progress until the stall monitor gave up).

Only plain functions and a small on-disk cache live here; fetching is the client's job.
"""
from __future__ import annotations

import html as html_module
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

WATCH = "watch"
SUBSCRIPTION = "subscription"
UNKNOWN = "unknown"

_CARD_START = re.compile(r'<div class="(drop-card[^"]*)">')
_CARD_END = re.compile(r"</div>\s*</div>")
_WATCH_TIME = re.compile(r"^watch\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?$", re.IGNORECASE)
_SUBS = re.compile(r"^(\d+)\s+subs?$", re.IGNORECASE)
_HOME_CARD = re.compile(r'<a\s[^>]*href="(/game/[^"]+)"[^>]*>', re.IGNORECASE)
_ATTRIBUTE = {
    name: re.compile(rf'data-{name}="([^"]*)"', re.IGNORECASE) for name in ("drops", "start", "end")
}


@dataclass(frozen=True, slots=True)
class RegistryDrop:
    name: str
    requirement: str  # WATCH, SUBSCRIPTION or UNKNOWN (a wording this parser does not know)
    minutes: int  # watch time needed (0 unless WATCH)
    subs: int  # subscriptions needed (0 unless SUBSCRIPTION)
    campaign: str
    expired: bool


@dataclass(frozen=True, slots=True)
class RewardSummary:
    """The active drops of one game, by what it takes to earn them."""

    watchable: int = 0
    subscription: int = 0
    unknown: int = 0

    @property
    def has_watchable(self) -> bool:
        return self.watchable > 0

    @property
    def subscription_only(self) -> bool:
        """Every active drop needs a subscription (an unrecognised wording never counts as one)."""
        return self.subscription > 0 and self.watchable == 0 and self.unknown == 0


def parse_requirement(text: str) -> tuple[str, int, int]:
    """("watch", minutes, 0), ("subscription", 0, subs) or ("unknown", 0, 0)."""
    cleaned = re.sub(r"\s+", " ", html_module.unescape(text or "")).strip()
    watch = _WATCH_TIME.match(cleaned)
    if watch and (watch.group(1) or watch.group(2)):
        minutes = int(watch.group(1) or 0) * 60 + int(watch.group(2) or 0)
        if minutes > 0:
            return WATCH, minutes, 0
    subs = _SUBS.match(cleaned)
    if subs and int(subs.group(1)) > 0:
        return SUBSCRIPTION, 0, int(subs.group(1))
    return UNKNOWN, 0, 0


def _field(chunk: str, css_class: str) -> str:
    match = re.search(rf'<div class="{css_class}">(.*?)</div>', chunk, re.DOTALL)
    if match is None:
        return ""
    return html_module.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()


def parse_game_page(page: str) -> list[RegistryDrop]:
    """Every drop card of a game page (finished ones included, flagged ``expired``)."""
    drops: list[RegistryDrop] = []
    for start in _CARD_START.finditer(page or ""):
        end = _CARD_END.search(page, start.end())
        chunk = page[start.end() : end.end() if end else start.end() + 1500]
        requirement, minutes, subs = parse_requirement(_field(chunk, "drop-time"))
        drops.append(
            RegistryDrop(
                name=_field(chunk, "drop-name"),
                requirement=requirement,
                minutes=minutes,
                subs=subs,
                campaign=_field(chunk, "drop-campaign"),
                expired="drop-expired" in start.group(1).split(),
            )
        )
    return drops


def summarize(drops: list[RegistryDrop]) -> RewardSummary | None:
    """Count the active drops by kind. None when there is nothing active to judge."""
    active = [drop for drop in drops if not drop.expired]
    if not active:
        return None
    return RewardSummary(
        watchable=sum(1 for drop in active if drop.requirement == WATCH),
        subscription=sum(1 for drop in active if drop.requirement == SUBSCRIPTION),
        unknown=sum(1 for drop in active if drop.requirement == UNKNOWN),
    )


@dataclass(frozen=True, slots=True)
class CardWindow:
    """When the registry says a game's campaigns run (None where the card does not say)."""

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    expired: bool = False  # a "Campaign history" card: no dates, nothing to farm
    upcoming: bool = False  # "Coming soon" with no dates (a game that has not launched yet)
    drops: int = 0  # how many drops the card says the game has (0 = not said)

    @property
    def known(self) -> bool:
        return self.expired or self.upcoming or (self.starts_at is not None and self.ends_at is not None)


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _int_attribute(card: str, name: str) -> int:
    found = _ATTRIBUTE[name].search(card)
    try:
        return max(0, int(found.group(1))) if found else 0
    except ValueError:
        return 0


def parse_card_window(card: str) -> CardWindow:
    """The window of one game card on the registry home page (its whole ``<a ...>...</a>``).

    Active, "ending today" and upcoming cards carry ``data-start``/``data-end`` on the ``<a>``;
    a finished game is a ``game-card--expired`` card with a ``status-expired`` badge and no
    dates; a game that has not launched yet can be a bare ``status-upcoming`` card.
    """
    card = card or ""
    found = {name: _ATTRIBUTE[name].search(card) for name in ("start", "end")}
    return CardWindow(
        starts_at=_parse_utc(found["start"].group(1)) if found["start"] else None,
        ends_at=_parse_utc(found["end"].group(1)) if found["end"] else None,
        expired="game-card--expired" in card or "status-expired" in card,
        upcoming="status-upcoming" in card,
        drops=_int_attribute(card, "drops"),
    )


def parse_home_signatures(page: str) -> dict[str, str]:
    """slug -> a signature of the game's card on the registry home page.

    The signature (drop count and campaign dates) changes whenever the game's campaigns change,
    so a game page only has to be read again when it does.
    """
    signatures: dict[str, str] = {}
    for tag in _HOME_CARD.finditer(page or ""):
        slug = tag.group(1).rsplit("/", 1)[-1]
        if not slug or slug in signatures:
            continue
        values = []
        for name in ("drops", "start", "end"):
            found = _ATTRIBUTE[name].search(tag.group(0))
            values.append(found.group(1) if found else "")
        # A card without data (a game whose campaigns are over) has nothing to check.
        if any(values):
            signatures[slug] = "|".join(values)
    return signatures


def slug_from_link(link_url: str) -> str:
    """The registry slug in a ``.../game/<slug>`` link ("" when it is not one)."""
    match = re.search(r"/game/([^/?#]+)", link_url or "")
    return match.group(1) if match else ""


class RewardCache:
    """slug -> RewardSummary, kept on disk so a restart does not read every page again."""

    def __init__(self, path: Path, *, max_age_sec: float = 3 * 24 * 3600.0, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._max_age = max_age_sec
        self._clock = clock
        self._entries: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = data.get("games") if isinstance(data, dict) else None
        if isinstance(entries, dict):
            self._entries = {
                slug: entry for slug, entry in entries.items() if isinstance(slug, str) and isinstance(entry, dict)
            }

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"games": self._entries}, indent=1), encoding="utf-8")
        os.replace(tmp, self._path)

    def store(self, slug: str, signature: str, summary: RewardSummary | None) -> None:
        self._entries[slug] = {
            "signature": signature,
            "checked_at": self._clock(),
            "known": summary is not None,
            "watchable": summary.watchable if summary else 0,
            "subscription": summary.subscription if summary else 0,
            "unknown": summary.unknown if summary else 0,
        }

    def is_fresh(self, slug: str, signature: str) -> bool:
        entry = self._entries.get(slug)
        if entry is None or entry.get("signature") != signature:
            return False
        try:
            return self._clock() - float(entry.get("checked_at", 0)) < self._max_age
        except (TypeError, ValueError):
            return False

    def summary(self, slug: str) -> RewardSummary | None:
        """What is known about the game, even if it is old (old data beats none)."""
        entry = self._entries.get(slug)
        if not entry or not entry.get("known"):
            return None
        try:
            return RewardSummary(
                watchable=int(entry.get("watchable", 0)),
                subscription=int(entry.get("subscription", 0)),
                unknown=int(entry.get("unknown", 0)),
            )
        except (TypeError, ValueError):
            return None

    def stale(self, signatures: dict[str, str]) -> list[str]:
        """The slugs whose page has to be read (never read, changed, or too old)."""
        return [slug for slug, signature in signatures.items() if not self.is_fresh(slug, signature)]
