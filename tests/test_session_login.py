"""Importing, keeping and restoring a Twitch session (client side, no window, no network)."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer import twitch_client as tc  # noqa: E402

TOKEN = "t" * 30


def _response(status: int = 200, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload or {}
    return response


def _cookie_list(token: str = TOKEN) -> list[dict]:
    return [
        {"name": "auth-token", "value": token, "domain": ".twitch.tv"},
        {"name": "unique_id", "value": "abc123", "domain": ".twitch.tv"},
    ]


class _ClientCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        for name, value in (
            ("CONFIG_DIR", base),
            ("COOKIE_FILE", base / "cookies.json"),
            ("SESSION_FILE", base / "session.json"),
            ("CAMPAIGN_CACHE_FILE", base / "campaign_cache.json"),
        ):
            patcher = patch.object(tc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = tc.TwitchClient()
        self.addCleanup(self.client.segment_watcher.stop)
        self.session_file = base / "session.json"

    def twitch_says(self, status: int = 200, login: str = "someone", user_id: str = "42") -> None:
        self.client.session.get = MagicMock(return_value=_response(status, {"login": login, "user_id": user_id}))


class TestImport(_ClientCase):
    def test_it_takes_back_what_this_app_exports(self):
        exported = json.dumps({"cookies": _cookie_list(), "user_id": "42", "login_name": "someone",
                               "device_id": "dev", "session_id": "sess"})

        self.client.import_session_json(exported)

        self.assertEqual(self.client.login_state.oauth_token, TOKEN)
        self.assertEqual(self.client.login_state.login_name, "someone")
        self.assertEqual(self.client.session.headers["Authorization"], f"OAuth {TOKEN}")
        self.assertEqual(self.client.device_id, "dev")

    def test_it_also_takes_the_plain_cookie_list_a_browser_extension_exports(self):
        self.client.import_session_json(json.dumps(_cookie_list()))

        self.assertEqual(self.client.login_state.oauth_token, TOKEN)

    def test_a_json_without_a_device_id_does_not_wipe_the_one_the_app_has(self):
        self.client.device_id = "keep-me"

        self.client.import_session_json(json.dumps(_cookie_list()))

        self.assertEqual(self.client.device_id, "keep-me")

    def test_anything_that_is_not_a_session_is_a_clear_value_error(self):
        for bad in ("not json", "42", '"text"', '{"cookies": "x"}', '{"cookies": [{"value": "v"}]}', "[1, 2]", "null"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    self.client.import_session_json(bad)

    def test_a_token_that_twitch_has_not_confirmed_is_replaced_by_the_imported_one(self):
        self.client.login_state.oauth_token = "o" * 30
        self.client.login_state.token_valid = False

        self.client.import_session_json(json.dumps(_cookie_list()))

        self.assertEqual(self.client.login_state.oauth_token, TOKEN)
        self.assertFalse(self.client.login_state.token_valid)

    def test_a_confirmed_token_is_kept_when_the_import_has_no_new_login(self):
        self.client.login_state.oauth_token = "o" * 30
        self.client.login_state.token_valid = True

        self.client.import_session_json(json.dumps([{"name": "unique_id", "value": "x", "domain": ".twitch.tv"}]))

        self.assertEqual(self.client.login_state.oauth_token, "o" * 30)
        self.assertTrue(self.client.login_state.token_valid)

    def test_a_different_token_means_the_old_confirmation_no_longer_applies(self):
        self.client.login_state.oauth_token = "o" * 30
        self.client.login_state.token_valid = False
        self.client.import_session_json(json.dumps(_cookie_list("n" * 30)))

        self.assertEqual(self.client.login_state.oauth_token, "n" * 30)
        self.assertFalse(self.client.login_state.logged_in)


class TestKeptSession(_ClientCase):
    def test_nothing_is_written_until_asked(self):
        self.client.login_state.oauth_token = TOKEN

        self.assertFalse(self.client.has_session_copy())
        self.assertFalse(self.session_file.exists())

    def test_saving_keeps_the_session_privately_and_leaves_no_temp_file(self):
        self.client.import_session_json(json.dumps(_cookie_list()))

        self.client.save_session_copy()

        self.assertTrue(self.client.has_session_copy())
        self.assertEqual(self.client.session_copy_path(), self.session_file)
        self.assertEqual([p.name for p in self.session_file.parent.glob("*.tmp")], [])
        self.assertIn(TOKEN, self.session_file.read_text(encoding="utf-8"))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.session_file.stat().st_mode), 0o600)

    def test_forgetting_deletes_it_and_says_whether_there_was_one(self):
        self.client.import_session_json(json.dumps(_cookie_list()))
        self.client.save_session_copy()

        self.assertTrue(self.client.forget_session_copy())
        self.assertFalse(self.session_file.exists())
        self.assertFalse(self.client.forget_session_copy())


class TestRestoreInThreeSteps(_ClientCase):
    def keep_a_session(self, token: str = TOKEN) -> None:
        self.client.import_session_json(json.dumps(_cookie_list(token)))
        self.client.save_session_copy()

    def forget_everything_in_memory(self) -> None:
        self.client.login_state.oauth_token = ""
        self.client.login_state.token_valid = False
        self.client.login_state.login_name = ""
        self.client.session.cookies.clear()
        self.client.session.headers.pop("Authorization", None)

    def test_it_reads_imports_and_validates_in_that_order_and_ends_signed_in(self):
        self.keep_a_session()
        self.forget_everything_in_memory()
        self.twitch_says(login="someone")
        steps: list[tuple[int, int]] = []

        state = self.client.login_from_session_copy(progress=lambda n, total: steps.append((n, total)))

        self.assertEqual(steps, [(1, 3), (2, 3), (3, 3)])
        self.assertTrue(state.logged_in)
        self.assertEqual(state.login_name, "someone")
        self.assertEqual(state.oauth_token, TOKEN)

    def test_it_works_over_a_stale_token_the_app_still_had(self):
        self.keep_a_session()
        self.forget_everything_in_memory()
        self.client.login_state.oauth_token = "x" * 30  # an old one Twitch no longer accepts
        self.twitch_says()

        state = self.client.login_from_session_copy()

        self.assertEqual(state.oauth_token, TOKEN)
        self.assertTrue(state.logged_in)

    def test_the_kept_copy_is_refreshed_once_the_session_is_confirmed(self):
        self.keep_a_session()
        stale = self.session_file.read_text(encoding="utf-8")
        self.forget_everything_in_memory()
        self.twitch_says(login="someone", user_id="42")

        self.client.login_from_session_copy()

        self.assertIn('"login_name": "someone"', self.session_file.read_text(encoding="utf-8"))
        self.assertNotEqual(self.session_file.read_text(encoding="utf-8"), stale)

    def test_a_session_twitch_rejects_is_reported_and_the_kept_copy_is_left_as_it_was(self):
        self.keep_a_session()
        before = self.session_file.read_text(encoding="utf-8")
        self.forget_everything_in_memory()
        self.twitch_says(status=401)

        with self.assertRaises(ValueError):
            self.client.login_from_session_copy()

        self.assertFalse(self.client.login_state.logged_in)
        self.assertEqual(self.session_file.read_text(encoding="utf-8"), before)

    def test_without_a_kept_session_it_says_so(self):
        steps: list[int] = []

        with self.assertRaises(ValueError):
            self.client.login_from_session_copy(progress=lambda n, _t: steps.append(n))

        self.assertEqual(steps, [1])

    def test_a_damaged_copy_is_a_value_error_not_a_crash(self):
        self.session_file.write_text("{ not json", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.client.login_from_session_copy()


if __name__ == "__main__":
    unittest.main()
