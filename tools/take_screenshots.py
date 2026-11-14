"""Generate the README screenshots (docs/images/) from FICTIONAL demo data.

    python tools/take_screenshots.py

Writes the gallery in Portuguese (docs/images/) and in English (docs/images/en/): the four main views, the
sign-in window and the three themes.

Nothing real can end up in a screenshot:

* the app runs against a throw-away home folder, so your own config, session and cookies are never read;
* every network request is refused, so nothing is fetched and nothing is sent;
* the games, drops and channels below are made up.

Needs a display (or ``QT_QPA_PLATFORM=offscreen``).
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# A throw-away home, set BEFORE the package is imported (its data folder is computed from the home folder).
_HOME = tempfile.TemporaryDirectory()
os.environ["HOME"] = _HOME.name
os.environ["USERPROFILE"] = _HOME.name
os.environ.setdefault("QT_SCALE_FACTOR", "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import requests  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "images"
WINDOW_W, WINDOW_H = 1280, 800
UTC = timezone.utc

# (game, campaign title, required minutes, progress minutes, what the card should say)
DEMO_GAMES = [
    ("Starfall Frontier", "Founders Week", 360, 142, "farming"),
    ("Neon Drift Racing", "Season 4 Rewards", 240, 0, "ready"),
    ("Kingdom of Ember", "Anniversary Drops", 180, 180, "done"),
    ("Pixel Ranch", "Harvest Festival", 120, 35, "ready"),
    ("Orbital Tactics", "Beta Weekend", 300, 0, "no_stream"),
    ("Misty Hollow", "Spooky Season", 90, 12, "ready"),
]


def build_demo(window, *, farm_running: bool):
    """Put the demo campaigns into the window as if the farm had just polled Twitch."""
    from twitch_drop_farmer.farmer import FarmSnapshot
    from twitch_drop_farmer.models import DropCampaign, FarmDecision, StreamCandidate

    now = datetime.now(UTC)
    campaigns, decisions = [], []
    for index, (game, title, required, progress, kind) in enumerate(DEMO_GAMES):
        campaign = DropCampaign(
            id=f"demo-{index}", game_name=game, title=title, status="ACTIVE",
            starts_at=now - timedelta(days=2), ends_at=now + timedelta(days=3 + index * 2),
            required_minutes=required, progress_minutes=progress, has_watchable_drops=True,
            all_drops_claimed=(kind == "done"), next_drop_name="Founder's Emblem" if kind == "farming" else "Supply Crate",
            next_drop_required_minutes=required, next_drop_remaining_minutes=required - progress,
            drops=[
                {"id": f"d{index}a", "name": "Supply Crate", "required_minutes": required // 2,
                 "current_minutes": min(progress, required // 2), "claimed": progress >= required // 2 and kind == "done"},
                {"id": f"d{index}b", "name": "Founder's Emblem" if kind == "farming" else "Legendary Skin",
                 "required_minutes": required, "current_minutes": progress, "claimed": kind == "done"},
            ],
        )
        campaigns.append(campaign)
        if kind == "done":
            decisions.append(FarmDecision(campaign=campaign, stream=None, reason_code="campaign_completed"))
        elif kind == "no_stream":
            decisions.append(FarmDecision(campaign=campaign, stream=None, reason_code="no_valid_stream"))
        else:
            stream = StreamCandidate(
                login=f"demo_channel_{index}", display_name=f"DemoChannel{index}", game_name=game,
                viewer_count=1200 - index * 150, drops_enabled=True, channel_id=str(1000 + index),
            )
            decisions.append(FarmDecision(campaign=campaign, stream=stream, reason_code="stream_selected"))

    snapshot = FarmSnapshot(
        campaigns=campaigns, decisions=decisions,
        available_games=[game for game, *_ in DEMO_GAMES], available_channels=[],
    )
    window.config.whitelist_games = [game for game, *_ in DEMO_GAMES]
    window.games_whitelist_list.set_entries(
        [window_filter_entry(game) for game, *_ in DEMO_GAMES], window.config.whitelist_games, ""
    )
    window.latest_snapshot = snapshot
    window._forced_farm_campaign_id = campaigns[0].id
    for campaign in campaigns:
        # The app's own generated cover (initials on a colour), shown as if it had been downloaded: nothing is fetched.
        cover = window._generated_game_placeholder(campaign.game_name)
        campaign.game_box_art_url = f"demo://cover/{campaign.id}"
        window._thumb_cache[campaign.game_box_art_url] = cover
    if farm_running:
        window.timer.start(600_000)
        window._set_farming_controls(True)
    window._apply_snapshot(snapshot)
    window._refresh_farming_now()


def window_filter_entry(game: str):
    from twitch_drop_farmer.ui import FilterEntry

    return FilterEntry(key=game, label=game)


LANGUAGES = (("pt_PT", OUT_DIR), ("en", OUT_DIR / "en"))
THEMES = (  # (the theme's key in the app, its label in each language)
    ("twitch", {"pt_PT": "Twitch", "en": "Twitch"}),
    ("black_red", {"pt_PT": "Preto / Vermelho", "en": "Black / Red"}),
    ("light", {"pt_PT": "Claro", "en": "Light"}),
)


def settle(app, rounds: int = 6) -> None:
    """Let the window finish what it was asked to do, including the widgets it replaced: those are deleted with
    deleteLater(), which only the real event loop performs, so a card from the previous refresh would stay on screen."""
    from PySide6.QtCore import QCoreApplication, QEvent

    for _ in range(rounds):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def capture_language(window, app, language: str, out_dir: Path) -> None:
    """The whole gallery in one language: the four main views, the sign-in window and the three themes."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

    out_dir.mkdir(parents=True, exist_ok=True)
    window.language_picker.setCurrentIndex(window.language_picker.findData(language))
    window._retranslate_ui()
    window._apply_theme("twitch")
    build_demo(window, farm_running=True)
    settle(app)

    def save(pixmap, name: str) -> None:
        path = out_dir / name
        pixmap.save(str(path), "PNG")
        print(f"  Saved: {path}")

    def views(name: str, left: int, right: int) -> None:
        window.tabs_left.setCurrentIndex(left)
        window.tabs_right.setCurrentIndex(right)
        settle(app)
        window.log_output.clear()  # the offline run logs connection errors: not for a screenshot
        settle(app, 2)
        save(window.grab(), name)

    views("ui-dashboard.png", 0, 0)  # Dashboard + Farming now
    views("ui-farming.png", 2, 0)  # Filters + Farming now
    views("ui-campaigns.png", 1, 1)  # Account + Campaigns
    views("ui-settings.png", 3, 1)  # Settings + Campaigns

    # The sign-in window, as it opens for someone who is not signed in yet (nothing is typed in it).
    from twitch_drop_farmer.login_dialog import LoginDialog

    dialog = LoginDialog(window, window)
    dialog.show()
    settle(app)
    save(dialog.grab(), "ui-login.png")
    dialog.close()
    dialog.deleteLater()
    settle(app, 2)

    # The three themes side by side: the dashboard of each, shrunk to half size, with its name above.
    window.tabs_left.setCurrentIndex(0)
    window.tabs_right.setCurrentIndex(0)
    cell_w, cell_h, gap, label_h = 640, 400, 12, 32
    canvas = QPixmap(len(THEMES) * cell_w + (len(THEMES) - 1) * gap, cell_h + label_h)
    canvas.fill(QColor("#0e0e10"))
    painter = QPainter(canvas)
    font = QFont(window.font())
    font.setBold(True)
    font.setPixelSize(16)
    painter.setFont(font)
    painter.setPen(QColor("#efeff1"))
    for index, (key, labels) in enumerate(THEMES):
        window._apply_theme(key)
        settle(app)
        window.log_output.clear()
        shot = window.grab().scaled(cell_w, cell_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        x = index * (cell_w + gap)
        painter.drawPixmap(x, label_h, shot)
        painter.drawText(QRect(x, 0, cell_w, label_h), Qt.AlignmentFlag.AlignCenter, labels[language])
    painter.end()
    window._apply_theme("twitch")
    save(canvas, "ui-themes.png")


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    with patch("requests.Session.request", side_effect=requests.ConnectionError("screenshots run offline")):
        from twitch_drop_farmer.ui import MainWindow

        window = MainWindow()
        window.resize(WINDOW_W, WINDOW_H)
        window.show()
        settle(app)
        for language, out_dir in LANGUAGES:
            capture_language(window, app, language, out_dir)

        window.timer.stop()
        window.client.segment_watcher.stop()
        window.executor.shutdown(wait=False)
        window.close()
    app.quit()
    print("\nDone. Screenshots saved to docs/images/ (Portuguese) and docs/images/en/ (English)")


if __name__ == "__main__":
    run()
