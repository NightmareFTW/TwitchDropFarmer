"""The app's ``--smoke-test`` mode: what the release workflow runs on the packaged .exe before publishing it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from twitch_drop_farmer import __main__ as entry  # noqa: E402
from twitch_drop_farmer import __version__  # noqa: E402


class TestSmokeTestRun(unittest.TestCase):
    def run_app(self, *flags: str) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.json"
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), QT_QPA_PLATFORM="offscreen",
                       HOME=tmp, USERPROFILE=tmp)
            process = subprocess.run(
                [sys.executable, "-m", "twitch_drop_farmer", *flags, str(result)],
                env=env, capture_output=True, text=True, timeout=180, cwd=str(ROOT),
            )
            report = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
            return process.returncode, report

    def test_a_healthy_app_passes_and_says_which_version_it_is(self):
        code, report = self.run_app("--smoke-test")

        self.assertEqual(code, 0, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual([step["step"] for step in report["steps"]],
                         ["import the app", "resources are in the bundle", "the main window builds"])
        self.assertTrue(all(step["ok"] for step in report["steps"]))
        self.assertIn(__version__, report["steps"][0]["detail"])

    def test_it_never_touches_the_real_data_folder(self):
        """It runs on a throw-away home: nothing of the person running it is read or written."""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HOME": tmp, "USERPROFILE": tmp}):
            before = os.environ["HOME"]
            ok, steps = entry._smoke_checks()
            after = os.environ["HOME"]

        self.assertTrue(ok, steps)
        self.assertNotEqual(before, after)  # the home folder was swapped for another one


class TestSmokeTestFailures(unittest.TestCase):
    def test_a_bundle_without_its_icons_fails_on_that_step_and_goes_no_further(self):
        from twitch_drop_farmer import ui

        with tempfile.TemporaryDirectory() as empty, patch.object(ui, "_ASSETS_DIR", Path(empty)), \
                patch.dict(os.environ, dict(os.environ)):
            ok, steps = entry._smoke_checks()

        self.assertFalse(ok)
        self.assertEqual([(s["step"], s["ok"]) for s in steps],
                         [("import the app", True), ("resources are in the bundle", False)])
        self.assertIn("icon.ico", steps[-1]["detail"])

    def test_a_missing_module_fails_the_first_step(self):
        package = sys.modules["twitch_drop_farmer"]
        saved = package.__dict__.pop("ui", None)  # as if the bundle had no ui module at all
        try:
            with patch.dict(sys.modules, {"twitch_drop_farmer.ui": None}), patch.dict(os.environ, dict(os.environ)):
                ok, steps = entry._smoke_checks()
        finally:
            if saved is not None:
                package.ui = saved

        self.assertFalse(ok)
        self.assertEqual(len(steps), 1)
        self.assertFalse(steps[0]["ok"])

    def test_the_exit_code_is_not_zero_when_a_step_fails_and_zero_when_all_pass(self):
        with patch.object(entry, "_smoke_report"):
            with patch.object(entry, "_smoke_checks", return_value=(False, [{"step": "x", "ok": False, "detail": "boom"}])):
                self.assertEqual(entry._smoke_test(["--smoke-test"]), 1)
            with patch.object(entry, "_smoke_checks", return_value=(True, [])):
                self.assertEqual(entry._smoke_test(["--smoke-test"]), 0)

    def test_the_report_goes_to_the_file_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.json"
            with patch.object(entry, "_smoke_checks", return_value=(True, [{"step": "x", "ok": True, "detail": ""}])):
                entry._smoke_test(["--smoke-test", str(target)])

            self.assertTrue(json.loads(target.read_text(encoding="utf-8"))["ok"])


class TestNormalStartIsUnchanged(unittest.TestCase):
    def test_without_the_flag_the_app_starts_normally(self):
        with patch.object(sys, "argv", ["twitch-drop-farmer"]), patch.object(entry, "_install_hooks"), \
                patch("twitch_drop_farmer.ui.run") as run, patch.object(entry, "_smoke_test") as smoke:
            self.assertEqual(entry.main(), 0)

        run.assert_called_once()
        smoke.assert_not_called()

    def test_the_flag_runs_the_smoke_test_and_not_the_app(self):
        with patch.object(sys, "argv", ["twitch-drop-farmer", "--smoke-test", "out.json"]), \
                patch.object(entry, "_smoke_test", return_value=0) as smoke, patch("twitch_drop_farmer.ui.run") as run:
            entry.main()

        smoke.assert_called_once()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
