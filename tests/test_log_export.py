"""The 'Save log' button: secrets are masked, files are named and pruned, the path is copied."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.log_export import build_report, redact, save_log  # noqa: E402
from twitch_drop_farmer.ui import TRANSLATIONS, MainWindow  # noqa: E402

TOKEN = "abcd1234efgh5678ijkl9012mnop34"  # 30 chars, letters and digits: looks like a Twitch token


class TestRedact(unittest.TestCase):
    def test_an_oauth_authorization_value_is_masked(self):
        self.assertNotIn(TOKEN, redact(f"Authorization: OAuth {TOKEN}"))
        self.assertNotIn(TOKEN, redact(f"header OAuth {TOKEN} sent"))

    def test_bearer_values_are_masked(self):
        self.assertNotIn("sekret-value-1234567890", redact("Bearer sekret-value-1234567890"))

    def test_named_credentials_are_masked_with_equals_or_colon(self):
        for line in (
            f"auth-token={TOKEN}",
            f"auth_token: {TOKEN}",
            "Client-Integrity: v4.public.some-long-integrity-value",
            "access_token = secret123",
            "api_key=xyz",
            "password: hunter2",
        ):
            masked = redact(line)
            self.assertIn("<redacted>", masked, line)
            self.assertNotIn("hunter2", masked)
            self.assertNotIn("secret123", masked)
            self.assertNotIn("integrity-value", masked)

    def test_a_bare_token_shaped_string_is_masked(self):
        self.assertEqual(redact(f"token was {TOKEN}."), "token was <redacted>.")

    def test_ordinary_log_lines_are_untouched(self):
        lines = [
            "[17:39:08] sendSpadeEvents OK | canal=jeffhoogland | uid=64691522 | broadcast=322223243994",
            "[17:39:06] Canais: 9 consulta(s) nesta volta, 17 jogo(s) com a última resposta guardada, 23 por verificar.",
            "Sem avanço após heartbeat (152/360 min). | campanha=cc721e50-8eae-4210-9a71-d7d0817fb82e",
            "Sinal CurrentDrop: drop=26dbe8e2-d702-11f1-bb2a-0a58a9feac02 | minutos=152",
            "hash a455deea71bdc9015b78eb49f4acfbce8baa7ccbedd28e549bb025bd0f751930",
            "ALLCAPSTOKENLOOKALIKEWITHOUTDIGITS",
        ]
        for line in lines:
            self.assertEqual(redact(line), line)


class TestSaveLog(unittest.TestCase):
    def test_the_file_name_has_the_version_and_the_time_and_lives_in_a_logs_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_log("line", ["h"], Path(tmp), version="2.2.51", now=datetime(2026, 11, 10, 17, 45, 1))

            self.assertEqual(path, Path(tmp) / "logs" / "log-2.2.51-20261110-174501.txt")
            self.assertTrue(path.is_file())

    def test_the_file_has_the_header_a_separator_and_the_log(self):
        body = build_report("first\nsecond\n", ["Twitch Drop Farmer 2.2.51", "Farming: running"])

        self.assertTrue(body.startswith("Twitch Drop Farmer 2.2.51\nFarming: running\n"))
        self.assertIn("\n" + "-" * 60 + "\n", body)
        self.assertTrue(body.endswith("first\nsecond\n"))

    def test_secrets_never_reach_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_log(f"oops auth-token={TOKEN}", [f"hdr OAuth {TOKEN}"], Path(tmp), version="1")

            self.assertNotIn(TOKEN, path.read_text(encoding="utf-8"))

    def test_only_the_newest_files_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            for minute in range(5):
                save_log("x", [], Path(tmp), version="1", now=datetime(2026, 11, 10, 12, minute, 0), keep=3)

            names = sorted(p.name for p in (Path(tmp) / "logs").glob("log-*.txt"))

            self.assertEqual(len(names), 3)
            self.assertEqual(names[0], "log-1-20261110-120200.txt")  # the two oldest were removed


class TestSaveLogButton(unittest.TestCase):
    def _window(self, log_text: str) -> MagicMock:
        fake = MagicMock()
        fake.log_output.toPlainText.return_value = log_text
        fake._log_report_header.return_value = ["Twitch Drop Farmer test"]
        fake._t = lambda key, **kw: TRANSLATIONS["pt_PT"][key].format(**kw)
        return fake

    def test_it_saves_the_log_and_copies_the_file_path_to_the_clipboard(self):
        fake = self._window("hello log")
        with tempfile.TemporaryDirectory() as tmp, \
                patch("twitch_drop_farmer.ui.CONFIG_DIR", Path(tmp)), \
                patch("twitch_drop_farmer.ui.QApplication") as application:
            MainWindow._do_save_log(fake)

            saved = next((Path(tmp) / "logs").glob("log-*.txt"))
            self.assertIn("hello log", saved.read_text(encoding="utf-8"))
            application.clipboard.return_value.setText.assert_called_once_with(str(saved))
            self.assertIn(str(saved), fake._log.call_args[0][0])

    def test_the_header_names_the_version_and_the_target(self):
        fake = MagicMock()
        fake.timer.isActive.return_value = True
        decision = MagicMock()
        decision.campaign.game_name = "MARVEL SNAP"
        decision.campaign.title = "Knights of Avalon Drops!"
        decision.stream.login = "jeffhoogland"
        fake._current_farm_decision.return_value = decision

        header = "\n".join(MainWindow._log_report_header(fake))

        self.assertIn("Twitch Drop Farmer 2.", header)
        self.assertIn("Farming: running", header)
        self.assertIn("MARVEL SNAP", header)
        self.assertIn("jeffhoogland", header)

    def test_the_button_texts_exist_in_both_languages(self):
        for language in ("pt_PT", "en"):
            for key in ("save_log_button", "save_log_tooltip", "log_saved"):
                self.assertIn(key, TRANSLATIONS[language], f"{language} is missing {key}")


if __name__ == "__main__":
    unittest.main()
