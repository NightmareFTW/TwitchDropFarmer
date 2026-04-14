from __future__ import annotations

import sys
from pathlib import Path


if __package__ in {None, ""}:
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from twitch_drop_farmer.ui import run
else:
    from .ui import run

if __name__ == "__main__":
    run()
