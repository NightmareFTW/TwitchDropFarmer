"""Nothing personal ends up in the repository: no e-mail addresses, home-folder paths, tokens or account ids.

The repository is public. A real Twitch login, user id, e-mail or Windows user name in a test, a doc or a
sample log would be published with it, so every tracked text file is scanned.

Account-specific terms (your own Twitch login, your name...) are deliberately NOT written here, since that would
publish them too. Put them, one per line, in ``tests/.private_terms`` (ignored by git); when that file exists the
scan also fails on any of them.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_TERMS = Path(__file__).resolve().parent / ".private_terms"

# E-mail addresses that are not personal: the GitHub no-reply identities, reserved example domains
# and the SSH form of a git remote.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
ALLOWED_EMAIL_DOMAINS = {
    "users.noreply.github.com", "noreply.github.com", "github.com",
    "example.com", "example.org", "example.net", "localhost.localdomain",
}
# C:\Users\<name>\... : a placeholder such as <utilizador> or %USERPROFILE% is fine, a real name is not.
WINDOWS_HOME = re.compile(r"[A-Za-z]:\\+Users\\+([^\\<>%$\s\"'{}()]+)")
ALLOWED_WINDOWS_NAMES = {"public", "default", "all", "user", "username", "utilizador", "you", "name"}
POSIX_HOME = re.compile(r"(?<![\w.])/(?:home|Users)/([A-Za-z0-9._-]+)")
ALLOWED_POSIX_NAMES = {"user", "runner", "you", "name", "username", "utilizador"}
# A Twitch web token is 30 lowercase letters and digits; a made-up one is a single repeated character.
TOKEN_ASSIGNED = re.compile(r"""(?:auth-token|oauth[_ -]?token|access_token|Authorization)["']?\s*[:=]\s*["']?(?:OAuth |Bearer )?([a-z0-9]{30})\b""")
TOKEN_OAUTH_PREFIX = re.compile(r"\boauth:([a-z0-9]{30})\b")
USER_ID = re.compile(r"\b(?:uid|user[_ ]?id)\s*[=:]\s*(\d{7,})")
FAKE_USER_IDS = {"12345678", "1234567", "123456789", "00000000", "99999999"}
TEXT_SUFFIXES = {
    ".py", ".pyw", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".ps1", ".cfg", ".ini", ".html", ".css",
    ".gitignore", ".gitattributes", "",
}


def _is_fake_token(value: str) -> bool:
    return len(set(value)) <= 2  # "k" * 30, "ab" * 15


def scan_text(text: str) -> list[str]:
    """What looks personal in ``text`` (descriptions only; the values are not repeated in full)."""
    found: list[str] = []
    for match in EMAIL.finditer(text):
        if match.group(1).lower() not in ALLOWED_EMAIL_DOMAINS:
            found.append(f"e-mail address ({match.group(0)[:3]}...@{match.group(1)})")
    for match in WINDOWS_HOME.finditer(text):
        if match.group(1).lower() not in ALLOWED_WINDOWS_NAMES:
            found.append(f"Windows home folder of a real user name ({match.group(0)[:12]}...)")
    for match in POSIX_HOME.finditer(text):
        if match.group(1).lower() not in ALLOWED_POSIX_NAMES:
            found.append(f"home folder of a real user name ({match.group(0)[:9]}...)")
    for pattern in (TOKEN_ASSIGNED, TOKEN_OAUTH_PREFIX):
        for match in pattern.finditer(text):
            if not _is_fake_token(match.group(1)):
                found.append("something shaped like a Twitch token")
    for match in USER_ID.finditer(text):
        if match.group(1) not in FAKE_USER_IDS:
            found.append(f"a Twitch user id ({match.group(1)[:2]}...)")
    for term in _private_terms():
        if term in text.lower():
            found.append("one of the terms in tests/.private_terms")
    return found


def _private_terms() -> list[str]:
    try:
        lines = PRIVATE_TERMS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip().lower() for line in lines if line.strip() and not line.startswith("#")]


def tracked_files(root: Path) -> list[Path] | None:
    """The files git tracks (None when this is not a git checkout, e.g. an exported archive)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [root / name for name in out.decode("utf-8", "replace").split("\0") if name]


def scan_files(paths: list[Path], *, skip: set[Path] = frozenset()) -> dict[str, list[str]]:
    problems: dict[str, list[str]] = {}
    for path in paths:
        if path in skip or path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = scan_text(text)
        if found:
            problems[str(path)] = sorted(set(found))
    return problems


class TestScannerRecognisesPersonalData(unittest.TestCase):
    """The scanner itself, on made-up samples: it must flag the real thing and let the placeholders through."""

    def test_flags_an_email_address(self):
        self.assertTrue(scan_text("contact: someone" + "@" + "mail-provider.com"))

    def test_lets_the_noreply_and_example_addresses_through(self):
        for address in ("x@users.noreply.github.com", "me@example.com", "git@github.com:o/r.git"):
            self.assertEqual(scan_text(address), [], address)

    def test_flags_a_windows_home_folder_with_a_real_name(self):
        self.assertTrue(scan_text("C:\\Users\\SomeRealName\\Desktop\\x"))
        self.assertTrue(scan_text("c:\\\\Users\\\\SomeRealName\\\\AppData"))

    def test_lets_a_placeholder_home_folder_through(self):
        for sample in ("C:\\Users\\<utilizador>\\.twitch-drop-farmer", "C:\\Users\\%USERNAME%\\x", "C:\\Users\\Public\\x"):
            self.assertEqual(scan_text(sample), [], sample)

    def test_flags_a_unix_home_folder_with_a_real_name(self):
        self.assertTrue(scan_text("/home/someone/projects"))
        self.assertTrue(scan_text("/Users/someone/projects"))
        self.assertEqual(scan_text("/home/user/TwitchDropFarmer"), [])  # the generic CI/sandbox account

    def test_flags_a_token_shaped_value_but_not_a_made_up_one(self):
        real_looking = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5"
        self.assertEqual(len(real_looking), 30)
        self.assertTrue(scan_text(f'auth-token = "{real_looking}"'))
        self.assertTrue(scan_text(f"oauth:{real_looking}"))
        self.assertEqual(scan_text('auth-token = "' + "k" * 30 + '"'), [])

    def test_flags_a_real_user_id_but_not_the_obvious_sample(self):
        self.assertTrue(scan_text("sendSpadeEvents OK | canal=x | uid=48151623"))
        self.assertEqual(scan_text("sendSpadeEvents OK | canal=x | uid=12345678"), [])

    def test_flags_a_term_from_the_private_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            terms = Path(tmp) / ".private_terms"
            terms.write_text("# comment\nsecretlogin\n", encoding="utf-8")
            with unittest.mock.patch(f"{__name__}.PRIVATE_TERMS", terms):
                self.assertTrue(scan_text("hello SecretLogin"))
                self.assertEqual(scan_text("hello world"), [])

    def test_scan_files_names_the_file_and_skips_what_is_not_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad, good, image = Path(tmp) / "bad.md", Path(tmp) / "good.md", Path(tmp) / "pic.png"
            bad.write_text("write to someone" + "@" + "mail-provider.com", encoding="utf-8")
            good.write_text("nothing here", encoding="utf-8")
            image.write_bytes(b"\x89PNG someone" + b"@" + b"mail-provider.com")

            problems = scan_files([bad, good, image])

            self.assertEqual(list(problems), [str(bad)])


class TestTheRepositoryHasNoPersonalData(unittest.TestCase):
    def test_no_tracked_text_file_has_any(self):
        files = tracked_files(ROOT)
        if files is None:
            self.skipTest("not a git checkout")

        problems = scan_files(files, skip={Path(__file__).resolve()})

        self.assertEqual(
            problems, {}, "personal data in tracked files (values are not shown; run the scan on the file): " + str(problems)
        )

    def test_the_ignore_rules_keep_the_account_files_out(self):
        rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for needed in ("session.json", "config.json", "cookies.json", ".env", "tests/.private_terms"):
            self.assertIn(needed, rules, f".gitignore should list {needed}")


if __name__ == "__main__":
    unittest.main()
