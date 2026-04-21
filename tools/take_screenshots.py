"""
take_screenshots.py – Gera screenshots da UI do TwitchDropFarmer em estado vazio.

Uso:
    cd <raiz do repo>
    python tools/take_screenshots.py

Os screenshots são gravados em docs/images/:
    ui-dashboard.png   – tab Dashboard (esquerda) + tab Farming now (direita)
    ui-farming.png     – tab Filtros (esquerda) + tab Farming now (direita)
    ui-campaigns.png   – tab Conta (esquerda) + tab Campaigns (direita)
    ui-settings.png    – tab Definições (esquerda) + tab Campaigns (direita)

Não é necessário estar autenticado — todos os screenshots mostram estado vazio.
"""

import sys
import os
from pathlib import Path

# Garante que o src/ está no PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer

os.environ.setdefault("QT_SCALE_FACTOR", "1")

OUT_DIR = REPO_ROOT / "docs" / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_W = 1280
WINDOW_H = 800


def save_shot(window, filename: str) -> None:
    pixmap = window.grab()
    path = str(OUT_DIR / filename)
    pixmap.save(path, "PNG")
    print(f"  Saved: {path}")


def run() -> None:
    app = QApplication(sys.argv)

    from twitch_drop_farmer.ui import MainWindow

    window = MainWindow()
    window.resize(WINDOW_W, WINDOW_H)
    window.show()
    app.processEvents()

    # ── Screenshot 1: Dashboard (novo) ─────────────────────────────────────
    # Left = tab 0 (Dashboard), Right = tab 0 (Farming now)
    window.tabs_left.setCurrentIndex(0)
    window.tabs_right.setCurrentIndex(0)
    app.processEvents()
    save_shot(window, "ui-dashboard.png")

    # ── Screenshot 2: Farming now ───────────────────────────────────────────
    # Left = tab 2 (Filtros), Right = tab 0 (Farming now)
    window.tabs_left.setCurrentIndex(2)
    window.tabs_right.setCurrentIndex(0)
    app.processEvents()
    save_shot(window, "ui-farming.png")

    # ── Screenshot 3: Campanhas ─────────────────────────────────────────────
    # Left = tab 1 (Conta), Right = tab 1 (Campanhas)
    window.tabs_left.setCurrentIndex(1)
    window.tabs_right.setCurrentIndex(1)
    app.processEvents()
    save_shot(window, "ui-campaigns.png")

    # ── Screenshot 4: Definições ────────────────────────────────────────────
    # Left = tab 3 (Definições), Right = tab 1 (Campanhas)
    window.tabs_left.setCurrentIndex(3)
    window.tabs_right.setCurrentIndex(1)
    app.processEvents()
    save_shot(window, "ui-settings.png")

    window.close()
    app.quit()
    print("\nDone. Screenshots saved to docs/images/")


if __name__ == "__main__":
    run()
