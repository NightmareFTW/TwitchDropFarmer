"""Generate the README screenshots (docs/images/) from FICTIONAL demo data.

    python tools/take_screenshots.py

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


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    with patch("requests.Session.request", side_effect=requests.ConnectionError("screenshots run offline")):
        from twitch_drop_farmer.ui import MainWindow

        window = MainWindow()
        window.resize(WINDOW_W, WINDOW_H)
        window.show()
        app.processEvents()
        build_demo(window, farm_running=True)
        window.log_output.clear()
        for _ in range(5):
            app.processEvents()

        def shot(name: str, left: int, right: int) -> None:
            window.tabs_left.setCurrentIndex(left)
            window.tabs_right.setCurrentIndex(right)
            for _ in range(5):
                app.processEvents()
            window.log_output.clear()  # the offline run logs connection errors: not for a screenshot
            app.processEvents()
            path = OUT_DIR / name
            window.grab().save(str(path), "PNG")
            print(f"  Saved: {path}")

        shot("ui-dashboard.png", 0, 0)  # Dashboard + Farming now
        shot("ui-farming.png", 2, 0)  # Filters + Farming now
        shot("ui-campaigns.png", 1, 1)  # Account + Campaigns
        shot("ui-settings.png", 3, 1)  # Settings + Campaigns

        window.timer.stop()
        window.client.segment_watcher.stop()
        window.executor.shutdown(wait=False)
        window.close()
    app.quit()
    print("\nDone. Screenshots saved to docs/images/")


if __name__ == "__main__":
    run()
