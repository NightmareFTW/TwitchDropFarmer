"""The license, the notices of the libraries in the package, and the package carrying both."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class TestLicense(unittest.TestCase):
    def test_it_is_the_polyform_noncommercial_license_with_a_required_notice_first(self):
        text = read("LICENSE")

        self.assertTrue(text.startswith("Required Notice: Copyright (c) "), "the copyright line must come first")
        self.assertIn("# PolyForm Noncommercial License 1.0.0", text)
        self.assertIn("https://polyformproject.org/licenses/noncommercial/1.0.0", text)

    def test_the_text_of_the_license_itself_was_not_altered(self):
        """The sentences that matter, word for word: no commercial use, personal use, no warranty."""
        text = re.sub(r"\s+", " ", read("LICENSE"))
        for sentence in (
            "Any noncommercial purpose is a permitted purpose.",
            "Personal use for research, experiment, and testing for the benefit of public knowledge, personal study, "
            "private entertainment, hobby projects, amateur pursuits, or religious observance, without any anticipated "
            "commercial application, is use for a permitted purpose.",
            "the software comes as is, without any warranty or condition",
            "within 32 days of receiving notice",
        ):
            self.assertIn(sentence, text)

    def test_the_old_permissive_license_is_gone(self):
        text = read("LICENSE")

        self.assertNotIn("Permission is hereby granted, free of charge", text)
        self.assertNotIn("MIT License", text)

    def test_the_readmes_say_the_same_thing_in_both_languages(self):
        for name, needles in (
            ("README.md", ("PolyForm Noncommercial 1.0.0", "não para fins comerciais", "THIRD_PARTY_NOTICES.md", "MIT")),
            ("README.en.md", ("PolyForm Noncommercial 1.0.0", "not for commercial purposes", "THIRD_PARTY_NOTICES.md", "MIT")),
        ):
            text = read(name)
            for needle in needles:
                self.assertIn(needle, text, (name, needle))
        self.assertNotIn("Licença MIT. Ver", read("README.md"))
        self.assertNotIn("MIT License. See", read("README.en.md"))


class TestThirdPartyNotices(unittest.TestCase):
    def test_every_library_we_require_is_listed(self):
        """So the list cannot go stale when a requirement is added."""
        notices = read("THIRD_PARTY_NOTICES.md").lower()
        names = [re.split(r"[<>=!~\[ ]", line.strip(), maxsplit=1)[0] for line in read("requirements.txt").splitlines()
                 if line.strip() and not line.startswith("#")]

        self.assertTrue(names)
        for name in names:
            self.assertIn(name.lower(), notices, f"{name} is in requirements.txt but not in THIRD_PARTY_NOTICES.md")

    def test_qt_is_said_to_be_used_under_the_lgpl_and_replaceable(self):
        notices = read("THIRD_PARTY_NOTICES.md")

        self.assertIn("LGPL-3.0", notices)
        self.assertIn("replace them", notices)
        self.assertIn("https://code.qt.io", notices)


class TestThePackageCarriesTheLicense(unittest.TestCase):
    def test_the_build_script_copies_both_files_into_the_bundle(self):
        script = read("build_exe.ps1")

        self.assertRegex(script, r'Copy-Item\s+\(Join-Path \$projectRoot "LICENSE"\)\s+\(Join-Path \$bundleDir "LICENSE\.txt"\)')
        self.assertRegex(script, r'Copy-Item\s+\(Join-Path \$projectRoot "THIRD_PARTY_NOTICES\.md"\)\s+\(Join-Path \$bundleDir "THIRD_PARTY_NOTICES\.md"\)')

    def test_the_release_workflow_refuses_a_zip_without_them(self):
        workflow = read(".github/workflows/release.yml")

        self.assertIn('"TwitchDropFarmer/LICENSE.txt"', workflow)
        self.assertIn('"TwitchDropFarmer/THIRD_PARTY_NOTICES.md"', workflow)

    def test_the_build_script_copies_them_after_the_bundle_exists(self):
        script = read("build_exe.ps1")

        self.assertGreater(script.index('"LICENSE.txt"'), script.index("Expected build output folder was not created"))


if __name__ == "__main__":
    unittest.main()
