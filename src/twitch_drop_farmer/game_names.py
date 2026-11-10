"""Clean game names that picked up the status text of a twitchdrops.app card.

Older versions flattened a whole registry card into text, so names such as
"HITMAN World of Assassination 1 drop · in 4 days", "Epic Seven Expired 15" or
"Grand Theft Auto VI Coming Soon Releases Nov 19 2026 ·" were saved in the whitelist and in
the campaign cache. Twitch has no game with such a name, so every one of them cost a failed
directory search and two failed image searches on each start, and a whitelist entry with
the noise never matched the real campaign.
"""

from __future__ import annotations

from functools import lru_cache
import re
import unicodedata

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


@lru_cache(maxsize=8192)
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


@lru_cache(maxsize=8192)
def loose_game_key(name: str) -> str:
    """A key that ignores case, accents, spaces and punctuation.

    Twitch only recognises a category by its exact name ("Honkai: Star Rail"), while the
    public registry often drops the punctuation ("Honkai Star Rail"). Both must count as the
    same game, so comparisons between names use this key.
    """
    text = unicodedata.normalize("NFKD", clean_game_name(name))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char for char in text.casefold() if char.isalnum())


def _punctuation(name: str) -> int:
    return sum(1 for char in name if not char.isalnum() and not char.isspace())


def preferred_game_name(variants: list[str]) -> str:
    """The variant most likely to be Twitch's own name: the one with the most punctuation
    ("Blue Protocol: Star Resonance" over "Blue Protocol Star Resonance"), then the shortest."""
    return min(variants, key=lambda item: (-_punctuation(item), len(item), item))


def clean_game_names(names: list[str]) -> list[str]:
    """Clean every name and merge the duplicates cleaning and punctuation create.

    The order of first appearance is kept; of several spellings of one game the preferred
    one (see ``preferred_game_name``) is the one that stays.
    """
    groups: dict[str, list[str]] = {}
    for name in names:
        if not isinstance(name, str):
            continue
        cleaned = clean_game_name(name)
        key = loose_game_key(cleaned)
        if cleaned and key:
            groups.setdefault(key, []).append(cleaned)
    return [preferred_game_name(variants) for variants in groups.values()]
