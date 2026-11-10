"""Game identity: names compared without punctuation, Twitch's own category lookup and box art."""
from __future__ import annotations

import hashlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer import twitch_client as tc  # noqa: E402
from twitch_drop_farmer.config import AppConfig  # noqa: E402
from twitch_drop_farmer.farmer import FarmEngine  # noqa: E402
from twitch_drop_farmer.game_names import (  # noqa: E402
    clean_game_names,
    loose_game_key,
    preferred_game_name,
)
from twitch_drop_farmer.twitch_client import (  # noqa: E402
    GameRef,
    TwitchClient,
    is_placeholder_box_art,
    official_box_art_url,
)
from twitch_drop_farmer.ui import (  # noqa: E402
    _dashboard_game_key,
    _effective_dashboard_game_names,
    _normalize_dashboard_game_name,
    MainWindow,
)

BLUE = "Blue Protocol: Star Resonance"
BLUE_NO_COLON = "Blue Protocol Star Resonance"


class TestLooseKey(unittest.TestCase):
    def test_case_accents_spaces_and_punctuation_are_ignored(self):
        self.assertEqual(loose_game_key(BLUE), loose_game_key(BLUE_NO_COLON))
        self.assertEqual(loose_game_key("Honkai: Star Rail"), loose_game_key("honkai star rail"))
        self.assertEqual(loose_game_key("Pokémon Trading Card Game Live"), loose_game_key("Pokemon Trading Card Game Live"))
        self.assertEqual(loose_game_key("Vampire: The Masquerade - Bloodhunt"), loose_game_key("Vampire The Masquerade Bloodhunt"))

    def test_different_games_keep_different_keys(self):
        self.assertNotEqual(loose_game_key("Dota 2"), loose_game_key("Dota"))
        self.assertNotEqual(loose_game_key("Planet Zoo"), loose_game_key("Planet Zoo 2"))

    def test_a_registry_status_suffix_does_not_change_the_key(self):
        self.assertEqual(loose_game_key("HITMAN World of Assassination 1 drop · in 4 days"), loose_game_key("HITMAN World of Assassination"))

    def test_the_spelling_with_punctuation_is_the_preferred_one(self):
        self.assertEqual(preferred_game_name([BLUE_NO_COLON, BLUE]), BLUE)
        self.assertEqual(preferred_game_name(["Same", "Same "]), "Same")

    def test_the_saved_lists_are_merged_to_one_entry_per_game_keeping_order(self):
        names = ["Alpha", BLUE_NO_COLON, "Beta", BLUE, "alpha"]

        self.assertEqual(clean_game_names(names), ["Alpha", BLUE, "Beta"])


class TestWhitelistMatching(unittest.TestCase):
    def _engine(self, **config) -> FarmEngine:
        return FarmEngine(MagicMock(), AppConfig(**config))

    def test_a_whitelist_entry_matches_the_registry_spelling_without_punctuation(self):
        engine = self._engine(whitelist_games=["Honkai: Star Rail"])

        self.assertTrue(engine._game_is_allowed("Honkai Star Rail"))
        self.assertFalse(engine._game_is_allowed("Genshin Impact"))

    def test_the_blacklist_works_the_same_way(self):
        engine = self._engine(blacklist_games=["Honkai: Star Rail"])

        self.assertFalse(engine._game_is_allowed("Honkai Star Rail"))
        self.assertTrue(engine._game_is_allowed("Genshin Impact"))


def _redirect(game_id: str = "", slug: str = "") -> dict:
    game = {"id": game_id, "slug": slug, "__typename": "Game"} if slug else None
    return {"data": {"game": game}}


def _search(*suggestions: tuple[str, str, str, bool]) -> dict:
    """(text, id, slug, is_category) per suggestion."""
    edges = []
    for text, game_id, slug, is_category in suggestions:
        content = (
            {"__typename": "SearchSuggestionCategory", "id": game_id, "game": {"id": game_id, "slug": slug}}
            if is_category
            else None
        )
        edges.append({"node": {"content": content, "text": text}})
    return {"data": {"searchSuggestions": {"edges": edges}}}


class TestResolveGame(unittest.TestCase):
    def _client(self, *responses) -> TwitchClient:
        client = TwitchClient()
        client._post_gql = MagicMock(side_effect=list(responses))
        return client

    def test_an_exact_name_is_found_with_one_request(self):
        client = self._client(_redirect("386821", "black-desert"))

        ref = client.resolve_game("Black Desert")

        self.assertEqual(ref, GameRef(name="Black Desert", id="386821", slug="black-desert"))
        self.assertEqual(client._post_gql.call_count, 1)

    def test_a_name_without_punctuation_is_found_through_twitchs_category_search(self):
        """Regression: 'Blue Protocol Star Resonance' never resolved and became a second card."""
        client = self._client(_redirect(), _search((BLUE, "266795834", "star-resonance", True)))

        ref = client.resolve_game(BLUE_NO_COLON)

        self.assertEqual(ref, GameRef(name=BLUE, id="266795834", slug="star-resonance"))
        self.assertEqual(client._post_gql.call_count, 2)
        sent = client._post_gql.call_args_list[1].args[0]
        self.assertEqual(sent["operationName"], "SearchTray_SearchSuggestions")
        self.assertEqual(sent["variables"]["queryFragment"], BLUE_NO_COLON)

    def test_a_similar_but_different_game_is_never_accepted(self):
        client = self._client(_redirect(), _search(("Blue Protocol", "1", "blue-protocol", True),
                                                   ("Star Resonance Fan Page", "2", "x", True)))

        self.assertIsNone(client.resolve_game(BLUE_NO_COLON))

    def test_suggestions_that_are_not_categories_are_ignored(self):
        client = self._client(_redirect(), _search((BLUE_NO_COLON, "", "", False)))

        self.assertIsNone(client.resolve_game(BLUE_NO_COLON))

    def test_answers_are_cached_by_the_loose_key_including_not_found(self):
        client = self._client(_redirect("1", "game-one"), _redirect(), _search())

        first = client.resolve_game("Game: One")
        again = client.resolve_game("game one")
        missing = client.resolve_game("Nothing Here")
        missing_again = client.resolve_game("nothing here")

        self.assertEqual((first, again), (first, first))
        self.assertIsNone(missing)
        self.assertIsNone(missing_again)
        self.assertEqual(client._post_gql.call_count, 3)

    def test_a_network_error_is_not_cached(self):
        client = self._client(requests.ConnectionError("down"), _redirect("386821", "black-desert"))

        with self.assertRaises(requests.ConnectionError):
            client.resolve_game("Black Desert")

        self.assertEqual(client.resolve_game("Black Desert").slug, "black-desert")

    def test_resolve_game_slug_uses_it(self):
        client = self._client(_redirect(), _search(("Honkai: Star Rail", "213930085", "honkai-star-rail", True)))

        self.assertEqual(client.resolve_game_slug("Honkai Star Rail"), "honkai-star-rail")
        self.assertEqual(client.resolve_game_slug("Honkai Star Rail"), "honkai-star-rail")  # cached
        self.assertEqual(client._post_gql.call_count, 2)


class TestBoxArt(unittest.TestCase):
    def test_the_official_url_is_built_from_the_category_id(self):
        self.assertEqual(
            official_box_art_url("386821"),
            "https://static-cdn.jtvnw.net/ttv-boxart/386821_IGDB-144x192.jpg",
        )
        self.assertEqual(official_box_art_url("386821", 285, 380).endswith("386821_IGDB-285x380.jpg"), True)
        self.assertEqual(official_box_art_url("black-desert"), "")
        self.assertEqual(official_box_art_url(""), "")

    def test_data_that_has_only_an_id_still_yields_the_box_art(self):
        client = TwitchClient()

        self.assertEqual(client._game_box_art_url({"id": "217432230"}), official_box_art_url("217432230"))
        self.assertEqual(
            client._game_box_art_url({"boxArtURL": "https://x/{width}x{height}.jpg", "id": "1"}),
            "https://x/144x192.jpg",
        )

    def test_a_known_category_gets_twitchs_own_image_without_asking_steam_or_google(self):
        """Regression: Black Desert showed Steam's library art, Chaos Zero Nightmare a generic icon."""
        client = TwitchClient()
        client._post_gql = MagicMock(return_value=_redirect("386821", "black-desert"))
        client.session.get = MagicMock()

        url = client.resolve_game_box_art_url("Black Desert")

        self.assertEqual(url, official_box_art_url("386821"))
        client.session.get.assert_not_called()

    def test_steam_is_only_used_for_a_store_entry_with_the_same_name(self):
        client = TwitchClient()
        response = MagicMock()
        response.json.return_value = {"items": [{"id": 1, "name": "Completely Different Game", "tiny_image": "https://steam/t.jpg"}]}
        client.session.get = MagicMock(return_value=response)
        client._resolve_google_game_box_art_url = MagicMock(return_value="https://google/g.jpg")
        client._resolve_duckduckgo_game_box_art_url = MagicMock(return_value="")

        url = client._resolve_external_game_box_art_url("Chaos Zero Nightmare")

        self.assertEqual(url, "https://google/g.jpg")  # not the unrelated Steam game's image

    def test_the_generic_image_twitch_serves_for_a_missing_box_art_is_recognised(self):
        generic = b"generic gamepad image"
        with patch.object(tc, "PLACEHOLDER_BOX_ART_MD5", frozenset({hashlib.md5(generic).hexdigest()})):
            self.assertTrue(is_placeholder_box_art(generic))
            self.assertFalse(is_placeholder_box_art(b"a real cover"))
            self.assertFalse(is_placeholder_box_art(b""))

    def test_the_real_generic_images_are_in_the_list(self):
        self.assertEqual(len(tc.PLACEHOLDER_BOX_ART_MD5), 4)
        self.assertIn("2aff40fa482c1bfe769264d010733467", tc.PLACEHOLDER_BOX_ART_MD5)


class TestDashboardNames(unittest.TestCase):
    def test_the_two_spellings_become_one_card_with_twitchs_spelling(self):
        known = {BLUE, BLUE_NO_COLON}

        self.assertEqual(_normalize_dashboard_game_name(BLUE_NO_COLON, known_names=known), BLUE)
        self.assertEqual(_normalize_dashboard_game_name(BLUE, known_names=known), BLUE)
        self.assertEqual(
            _dashboard_game_key(BLUE_NO_COLON, known_names=known), _dashboard_game_key(BLUE, known_names=known)
        )
        self.assertEqual(_effective_dashboard_game_names([BLUE_NO_COLON], known_names=[BLUE]), [BLUE])

    def test_the_card_keeps_the_original_capitalisation(self):
        names = _effective_dashboard_game_names(["GODDESS OF VICTORY NIKKE"], known_names=["GODDESS OF VICTORY: NIKKE"])

        self.assertEqual(names, ["GODDESS OF VICTORY: NIKKE"])

    def test_a_polluted_spelling_does_not_win_because_of_its_own_punctuation(self):
        """Regression: '… 1 drop · in 4 days' counted as the most punctuated spelling."""
        names = _effective_dashboard_game_names(["HITMAN World of Assassination 1 drop · in 4 days", "HITMAN World of Assassination"])

        self.assertEqual(names, ["HITMAN World of Assassination"])

    def test_unrelated_games_are_left_alone(self):
        names = ["Dota 2", "Counter-Strike 2", "Honkai: Star Rail", "Genshin Impact"]

        self.assertEqual(_effective_dashboard_game_names(names, known_names=names), sorted(names, key=str.casefold))


class TestArtLoader(unittest.TestCase):
    def _window(self, downloads: dict[str, bytes]) -> MagicMock:
        fake = MagicMock()
        fake._download_url_bytes = lambda url: downloads.get(url, b"")
        return fake

    def test_the_generic_image_is_skipped_in_favour_of_the_next_source(self):
        fake = self._window({"https://t/resolved.jpg": b"PLACEHOLDER", "https://t/campaign.jpg": b"REAL"})
        fake.client.resolve_game_box_art_url.return_value = "https://t/resolved.jpg"
        fake.client.resolve_external_box_art_url.return_value = ""

        with patch("twitch_drop_farmer.ui.is_placeholder_box_art", side_effect=lambda data: data == b"PLACEHOLDER"):
            result = MainWindow._resolve_and_download_box_art_bytes(fake, "https://t/campaign.jpg", "Game", "")

        self.assertEqual(result, b"REAL")

    def test_when_every_source_gives_the_generic_image_nothing_is_returned(self):
        fake = self._window({"https://t/guess.jpg": b"PLACEHOLDER"})
        fake.client.resolve_game_box_art_url.return_value = ""
        fake.client.resolve_external_box_art_url.return_value = ""

        with patch("twitch_drop_farmer.ui.is_placeholder_box_art", side_effect=lambda data: data == b"PLACEHOLDER"):
            result = MainWindow._resolve_and_download_box_art_bytes(fake, "https://t/guess.jpg", "Game", "")

        self.assertEqual(result, b"")  # the card then gets its generated, named placeholder

    def test_a_url_twitch_already_gave_is_fetched_directly_without_any_lookup(self):
        url = official_box_art_url("386821")
        fake = self._window({url: b"REAL"})

        result = MainWindow._resolve_and_download_box_art_bytes(fake, url, "Black Desert", "", prefer_direct_url=True)

        self.assertEqual(result, b"REAL")
        fake.client.resolve_game_box_art_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
