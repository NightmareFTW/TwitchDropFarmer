"""The version shown in the app footer must always match the newest CHANGELOG entry.

Every published change bumps the version (the user needs to tell which build is
running). Forgetting the bump, or bumping only one of the two places, fails here.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer import __version__  # noqa: E402

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


class TestVersionConsistency(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_newest_changelog_entry_matches_the_package_version(self):
        versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(encoding="utf-8"), flags=re.M)
        self.assertTrue(versions, "CHANGELOG.md has no versioned entry")
        self.assertEqual(
            versions[0],
            __version__,
            "Bump __version__ and add a CHANGELOG entry together: the footer shows __version__.",
        )


if __name__ == "__main__":
    unittest.main()
