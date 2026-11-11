"""Reading what the public registry says about drops: watch time versus a subscription.

The HTML in tests/fixtures/registry was trimmed from the real twitchdrops.app pages (Nov 2026).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.registry_rewards import (  # noqa: E402
    SUBSCRIPTION,
    UNKNOWN,
    WATCH,
    RewardCache,
    RewardSummary,
    parse_card_window,
    parse_game_page,
    parse_home_signatures,
    parse_requirement,
    slug_from_link,
    summarize,
)

FIXTURES = Path(__file__).parent / "fixtures" / "registry"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def card(time_text: str, *, name: str = "Reward", expired: bool = False, campaign: str = "") -> str:
    classes = "drop-card drop-expired" if expired else "drop-card"
    extra = f'<div class="drop-campaign">{campaign}</div>' if campaign else ""
    return (
        f'<div class="{classes}"> <img src="x.png" alt="{name}" class="drop-img">'
        f' <div class="drop-name">{name}</div> <div class="drop-time">{time_text}</div> {extra}</div>'
    )


class TestRequirementWording(unittest.TestCase):
    def test_every_wording_seen_on_the_real_site(self):
        for text, expected in {
            "Watch 30m": (WATCH, 30, 0),
            "Watch 1h": (WATCH, 60, 0),
            "Watch 1h 30m": (WATCH, 90, 0),
            "Watch 15h": (WATCH, 900, 0),
            "1 sub": (SUBSCRIPTION, 0, 1),
            "2 subs": (SUBSCRIPTION, 0, 2),
            "  Watch   2h ": (WATCH, 120, 0),
        }.items():
            with self.subTest(text):
                self.assertEqual(parse_requirement(text), expected)

    def test_a_wording_it_does_not_know_is_unknown_never_a_guess(self):
        for text in ("", "Watch", "Watch 0m", "0 subs", "Claim in game", "Gift 5 subs", "Subscribe"):
            with self.subTest(text):
                self.assertEqual(parse_requirement(text)[0], UNKNOWN)


class TestRealGamePages(unittest.TestCase):
    def test_a_game_whose_only_active_drop_is_a_subscription_is_subscription_only(self):
        for game in ("elden-ring", "call-of-duty-modern-warfare-4"):
            with self.subTest(game):
                summary = summarize(parse_game_page(fixture(game)))

                self.assertTrue(summary.subscription_only)
                self.assertFalse(summary.has_watchable)
                self.assertEqual((summary.watchable, summary.subscription, summary.unknown), (0, 1, 0))

    def test_a_game_with_watch_and_subscription_drops_stays_farmable(self):
        summary = summarize(parse_game_page(fixture("cyberpunk-2077")))

        self.assertTrue(summary.has_watchable)
        self.assertFalse(summary.subscription_only)
        self.assertEqual((summary.watchable, summary.subscription), (1, 1))

    def test_finished_drops_do_not_count(self):
        """Crimson Desert's subscription badge is over (drop-expired): only the 6 watch drops are active."""
        drops = parse_game_page(fixture("crimson-desert"))
        summary = summarize(drops)

        self.assertGreater(len(drops), 6)
        self.assertEqual((summary.watchable, summary.subscription), (6, 0))
        self.assertTrue(any(d.expired and d.requirement == SUBSCRIPTION for d in drops))

    def test_cards_without_a_campaign_line_do_not_swallow_the_next_card(self):
        """Single-campaign games have no drop-campaign div; each card must still be read on its own."""
        drops = parse_game_page(fixture("captains-call"))

        self.assertEqual([(d.name, d.minutes) for d in drops], [("42 Gold", 60), ("42 Potions", 480), ("24 Catnip", 900)])
        self.assertTrue(all(d.requirement == WATCH and not d.expired and d.campaign == "" for d in drops))

    def test_the_campaign_name_is_read_when_there_is_one(self):
        drops = [d for d in parse_game_page(fixture("crimson-desert")) if not d.expired]

        self.assertEqual(len(drops), 6)
        self.assertEqual({d.campaign for d in drops}, {"CD DLC Week 2", "Crimson Desert DLC Week 2"})


class TestParserLimits(unittest.TestCase):
    def test_a_drop_time_outside_a_card_is_not_a_drop(self):
        """Synthetic: stray text that looks like a requirement, outside any drop-card."""
        page = card("1 sub", name="Badge") + '<div class="drop-time">Watch 5h</div><p>Watch 3h</p>'

        drops = parse_game_page(page)

        self.assertEqual([(d.name, d.requirement) for d in drops], [("Badge", SUBSCRIPTION)])

    def test_a_card_without_a_time_does_not_borrow_the_next_cards(self):
        """Synthetic: the first card is cut short; it must be unknown, not 'Watch 5h' from its neighbour."""
        page = '<div class="drop-card"> <div class="drop-name">No time</div> </div>' + card("Watch 5h", name="Next")

        drops = parse_game_page(page)

        self.assertEqual([(d.name, d.requirement) for d in drops], [("No time", UNKNOWN), ("Next", WATCH)])

    def test_an_unknown_wording_blocks_the_subscription_only_verdict(self):
        """If one active drop is something we do not understand, the game must not be called sub-only."""
        summary = summarize(parse_game_page(card("1 sub") + card("Claim in game")))

        self.assertEqual((summary.subscription, summary.unknown), (1, 1))
        self.assertFalse(summary.subscription_only)

    def test_html_entities_in_names_are_decoded(self):
        drops = parse_game_page(card("Watch 1h", name="Lantern &amp; Meat Dish"))

        self.assertEqual(drops[0].name, "Lantern & Meat Dish")

    def test_a_page_with_no_cards_or_only_finished_ones_says_nothing(self):
        self.assertEqual(parse_game_page(""), [])
        self.assertEqual(parse_game_page("<html>layout changed</html>"), [])
        self.assertIsNone(summarize([]))
        self.assertIsNone(summarize(parse_game_page(card("1 sub", expired=True))))


class TestHomePage(unittest.TestCase):
    def setUp(self) -> None:
        self.home = fixture("home_excerpt")

    def test_signatures_cover_the_games_that_have_a_campaign_and_skip_the_finished_ones(self):
        signatures = parse_home_signatures(self.home)

        self.assertEqual(signatures["elden-ring"], "1|2026-11-02T07:00:00Z|2026-11-30T06:59:59.999Z")
        self.assertIn("eternal-return", signatures)
        self.assertNotIn("fortnite", signatures)  # a "campaign history" card has no data at all

    def test_a_changed_campaign_changes_the_signature(self):
        before = parse_home_signatures(self.home)["elden-ring"]
        after = parse_home_signatures(self.home.replace('data-drops="1" data-end="2026-11-30', 'data-drops="2" data-end="2026-11-30'))["elden-ring"]

        self.assertNotEqual(before, after)

    def test_the_window_of_each_kind_of_card(self):
        import re
        tags = {m.group(1): m.group(0) for m in re.finditer(r'(?is)<a\b[^>]*href="/game/([^"]+)"[^>]*>.*?</a>', self.home)}

        active = parse_card_window(tags["elden-ring"])
        self.assertEqual(active.starts_at, datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(active.ends_at, datetime(2026, 11, 30, 6, 59, 59, 999000, tzinfo=timezone.utc))
        self.assertTrue(active.known and not active.expired)

        upcoming = parse_card_window(tags["eternal-return"])
        self.assertEqual(upcoming.starts_at, datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc))

        expired = parse_card_window(tags["fortnite"])
        self.assertTrue(expired.expired and expired.known)
        self.assertIsNone(expired.starts_at)

        coming_soon = parse_card_window(tags["grand-theft-auto-vi"])  # a bare "Coming Soon" card: a badge, no dates
        self.assertTrue(coming_soon.upcoming and coming_soon.known)
        self.assertIsNone(coming_soon.starts_at)

        unknown = parse_card_window('<a href="/game/x">')
        self.assertFalse(unknown.known)

    def test_slug_from_link(self):
        self.assertEqual(slug_from_link("https://twitchdrops.app/game/elden-ring"), "elden-ring")
        self.assertEqual(slug_from_link("/game/elden-ring?x=1"), "elden-ring")
        self.assertEqual(slug_from_link("https://www.twitch.tv/drops/campaigns"), "")
        self.assertEqual(slug_from_link(""), "")


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class TestRewardCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "registry_rewards.json"
        self.clock = _Clock()
        self.cache = RewardCache(self.path, max_age_sec=3600, clock=self.clock)

    def test_what_was_stored_survives_a_restart(self):
        self.cache.store("elden-ring", "sig", RewardSummary(watchable=0, subscription=1))
        self.cache.save()

        again = RewardCache(self.path, max_age_sec=3600, clock=self.clock)

        self.assertTrue(again.summary("elden-ring").subscription_only)
        self.assertTrue(again.is_fresh("elden-ring", "sig"))
        self.assertEqual([p.name for p in self.path.parent.glob("*.tmp")], [])

    def test_a_game_is_read_again_only_when_its_card_changed_or_the_data_is_old(self):
        self.cache.store("a", "sig1", RewardSummary(watchable=2))

        self.assertEqual(self.cache.stale({"a": "sig1"}), [])
        self.assertEqual(self.cache.stale({"a": "sig2"}), ["a"])  # the card changed
        self.assertEqual(self.cache.stale({"b": "x"}), ["b"])  # never read
        self.clock.now += 3601
        self.assertEqual(self.cache.stale({"a": "sig1"}), ["a"])  # too old

    def test_old_data_still_answers_until_it_is_replaced(self):
        self.cache.store("a", "sig1", RewardSummary(subscription=1))
        self.clock.now += 10_000

        self.assertTrue(self.cache.summary("a").subscription_only)

    def test_a_game_with_nothing_active_is_remembered_so_it_is_not_asked_again(self):
        self.cache.store("a", "sig", None)

        self.assertIsNone(self.cache.summary("a"))
        self.assertTrue(self.cache.is_fresh("a", "sig"))

    def test_a_damaged_file_is_ignored_not_fatal(self):
        for bad in ("{ not json", "[]", '{"games": 5}', '{"games": {"a": 7}}'):
            with self.subTest(bad):
                self.path.write_text(bad, encoding="utf-8")

                cache = RewardCache(self.path)

                self.assertIsNone(cache.summary("a"))

    def test_a_damaged_entry_is_ignored(self):
        self.path.write_text(json.dumps({"games": {"a": {"known": True, "watchable": "many"}}}), encoding="utf-8")

        self.assertIsNone(RewardCache(self.path).summary("a"))


if __name__ == "__main__":
    unittest.main()
