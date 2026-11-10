"""Clean game names that picked up the status text of a twitchdrops.app card.

Older versions flattened a whole registry card into text, so names such as
"HITMAN World of Assassination 1 drop · in 4 days", "Epic Seven Expired 15" or
"Grand Theft Auto VI Coming Soon Releases Nov 19 2026 ·" were saved in the whitelist and in
the campaign cache. Twitch has no game with such a name, so every one of them cost a failed
directory search and two failed image searches on each start, and a whitelist entry with
the noise never matched the real campaign.
"""

from __future__ import annotations

import re

_NOISE: tuple[re.Pattern[str], ...] = (
    # "... Expired 15" (the number is the card's position, not part of the name).
    re.compile(r"\s+Expired\s+\d+\s*$", re.IGNORECASE),
    # "... 1 drop", "... 3 drops · in 4 days", "... 2 drops - ends in 2 days".
    re.compile(r"\s+\d+\s+drops?\s*(?:[·•|–-].*)?$", re.IGNORECASE),
    # "... Coming Soon Releases Nov 19 2026 ·"
    re.compile(r"\s+Coming\s+Soon\b.*$", re.IGNORECASE),
    # A dangling bullet and whatever follows it.
    re.compile(r"\s*[·•].*$"),
)


def clean_game_name(name: str) -> str:
    """``name`` without a trailing card status. Ordinary names come back unchanged."""
    original = " ".join(str(name or "").split())
    text = original
    for _ in range(4):  # a name can carry more than one suffix
        before = text
        for pattern in _NOISE:
            text = pattern.sub("", text).strip()
        if text == before:
            break
    return text or original


def clean_game_names(names: list[str]) -> list[str]:
    """Clean every name and drop the duplicates that cleaning creates (order kept)."""
    seen: set[str] = set()
    output: list[str] = []
    for name in names:
        if not isinstance(name, str):
            continue
        cleaned = clean_game_name(name)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output
