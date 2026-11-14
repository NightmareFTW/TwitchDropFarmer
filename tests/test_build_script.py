"""The Windows build script must work on a fresh checkout, which is what the release runner has.

On the first manual run of the release workflow, ``Get-ChildItem dist`` stopped the whole build because
``dist\\`` did not exist yet (it always existed on the author's machine). The script cannot be run here, so
this checks the one assumption that broke it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build_exe.ps1"


class TestBuildScriptOnAFreshCheckout(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = SCRIPT.read_text(encoding="utf-8").splitlines()

    def test_every_listing_of_the_dist_folder_is_guarded_by_a_check_that_it_exists(self):
        listings = [i for i, line in enumerate(self.lines) if re.search(r"Get-ChildItem\s+-Path\s+\$distDir", line)]
        self.assertTrue(listings, "the script no longer lists dist (update this test if that was on purpose)")
        for index in listings:
            guard = next((line for line in reversed(self.lines[:index]) if line.strip() and not line.strip().startswith("#")), "")
            self.assertRegex(guard, r"if\s*\(\s*Test-Path\s+\$distDir\s*\)", f"line {index + 1} lists dist without checking it exists")

    def test_the_script_stops_on_errors_so_a_failed_step_is_not_hidden(self):
        self.assertIn('$ErrorActionPreference = "Stop"', "\n".join(self.lines))


if __name__ == "__main__":
    unittest.main()
