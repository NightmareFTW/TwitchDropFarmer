"""Save the on-screen log to a file that can be attached to a bug report.

Copying a long log out of the window and pasting it into a chat is slow and wasteful, so
the UI has a "Save log" button, which also copies the file's path to the clipboard. The file
gets a short header (version, platform, what is being farmed) and secrets are masked first:
the log should never hold a token, but this is the one place where it leaves the machine, so
it is checked again here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

KEEP_LOG_FILES = 20
LOG_DIR_NAME = "logs"

_MASK = "<redacted>"
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "OAuth abc..." / "Bearer abc..." as sent in an Authorization header.
    (re.compile(r"(?i)\b(oauth|bearer)\s+[A-Za-z0-9_\-.]{16,}"), rf"\1 {_MASK}"),
    # key=value / key: value for the names that carry credentials.
    (
        re.compile(
            r"(?i)\b(auth[-_ ]?token|access[-_ ]?token|refresh[-_ ]?token|oauth[-_ ]?token|"
            r"client[-_ ]?integrity|authorization|device[-_ ]?code|api[-_ ]?key|password)"
            r"(\s*[=:]\s*)[^\s,;'\"]+"
        ),
        rf"\1\2{_MASK}",
    ),
    # A bare Twitch-style token: 30 lowercase letters/digits, with at least one of each.
    (re.compile(r"\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{30}\b"), _MASK),
)


def redact(text: str) -> str:
    """Mask anything in ``text`` that looks like a credential."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def build_report(log_text: str, header_lines: list[str]) -> str:
    """The file body: a short header, a separator and the (redacted) log."""
    header = "\n".join(redact(line) for line in header_lines)
    return f"{header}\n{'-' * 60}\n{redact(log_text).rstrip()}\n"


def save_log(
    log_text: str,
    header_lines: list[str],
    directory: Path,
    *,
    version: str,
    now: datetime | None = None,
    keep: int = KEEP_LOG_FILES,
) -> Path:
    """Write the log to ``directory/logs`` and return the new file's path.

    The file name carries the app version and the time, so a report says which build it
    came from. Only the newest ``keep`` files are kept.
    """
    now = now or datetime.now()
    folder = directory / LOG_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"log-{version}-{now.strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(build_report(log_text, header_lines), encoding="utf-8")
    _prune(folder, keep)
    return path


def _prune(folder: Path, keep: int) -> None:
    files = sorted(folder.glob("log-*.txt"), key=lambda item: item.name, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass

