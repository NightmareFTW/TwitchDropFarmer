from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import sys
import traceback
import weakref
from typing import Callable
from urllib.parse import quote

import requests

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, QUrl, QPoint, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygon


def _resolve_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        if meipass:
            frozen_assets = meipass / "twitch_drop_farmer" / "assets"
            if frozen_assets.exists():
                return frozen_assets
    return Path(__file__).resolve().parent / "assets"


_ASSETS_DIR = _resolve_assets_dir()
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import load_config, save_config
from .farmer import FarmEngine, FarmSnapshot
from .models import DropCampaign, FarmDecision
from .twitch_client import TwitchClient
from .energy_profiles import AVAILABLE_PROFILES, get_profile_by_name
from .alerts import AlertManager, AlertSeverity, AlertType, get_alert_manager
from . import __version__, updater

logger = logging.getLogger(__name__)

LABEL_ROLE = int(Qt.ItemDataRole.UserRole) + 1
CHECK_MARK = "\u2713"
BOX_ART_FALLBACK_URL = "https://static-cdn.jtvnw.net/ttv-static/404_boxart.jpg"

# ── Ribbon constants ────────────────────────────────────────────────────────
RIBBON_FARMING = ("FARMING", "#9147ff")  # purple
RIBBON_LIVE    = ("LIVE",    "#00b167")  # green


class GameCard(QWidget):
    """Card moderno para o dashboard: box art com ribbon de estado, hover fade e borda animada."""

    CARD_W = 130
    CARD_H = 185

    def __init__(
        self,
        game_key: str,
        game_label: str,
        pixmap: QPixmap,
        ribbon: tuple[str, str] | None = None,
        is_farming: bool = False,
        on_click: Callable | None = None,
    ) -> None:
        super().__init__()
        self.game_key    = game_key
        self.game_label  = game_label
        self._pixmap     = pixmap
        self._ribbon     = ribbon        # (text, hex_color) or None
        self._is_farming = is_farming
        self._on_click   = on_click
        self._hover_t    = 0.0            # 0.0 → 1.0 for hover fade

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip(game_label)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)   # ~60 fps
        self._anim_direction = 0
        self._anim_timer.timeout.connect(self._tick_anim)

    # ── animation ─────────────────────────────────────────────────────────

    def _tick_anim(self) -> None:
        self._hover_t = max(0.0, min(1.0, self._hover_t + 0.09 * self._anim_direction))
        self.update()
        if self._hover_t <= 0.0 or self._hover_t >= 1.0:
            self._anim_timer.stop()

    def enterEvent(self, event) -> None:
        self._anim_direction = 1
        self._anim_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim_direction = -1
        self._anim_timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._on_click:
            self._on_click(self.game_key, self.game_label)
        super().mousePressEvent(event)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        rect = self.rect()

        # -- rounded clip mask --
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), 10, 10)
        painter.setClipPath(clip)

        # -- box art (fill card, centre-crop) --
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (scaled.width()  - w) // 2
            y_off = (scaled.height() - h) // 2
            painter.drawPixmap(-x_off, -y_off, scaled)
        else:
            painter.fillRect(rect, QColor("#1a1a22"))

        # -- bottom gradient for name legibility --
        grad = QLinearGradient(0, h * 0.42, 0, h)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 215))
        painter.fillRect(rect, grad)

        # -- hover bright overlay --
        if self._hover_t > 0.0:
            overlay = QColor(255, 255, 255, int(32 * self._hover_t))
            painter.fillRect(rect, overlay)

        # -- diagonal ribbon (top-left) --
        if self._ribbon:
            ribbon_text, ribbon_hex = self._ribbon
            ribbon_size = 58
            pts = QPolygon([QPoint(0, 0), QPoint(ribbon_size, 0), QPoint(0, ribbon_size)])
            painter.setBrush(QColor(ribbon_hex))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(pts)
            painter.save()
            painter.translate(ribbon_size // 3, ribbon_size // 3 - 2)
            painter.rotate(-45)
            rib_font = QFont()
            rib_font.setPixelSize(8)
            rib_font.setBold(True)
            painter.setFont(rib_font)
            painter.setPen(QColor("white"))
            painter.drawText(QRect(-22, -7, 44, 14), Qt.AlignmentFlag.AlignCenter, ribbon_text)
            painter.restore()

        # -- border (outside clip so it sits on the rounded edge) --
        painter.setClipping(False)
        if self._is_farming:
            border_color = QColor("#9147ff")
            border_w = 2.5
        else:
            alpha = int(55 + 100 * self._hover_t)
            border_color = QColor(145, 71, 255, alpha)
            border_w = 1.5
        pen = QPen(border_color, border_w)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), 9, 9)

        # -- game name text (bottom overlay) --
        painter.setClipPath(clip)
        name_font = QFont()
        name_font.setPixelSize(11)
        name_font.setBold(True)
        painter.setFont(name_font)
        alpha_text = int(210 + 45 * self._hover_t)
        painter.setPen(QColor(255, 255, 255, alpha_text))
        text_rect = QRect(5, h - 46, w - 10, 42)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            self.game_label,
        )

        painter.end()


THEMES: dict[str, str] = {
    "twitch": """
        QWidget { background: #0e0e10; color: #efeff1; }
        QGroupBox {
            border: 1px solid #2a2a31;
            border-radius: 10px;
            margin-top: 12px;
            padding-top: 12px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
            color: #bf94ff;
        }
        QLineEdit, QComboBox, QListWidget, QTextEdit {
            background: #18181b;
            border: 1px solid #2f2f35;
            border-radius: 8px;
            padding: 6px;
        }
        QListWidget::item { padding: 5px 6px; }
        QPushButton {
            background: #9147ff;
            color: white;
            padding: 7px 10px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
        }
        QPushButton:hover { background: #a970ff; }
        QPushButton:disabled { background: #444451; color: #a8a8af; }
        QRadioButton { spacing: 8px; }
        QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border-radius: 8px;
            border: 2px solid #555563;
            background: #18181b;
        }
        QRadioButton::indicator:hover { border-color: #9147ff; }
        QRadioButton::indicator:checked {
            border: 5px solid #9147ff;
            background: #efeff1;
        }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 2px solid #555563;
            background: #18181b;
        }
        QCheckBox::indicator:hover { border-color: #9147ff; }
        QCheckBox::indicator:checked {
            border: 2px solid #9147ff;
            background: #9147ff;
        }
        QLabel#HelpIcon {
            background: #9147ff;
            color: white;
            border-radius: 9px;
            font-weight: 700;
        }
        QFrame#DashboardGameCard {
            background: #18181b;
            border: 1px solid #2f2f35;
            border-radius: 12px;
            padding: 10px 8px 8px 8px;
            min-height: 208px;
        }
        QFrame#DashboardGameCard[hovered="true"] {
            border: 1px solid #7f52c6;
            background: #1f1f24;
        }
        QFrame#DashboardGameCard[selected="true"] {
            border: 2px solid #a970ff;
            background: #241b34;
        }
        QFrame#DashboardGameCard[farmable="false"] {
            border: 1px solid #34343b;
        }
        QLabel#DashboardTitle {
            font-weight: 600;
            color: #efeff1;
        }
        QFrame#DashboardGameCard[farmable="false"] QLabel#DashboardTitle {
            color: #a8a8af;
        }
        QLabel#DashboardBadge {
            background: #28303b;
            color: #b7d7ff;
            border-radius: 7px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: 700;
        }
        QFrame#DashboardGameCard[status="active"] QLabel#DashboardBadge {
            background: #213729;
            color: #96f2ad;
        }
        QFrame#DashboardGameCard[status="upcoming"] QLabel#DashboardBadge {
            background: #2d2f36;
            color: #c6c9d3;
        }
        QFrame#DashboardGameCard[status="offline"] QLabel#DashboardBadge {
            background: #2d2f36;
            color: #c6c9d3;
        }
        QFrame#DashboardGameCard[status="completed"] QLabel#DashboardBadge {
            background: #0f3f2c;
            color: #9cf2cb;
        }
        QFrame#DashboardGameCard[status="subscription_required"] QLabel#DashboardBadge {
            background: #4a2d12;
            color: #ffd19a;
        }
        QFrame#DashboardGameCard[status="lost_full"] QLabel#DashboardBadge {
            background: #4a1a1d;
            color: #ffb3b8;
        }
        QFrame#DashboardGameCard[status="lost_partial"] QLabel#DashboardBadge {
            background: #4a3b14;
            color: #ffe39f;
        }
        QLabel#DashboardRibbon {
            background: #a970ff;
            color: #ffffff;
            border-radius: 6px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
    """,
    "black_red": """
        QWidget { background: #050505; color: #f2f2f2; }
        QGroupBox {
            border: 1px solid #3a1515;
            border-radius: 10px;
            margin-top: 12px;
            padding-top: 12px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
            color: #ff7676;
        }
        QLineEdit, QComboBox, QListWidget, QTextEdit {
            background: #111111;
            border: 1px solid #402020;
            border-radius: 8px;
            padding: 6px;
        }
        QListWidget::item { padding: 5px 6px; }
        QPushButton {
            background: #b00020;
            color: white;
            padding: 7px 10px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
        }
        QPushButton:hover { background: #d00027; }
        QPushButton:disabled { background: #4a2428; color: #b8a6a8; }
        QRadioButton { spacing: 8px; }
        QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border-radius: 8px;
            border: 2px solid #5a3535;
            background: #111111;
        }
        QRadioButton::indicator:hover { border-color: #ff5d6d; }
        QRadioButton::indicator:checked {
            border: 5px solid #ff5d6d;
            background: #f2f2f2;
        }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 2px solid #5a3535;
            background: #111111;
        }
        QCheckBox::indicator:hover { border-color: #ff5d6d; }
        QCheckBox::indicator:checked {
            border: 2px solid #ff5d6d;
            background: #b00020;
        }
        QLabel#HelpIcon {
            background: #b00020;
            color: white;
            border-radius: 9px;
            font-weight: 700;
        }
        QFrame#DashboardGameCard {
            background: #111111;
            border: 1px solid #402020;
            border-radius: 12px;
            padding: 10px 8px 8px 8px;
            min-height: 208px;
        }
        QFrame#DashboardGameCard[hovered="true"] {
            border: 1px solid #b83a44;
            background: #1a1010;
        }
        QFrame#DashboardGameCard[selected="true"] {
            border: 2px solid #ff5d6d;
            background: #2a1317;
        }
        QFrame#DashboardGameCard[farmable="false"] {
            border: 1px solid #3a2a2c;
        }
        QLabel#DashboardTitle {
            font-weight: 600;
            color: #f2f2f2;
        }
        QFrame#DashboardGameCard[farmable="false"] QLabel#DashboardTitle {
            color: #b8a6a8;
        }
        QLabel#DashboardBadge {
            background: #3a2222;
            color: #ffb0b0;
            border-radius: 7px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: 700;
        }
        QFrame#DashboardGameCard[status="active"] QLabel#DashboardBadge {
            background: #203227;
            color: #98ecac;
        }
        QFrame#DashboardGameCard[status="upcoming"] QLabel#DashboardBadge {
            background: #2f2729;
            color: #c5b6b8;
        }
        QFrame#DashboardGameCard[status="offline"] QLabel#DashboardBadge {
            background: #2f2729;
            color: #c5b6b8;
        }
        QFrame#DashboardGameCard[status="completed"] QLabel#DashboardBadge {
            background: #103425;
            color: #8de6ba;
        }
        QFrame#DashboardGameCard[status="subscription_required"] QLabel#DashboardBadge {
            background: #4a2f16;
            color: #ffd7a8;
        }
        QFrame#DashboardGameCard[status="lost_full"] QLabel#DashboardBadge {
            background: #4a1b22;
            color: #ffb8c1;
        }
        QFrame#DashboardGameCard[status="lost_partial"] QLabel#DashboardBadge {
            background: #4a3b14;
            color: #ffe39f;
        }
        QLabel#DashboardRibbon {
            background: #ff5d6d;
            color: #ffffff;
            border-radius: 6px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
    """,
    "light": """
        QWidget { background: #f6f4fb; color: #1b1b1f; }
        QGroupBox {
            border: 1px solid #d4cfdf;
            border-radius: 10px;
            margin-top: 12px;
            padding-top: 12px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
            color: #6441a4;
        }
        QLineEdit, QComboBox, QListWidget, QTextEdit {
            background: #ffffff;
            border: 1px solid #d3cfe0;
            border-radius: 8px;
            padding: 6px;
        }
        QListWidget::item { padding: 5px 6px; }
        QPushButton {
            background: #6441a4;
            color: white;
            padding: 7px 10px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
        }
        QPushButton:hover { background: #7b57bf; }
        QPushButton:disabled { background: #ccc6dc; color: #6f6784; }
        QRadioButton { spacing: 8px; }
        QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border-radius: 8px;
            border: 2px solid #b8b0cc;
            background: #ffffff;
        }
        QRadioButton::indicator:hover { border-color: #6441a4; }
        QRadioButton::indicator:checked {
            border: 5px solid #6441a4;
            background: #ffffff;
        }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 2px solid #b8b0cc;
            background: #ffffff;
        }
        QCheckBox::indicator:hover { border-color: #6441a4; }
        QCheckBox::indicator:checked {
            border: 2px solid #6441a4;
            background: #6441a4;
        }
        QLabel#HelpIcon {
            background: #6441a4;
            color: white;
            border-radius: 9px;
            font-weight: 700;
        }
        QFrame#DashboardGameCard {
            background: #ffffff;
            border: 1px solid #d3cfe0;
            border-radius: 12px;
            padding: 10px 8px 8px 8px;
            min-height: 208px;
        }
        QFrame#DashboardGameCard[hovered="true"] {
            border: 1px solid #8a6ec7;
            background: #fbf9ff;
        }
        QFrame#DashboardGameCard[selected="true"] {
            border: 2px solid #7b57bf;
            background: #f0e9ff;
        }
        QFrame#DashboardGameCard[farmable="false"] {
            border: 1px solid #d9d5e3;
        }
        QLabel#DashboardTitle {
            font-weight: 600;
            color: #1b1b1f;
        }
        QFrame#DashboardGameCard[farmable="false"] QLabel#DashboardTitle {
            color: #7d748f;
        }
        QLabel#DashboardBadge {
            background: #ebe7f6;
            color: #554776;
            border-radius: 7px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: 700;
        }
        QFrame#DashboardGameCard[status="active"] QLabel#DashboardBadge {
            background: #daf0e0;
            color: #1f6b36;
        }
        QFrame#DashboardGameCard[status="upcoming"] QLabel#DashboardBadge {
            background: #ebe9ef;
            color: #675f77;
        }
        QFrame#DashboardGameCard[status="offline"] QLabel#DashboardBadge {
            background: #ebe9ef;
            color: #675f77;
        }
        QFrame#DashboardGameCard[status="completed"] QLabel#DashboardBadge {
            background: #d7f1e4;
            color: #19603d;
        }
        QFrame#DashboardGameCard[status="subscription_required"] QLabel#DashboardBadge {
            background: #ffe8c7;
            color: #8a5417;
        }
        QFrame#DashboardGameCard[status="lost_full"] QLabel#DashboardBadge {
            background: #f8d6da;
            color: #8a1f2c;
        }
        QFrame#DashboardGameCard[status="lost_partial"] QLabel#DashboardBadge {
            background: #f8edcc;
            color: #7d5d1c;
        }
        QLabel#DashboardRibbon {
            background: #7b57bf;
            color: #ffffff;
            border-radius: 6px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
    """,
}

LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("pt_PT", "Portugues (Portugal)"),
    ("en", "English"),
]

SORT_MODE_OPTIONS: list[str] = [
    "ending_soonest",
    "least_remaining",
    "most_remaining",
    "shortest_campaign",
    "longest_campaign",
]

TRANSLATIONS: dict[str, dict[str, str]] = {
    "pt_PT": {
        "window_title": "Twitch Drop Farmer",
        "oauth_group": "OAuth",
        "oauth_token_label": "Token auth-token",
        "oauth_placeholder": "Cola aqui o valor do cookie auth-token",
        "oauth_help": (
            "Token necessário: copia o valor do cookie 'auth-token' da sessão em https://www.twitch.tv .\n"
            "Depois de guardado, a app reutiliza este token automaticamente enquanto continuar válido.\n"
            "Não copies 'api_token' nem o nome do cookie.\n"
            "Passos rápidos:\n"
            "1. Inicia sessão na Twitch no navegador.\n"
            "2. Abre as ferramentas de programador ou um editor de cookies.\n"
            "3. Encontra o cookie 'auth-token' em www.twitch.tv.\n"
            "4. Copia apenas o valor do cookie.\n"
            "5. Cola esse valor aqui sem o prefixo 'OAuth '."
        ),
        "save_oauth": "Guardar OAuth",
        "edit_oauth": "Editar OAuth",
        "auth_not_saved": "Nenhum auth-token guardado.",
        "auth_saved_hidden": "auth-token guardado e oculto.",
        "auth_valid": "Ligado como {login} (user {user_id}).",
        "auth_invalid": "O auth-token actual não foi validado.",
        "preferences_group": "Preferências",
        "language_label": "Idioma:",
        "theme_label": "Tema:",
        "sort_label": "Prioridade de farm:",
        "theme_twitch": "Twitch",
        "theme_black_red": "Black / Red",
        "theme_light": "Claro",
        "sort_ending_soonest": "Terminam mais cedo",
        "sort_least_remaining": "Menos minutos em falta",
        "sort_most_remaining": "Mais minutos em falta",
        "sort_shortest_campaign": "Menor duração total",
        "sort_longest_campaign": "Maior duração total",
        "refresh_active": "Actualizar campanhas e streams",
        "active_lists_note": "As listas abaixo são geradas a partir das campanhas e canais activos devolvidos pela Twitch.",
        "filters_hint": "Organiza os filtros por sub-aba e usa pesquisa para encontrar jogos/canais rapidamente.",
        "filters_search_games": "Pesquisar jogo...",
        "filters_search_channels": "Pesquisar canal...",
        "filters_select_all": "Selecionar todos",
        "filters_clear_all": "Limpar todos",
        "filters_select_visible": "Selecionar visíveis",
        "filters_clear_visible": "Limpar visíveis",
        "filter_tab_games_whitelist": "Jogos whitelist",
        "filter_tab_games_blacklist": "Jogos blacklist",
        "filter_tab_channels_whitelist": "Canais whitelist",
        "filter_tab_channels_blacklist": "Canais blacklist",
        "filter_tab_games_whitelist_count": "Jogos whitelist ({selected}/{total})",
        "filter_tab_games_blacklist_count": "Jogos blacklist ({selected}/{total})",
        "filter_tab_channels_whitelist_count": "Canais whitelist ({selected}/{total})",
        "filter_tab_channels_blacklist_count": "Canais blacklist ({selected}/{total})",
        "games_whitelist_group": "Whitelist de jogos",
        "games_blacklist_group": "Blacklist de jogos",
        "channels_whitelist_group": "Whitelist de canais",
        "channels_blacklist_group": "Blacklist de canais",
        "games_whitelist_hint": "✓ Selecciona apenas os jogos que queres farmar. Se nada estiver marcado, todos os jogos activos podem ser farmados.",
        "games_blacklist_hint": "X Marca os jogos que devem ser ignorados. Se nada estiver marcado, nenhum jogo é excluído.",
        "channels_whitelist_hint": "✓ Estes canais têm prioridade. Se nenhum estiver disponível, a app usa os restantes canais activos.",
        "channels_blacklist_hint": "X Estes canais nunca serão usados. Se nada estiver marcado, nenhum canal é bloqueado.",
        "no_active_games": "Ainda não há jogos activos para mostrar.",
        "no_active_channels": "Ainda não há canais activos para mostrar.",
        "save_settings": "Guardar definições",
        "start_farm": "Iniciar farm",
        "stop_farm": "Parar farm",
        "farming_start_main": "Iniciar farm",
        "farming_pause_main": "Pausar farm",
        "farming_next_game": "Próximo jogo",
        "farming_next_game_selected": "Alvo manual alterado para: {game} -> {channel}.",
        "farming_next_game_unavailable": "Não há próximo jogo disponível para alternar.",
        "campaigns_detected": "Campanhas detetadas",
        "campaigns_detected_count": "Campanhas detetadas ({count})",
        "tab_farming_now": "A farmar agora",
        "tab_campaign_explorer": "Campanhas",
        "tab_dashboard": "Dashboard",
        "tab_dashboard": "Dashboard",
        "tab_account": "Conta",
        "tab_filters": "Filtros",
        "tab_settings": "Definições",
        "dashboard_group": "Jogos da whitelist",
        "dashboard_hint": "Clica num jogo para o tornar alvo manual de farm.",
        "dashboard_refresh": "Atualizar dashboard",
        "dashboard_hide_sub_only": "Ocultar jogos com drops de subscrição",
        "dashboard_hide_sub_only_help": "Esconde jogos cujas campanhas disponíveis exigem subscrição para resgatar drops.",
        "dashboard_empty": "Adiciona jogos na whitelist para aparecerem aqui.",
        "dashboard_selected": "Alvo manual por jogo: {game}.",
        "dashboard_unset": "Sem alvo manual por jogo.",
        "dashboard_ribbon": "▶ Selecionado",
        "dashboard_ribbon_completed": "CONCLUIDO",
        "dashboard_game_unavailable": "O jogo selecionado ({game}) não está farmável agora.",
        "dashboard_badge_active": "Ativo",
        "dashboard_badge_upcoming": "Nao iniciada",
        "dashboard_badge_offline": "Sem stream",
        "dashboard_badge_no_data": "Sem dados",
        "dashboard_badge_completed": "Completo",
        "dashboard_badge_subscription_required": "Subscricao Requerida",
        "dashboard_badge_lost_full": "Perdida",
        "dashboard_badge_lost_partial": "Parcial perdida",
        "dashboard_completed_tooltip": "Todos os drops deste jogo ja foram concluidos nesta conta.",
        "dashboard_completed_tooltip_detail": "Concluidas {completed}/{total} campanhas rastreaveis deste jogo.",
        "dashboard_subscription_required_tooltip": "Este drop exige subscricao ativa para ser resgatado.",
        "dashboard_lost_full_tooltip": "Campanha expirada sem progresso: {lost}/{total} campanhas perderam todos os drops.",
        "dashboard_lost_partial_tooltip": "Campanha expirada com progresso parcial: {lost}/{total} campanhas ficaram incompletas.",
        "dashboard_upcoming_tooltip": "A campanha ainda nao comecou.",
        "dashboard_offline_tooltip": "Sem stream valida no momento para esta campanha.",
        "dashboard_ribbon_lost_full": "PERDIDA",
        "dashboard_ribbon_lost_partial": "PARCIAL",
        "dashboard_ribbon_subscription_required": "SUBSCRICAO",
        "active_drops_group": "Drops ativos",
        "active_drops_group_game": "Drops ativos de {game}",
        "active_drops_empty": "Sem drops ativos para mostrar.",
        "active_drops_claimed": "Resgatado",
        "active_drops_progress": "{current}/{required} min",
        "active_drops_subscription_hint": "Esta campanha exige subscricao ativa para resgatar.",
        "farming_now_group": "Estado actual de farming",
        "farming_state_running": "Estado: Em execução",
        "farming_state_stopped": "Estado: Parado",
        "farming_now_idle": "Nenhuma campanha ativa a ser farmada neste momento.",
        "farming_now_game": "Jogo: {game}",
        "farming_now_campaign": "Campanha: {campaign}",
        "farming_now_channel": "Canal em visualização: {channel}",
        "farming_now_next_drop": "Próximo drop: {drop}",
        "farming_now_eta": "Tempo para o próximo drop: {eta}",
        "farming_now_progress": "Progresso da campanha: {progress}/{required} min",
        "farming_last_refresh": "Última actualização: {time}",
        "farming_last_refresh_never": "Última actualização: --:--:--",
        "drop_unknown": "Desconhecido",
        "campaign_filter_status": "Mostrar:",
        "campaign_filter_link": "Ligação:",
        "campaign_sort_label": "Ordenar por:",
        "campaign_status_all": "Todas",
        "campaign_status_active": "Ativas",
        "campaign_status_upcoming": "Futuras",
        "campaign_status_farmable": "Farmáveis agora",
        "campaign_link_all": "Todas",
        "campaign_link_eligible": "Conta ligada/elegível",
        "campaign_link_unlinked": "Por ligar",
        "campaign_sort_priority": "Prioridade de farm",
        "campaign_sort_ending": "Terminam mais cedo",
        "campaign_sort_progress": "Mais progresso",
        "campaign_sort_remaining": "Menos minutos em falta",
        "campaign_sort_game": "Jogo (A-Z)",
        "best_target_none": "Sem alvo prioritário neste momento.",
        "best_target": "Melhor alvo actual: {game} -> {channel} | ordenação: {sort_mode}",
        "best_target_no_stream": "Nenhuma stream válida para {game} | ordenação: {sort_mode}",
        "campaign_details_none": "Selecciona uma campanha para veres o estado da ligação e o link de conta.",
        "campaign_details": (
            "Jogo: {game}\n"
            "Campanha: {title}\n"
            "Estado: {status}\n"
            "Conta ligada: {linked}\n"
            "Progresso: {progress}/{required} min\n"
            "Canais permitidos pela campanha: {allowed}\n"
            "Ligação da conta: {link_status}"
        ),
        "linked_yes": "Sim",
        "linked_no": "Não",
        "linked_label": "ligada",
        "allowed_any": "Qualquer canal drops-enabled",
        "link_status_open_browser": "Disponível pelo botão abaixo",
        "link_status_unavailable": "Não necessário ou indisponível",
        "link_account": "Ligar conta desta campanha",
        "open_drops_page": "Abrir página de Drops",
        "link_button_disabled": "Seleciona uma campanha com conta por ligar.",
        "log_label": "Log",
        "error_title": "Erro",
        "oauth_saved": "auth-token guardado e validado.",
        "oauth_refreshing": "Token validado. A actualizar campanhas...",
        "settings_saved": "Definições guardadas.",
        "farming_started": "Farm automático iniciado.",
        "farming_stopped": "Farm parado.",
        "streamless_running": "Modo streamless ativo para o alvo selecionado.",
        "streamless_target": "Alvo streamless atual: {channel}.",
        "streamless_failed": "Falha no heartbeat streamless para {channel}.",
        "streamless_no_target": "Sem alvo streamless válido neste ciclo.",
        "refresh_done": "Actualização concluída: {count} campanhas.",
        "channel_word": "canal",
        "channel_unknown": "desconhecido",
        "remaining_word": "faltam",
        "ends_in_word": "termina em",
        "reason_game_filtered": "Jogo filtrado por whitelist/blacklist.",
        "reason_no_valid_stream": "Sem stream válida depois dos filtros.",
        "reason_stream_selected": "Melhor stream por drops ativos e viewers.",
        "reason_channel_priority": "Whitelist de canais aplicada.",
        "reason_account_not_linked": "Conta do jogo ainda não ligada a esta campanha.",
        "reason_subscription_required": "Campanha requer subscricao ativa para resgatar.",
        "reason_campaign_upcoming": "Campanha ainda não começou.",
        "reason_campaign_not_active": "Campanha não está activa neste momento.",
        "reason_campaign_completed": "Campanha concluída (todos os drops já completos).",
        "link_opened": "Link de campanha aberto no navegador.",
        "drops_page_opened": "Página de Drops aberta no navegador.",
        "token_required": "Tens de colar o valor do cookie auth-token antes de guardar.",
        "auth_quick_token": "Token Rápido",
        "auth_session_export": "Sessão Duradoura",
        "session_group": "Sessão do Browser",
        "session_export_label": "Exporta a sessão completa para durabilidade prolongada:",
        "btn_export_session": "Exportar Sessão JSON",
        "session_import_label": "Importa uma sessão guardada (JSON):",
        "btn_import_session": "Importar Sessão",
        "btn_validate_session": "Validar Sessão",
        "session_auth_status": "Estado da sessão: {status}",
        "session_not_imported": "Nenhuma sessão importada.",
        "session_imported": "Sessão importada e validada.",
        "session_imported_hidden": "Sessão importada (oculta).",
        "session_import_error": "Erro ao importar sessão: {error}",
        "session_export_success": "Sessão exportada. Copia o JSON abaixo e guarda-o num local seguro.",
        "session_export_copied": "JSON da sessão copiado para a área de transferência.",
        "auto_claim_checkbox": "Redimir drops automaticamente",
        "settings_tab_basic": "Básico",
        "settings_tab_advanced": "Avançado",
        "settings_tab_alerts": "Alertas",
        "energy_profile_label": "Perfil de energia",
        "watchdog_enabled": "Ativar monitor de progresso",
        "watchdog_timeout": "Tempo limite sem progresso",
        "autoupdate_enabled": "Atualizar automaticamente",
        "autoupdate_delay": "Espera antes de reiniciar",
        "btn_diagnostic": "Executar diagnóstico do sistema",
        "btn_check_updates": "Procurar atualizações",
        "status_diag_running": "A executar diagnóstico do sistema...",
        "status_diag_done": "Diagnóstico concluído.",
        "status_diag_timeout": "O diagnóstico excedeu o tempo de espera. Verifica ligação/token e tenta novamente.",
        "status_updates_checking": "A procurar atualizações...",
        "status_updates_failed": "Não foi possível verificar atualizações.",
        "status_updates_uptodate": "Esta versão já está atualizada.",
        "status_updates_available": "Há uma atualização disponível: {version}\nTransferência: {url}",
        "status_updates_timeout": "A procura de atualizações excedeu o tempo de espera. Tenta novamente.",
        "status_operation_error": "Erro: {error}",
        "version_corner": "v{version}",
        "help_energy_profile": "Define o comportamento da aplicação: mais económico (menos pedidos) ou mais reativo (mais pedidos).",
        "help_watchdog": "Monitoriza ausência de progresso e tenta recuperar automaticamente quando deteta bloqueio.",
        "help_watchdog_timeout": "Minutos sem progresso antes do monitor considerar que a farm ficou bloqueada.",
        "help_autoupdate": "Quando ativo, a aplicação pode transferir e aplicar automaticamente uma nova versão quando disponível.",
        "help_autoupdate_delay": "Tempo de espera antes de reiniciar a aplicação para concluir uma atualização automática.",
        "alert_type_campaign_expiring_soon": "Campanha a expirar brevemente",
        "alert_type_token_invalid": "Token inválido",
        "alert_type_no_progress": "Sem progresso",
        "alert_type_farm_complete": "Farm concluída",
        "alert_type_stream_offline": "Canal offline",
        "alert_type_api_error": "Erro da API",
        "alert_type_watchdog_recovered": "Recuperação do monitor",
        "alert_help_campaign_expiring_soon": "Avisa quando uma campanha está perto do fim para não perderes drops.",
        "alert_help_token_invalid": "Avisa quando o token deixa de ser válido e exige nova autenticação.",
        "alert_help_no_progress": "Avisa quando não há progresso de drops durante um período anormal.",
        "alert_help_farm_complete": "Avisa quando a farm da campanha ativa foi concluída.",
        "alert_help_stream_offline": "Avisa quando o canal alvo fica offline.",
        "alert_help_api_error": "Avisa quando há falhas de comunicação com a API da Twitch.",
        "alert_help_watchdog_recovered": "Avisa quando o monitor deteta problema e consegue recuperar automaticamente.",
        "redeem_drops": "Redimir drops",
        "redeem_done": "Drops redimidos: {count}.",
        "redeem_none": "Nenhum drop pronto para redimir.",
        "redeem_auto_done": "Auto-redimir executado: {count} drops.",
    },
    "en": {
        "window_title": "Twitch Drop Farmer",
        "oauth_group": "OAuth",
        "oauth_token_label": "auth-token value",
        "oauth_placeholder": "Paste the auth-token cookie value here",
        "oauth_help": (
            "Required token: copy the value of the 'auth-token' cookie from https://www.twitch.tv .\n"
            "After saving, the app reuses it automatically while it remains valid.\n"
            "Do not use 'api_token' and do not paste the cookie name.\n"
            "Quick steps:\n"
            "1. Sign in to Twitch in your browser.\n"
            "2. Open developer tools or a cookie editor.\n"
            "3. Find the 'auth-token' cookie under www.twitch.tv.\n"
            "4. Copy only the cookie value.\n"
            "5. Paste that value here without the 'OAuth ' prefix."
        ),
        "save_oauth": "Save OAuth",
        "edit_oauth": "Edit OAuth",
        "auth_not_saved": "No auth-token saved yet.",
        "auth_saved_hidden": "auth-token saved and hidden.",
        "auth_valid": "Authenticated as {login} (user {user_id}).",
        "auth_invalid": "The current auth-token has not been validated.",
        "preferences_group": "Preferences",
        "language_label": "Language:",
        "theme_label": "Theme:",
        "sort_label": "Farm priority:",
        "theme_twitch": "Twitch",
        "theme_black_red": "Black / Red",
        "theme_light": "Light",
        "sort_ending_soonest": "Ending soonest",
        "sort_least_remaining": "Least minutes remaining",
        "sort_most_remaining": "Most minutes remaining",
        "sort_shortest_campaign": "Shortest total duration",
        "sort_longest_campaign": "Longest total duration",
        "refresh_active": "Refresh campaigns and streams",
        "active_lists_note": "The lists below are built from the active campaigns and channels returned by Twitch.",
        "filters_hint": "Use sub-tabs and search to browse all games/channels with less scrolling.",
        "filters_search_games": "Search game...",
        "filters_search_channels": "Search channel...",
        "filters_select_all": "Select all",
        "filters_clear_all": "Clear all",
        "filters_select_visible": "Select visible",
        "filters_clear_visible": "Clear visible",
        "filter_tab_games_whitelist": "Game whitelist",
        "filter_tab_games_blacklist": "Game blacklist",
        "filter_tab_channels_whitelist": "Channel whitelist",
        "filter_tab_channels_blacklist": "Channel blacklist",
        "filter_tab_games_whitelist_count": "Game whitelist ({selected}/{total})",
        "filter_tab_games_blacklist_count": "Game blacklist ({selected}/{total})",
        "filter_tab_channels_whitelist_count": "Channel whitelist ({selected}/{total})",
        "filter_tab_channels_blacklist_count": "Channel blacklist ({selected}/{total})",
        "games_whitelist_group": "Game whitelist",
        "games_blacklist_group": "Game blacklist",
        "channels_whitelist_group": "Channel whitelist",
        "channels_blacklist_group": "Channel blacklist",
        "games_whitelist_hint": "✓ Pick only the games you want to farm. If nothing is selected, every active game can be farmed.",
        "games_blacklist_hint": "X Mark games that must be ignored. If nothing is selected, no game is excluded.",
        "channels_whitelist_hint": "✓ These channels get priority. If none of them are available, the app falls back to the other active channels.",
        "channels_blacklist_hint": "X These channels are never used. If nothing is selected, no channel is blocked.",
        "no_active_games": "No active games available yet.",
        "no_active_channels": "No active channels available yet.",
        "save_settings": "Save settings",
        "start_farm": "Start farming",
        "stop_farm": "Stop farming",
        "farming_start_main": "Start farming",
        "farming_pause_main": "Pause farming",
        "farming_next_game": "Next game",
        "farming_next_game_selected": "Manual target changed to: {game} -> {channel}.",
        "farming_next_game_unavailable": "No next game available to switch.",
        "campaigns_detected": "Detected campaigns",
        "campaigns_detected_count": "Detected campaigns ({count})",
        "tab_farming_now": "Farming now",
        "tab_campaign_explorer": "Campaigns",
        "tab_dashboard": "Dashboard",
        "tab_dashboard": "Dashboard",
        "tab_account": "Account",
        "tab_filters": "Filters",
        "tab_settings": "Settings",
        "dashboard_group": "Whitelisted games",
        "dashboard_hint": "Click a game to make it your manual farming target.",
        "dashboard_refresh": "Refresh dashboard",
        "dashboard_hide_sub_only": "Hide games with subscription-only drops",
        "dashboard_hide_sub_only_help": "Hide games whose available campaigns require an active subscription to redeem drops.",
        "dashboard_empty": "Add games to your whitelist to show them here.",
        "dashboard_selected": "Manual game target: {game}.",
        "dashboard_unset": "No manual game target.",
        "dashboard_ribbon": "▶ Selected",
        "dashboard_ribbon_completed": "COMPLETED",
        "dashboard_game_unavailable": "Selected game ({game}) is not farmable right now.",
        "dashboard_badge_active": "Active",
        "dashboard_badge_upcoming": "Not started",
        "dashboard_badge_offline": "No stream",
        "dashboard_badge_no_data": "No data",
        "dashboard_badge_completed": "Completed",
        "dashboard_badge_subscription_required": "Subscription Required",
        "dashboard_badge_lost_full": "Lost",
        "dashboard_badge_lost_partial": "Partially lost",
        "dashboard_completed_tooltip": "All drops for this game are already completed on this account.",
        "dashboard_completed_tooltip_detail": "Completed {completed}/{total} trackable campaigns for this game.",
        "dashboard_subscription_required_tooltip": "This drop requires an active subscription to redeem.",
        "dashboard_lost_full_tooltip": "Expired with no progress: {lost}/{total} campaigns lost all drops.",
        "dashboard_lost_partial_tooltip": "Expired with partial progress: {lost}/{total} campaigns ended incomplete.",
        "dashboard_upcoming_tooltip": "The campaign has not started yet.",
        "dashboard_offline_tooltip": "No valid stream is available right now for this campaign.",
        "dashboard_ribbon_lost_full": "LOST",
        "dashboard_ribbon_lost_partial": "PARTIAL",
        "dashboard_ribbon_subscription_required": "SUB REQUIRED",
        "active_drops_group": "Active drops",
        "active_drops_group_game": "Active drops for {game}",
        "active_drops_empty": "No active drops to display.",
        "active_drops_claimed": "Claimed",
        "active_drops_progress": "{current}/{required} min",
        "active_drops_subscription_hint": "This campaign requires an active subscription to redeem drops.",
        "farming_now_group": "Current farming status",
        "farming_state_running": "Status: Running",
        "farming_state_stopped": "Status: Stopped",
        "farming_now_idle": "No active campaign is being farmed right now.",
        "farming_now_game": "Game: {game}",
        "farming_now_campaign": "Campaign: {campaign}",
        "farming_now_channel": "Watching channel: {channel}",
        "farming_now_next_drop": "Next drop: {drop}",
        "farming_now_eta": "Time to next drop: {eta}",
        "farming_now_progress": "Campaign progress: {progress}/{required} min",
        "farming_last_refresh": "Last refresh: {time}",
        "farming_last_refresh_never": "Last refresh: --:--:--",
        "drop_unknown": "Unknown",
        "campaign_filter_status": "Show:",
        "campaign_filter_link": "Linking:",
        "campaign_sort_label": "Sort by:",
        "campaign_status_all": "All",
        "campaign_status_active": "Active",
        "campaign_status_upcoming": "Upcoming",
        "campaign_status_farmable": "Farmable now",
        "campaign_link_all": "All",
        "campaign_link_eligible": "Linked/eligible",
        "campaign_link_unlinked": "Needs linking",
        "campaign_sort_priority": "Farm priority",
        "campaign_sort_ending": "Ending soonest",
        "campaign_sort_progress": "Most progress",
        "campaign_sort_remaining": "Least remaining",
        "campaign_sort_game": "Game (A-Z)",
        "best_target_none": "No priority target right now.",
        "best_target": "Current best target: {game} -> {channel} | order: {sort_mode}",
        "best_target_no_stream": "No valid stream for {game} | order: {sort_mode}",
        "campaign_details_none": "Select a campaign to inspect account linking and the campaign link.",
        "campaign_details": (
            "Game: {game}\n"
            "Campaign: {title}\n"
            "Status: {status}\n"
            "Account linked: {linked}\n"
            "Progress: {progress}/{required} min\n"
            "Allowed campaign channels: {allowed}\n"
            "Account link: {link_status}"
        ),
        "linked_yes": "Yes",
        "linked_no": "No",
        "linked_label": "linked",
        "allowed_any": "Any drops-enabled channel",
        "link_status_open_browser": "Available from the button below",
        "link_status_unavailable": "Not needed or unavailable",
        "link_account": "Link account for this campaign",
        "open_drops_page": "Open Drops page",
        "link_button_disabled": "Select a campaign that still needs account linking.",
        "log_label": "Log",
        "error_title": "Error",
        "oauth_saved": "auth-token saved and validated.",
        "oauth_refreshing": "Token validated. Refreshing campaigns...",
        "settings_saved": "Settings saved.",
        "farming_started": "Automatic farming started.",
        "farming_stopped": "Farming stopped.",
        "streamless_running": "Streamless mode active for the selected target.",
        "streamless_target": "Current streamless target: {channel}.",
        "streamless_failed": "Streamless heartbeat failed for {channel}.",
        "streamless_no_target": "No valid streamless target in this cycle.",
        "refresh_done": "Refresh complete: {count} campaigns.",
        "channel_word": "channel",
        "channel_unknown": "unknown",
        "remaining_word": "remaining",
        "ends_in_word": "ends in",
        "reason_game_filtered": "Game filtered by whitelist/blacklist.",
        "reason_no_valid_stream": "No valid stream after filters.",
        "reason_stream_selected": "Best stream by drops enabled and viewers.",
        "reason_channel_priority": "Channel whitelist priority applied.",
        "reason_account_not_linked": "Game account is not linked for this campaign yet.",
        "reason_subscription_required": "Campaign requires an active subscription to redeem.",
        "reason_campaign_upcoming": "Campaign has not started yet.",
        "reason_campaign_not_active": "Campaign is not active right now.",
        "reason_campaign_completed": "Campaign completed (all drops already finished).",
        "link_opened": "Campaign link opened in the browser.",
        "drops_page_opened": "Drops page opened in the browser.",
        "token_required": "You need to paste the auth-token cookie value before saving.",
        "auth_quick_token": "Quick Token",
        "auth_session_export": "Lasting Session",
        "session_group": "Browser Session",
        "session_export_label": "Export full session for extended durability:",
        "btn_export_session": "Export Session JSON",
        "session_import_label": "Import a saved session (JSON):",
        "btn_import_session": "Import Session",
        "btn_validate_session": "Validate Session",
        "session_auth_status": "Session status: {status}",
        "session_not_imported": "No session imported yet.",
        "session_imported": "Session imported and validated.",
        "session_imported_hidden": "Session imported (hidden).",
        "session_import_error": "Error importing session: {error}",
        "session_export_success": "Session exported. Copy the JSON below and save it securely.",
        "session_export_copied": "Session JSON copied to clipboard.",
        "auto_claim_checkbox": "Redeem drops automatically",
        "settings_tab_basic": "Basic",
        "settings_tab_advanced": "Advanced",
        "settings_tab_alerts": "Alerts",
        "energy_profile_label": "Energy profile",
        "watchdog_enabled": "Enable watchdog",
        "watchdog_timeout": "Stall timeout",
        "autoupdate_enabled": "Automatic updates",
        "autoupdate_delay": "Delay before restart",
        "btn_diagnostic": "Run diagnostics",
        "btn_check_updates": "Check updates",
        "status_diag_running": "Running system diagnostics...",
        "status_diag_done": "Diagnostics completed.",
        "status_diag_timeout": "Diagnostics exceeded the time limit. Check network/token and try again.",
        "status_updates_checking": "Checking for updates...",
        "status_updates_failed": "Unable to check for updates.",
        "status_updates_uptodate": "This version is already up to date.",
        "status_updates_available": "Update available: {version}\nDownload: {url}",
        "status_updates_timeout": "Update check exceeded the time limit. Please try again.",
        "status_operation_error": "Error: {error}",
        "version_corner": "v{version}",
        "help_energy_profile": "Defines app behavior: more economical (fewer requests) or more responsive (more requests).",
        "help_watchdog": "Monitors lack of progress and tries automatic recovery when farming gets stuck.",
        "help_watchdog_timeout": "Minutes without progress before watchdog considers farming stalled.",
        "help_autoupdate": "When enabled, the app can automatically download and apply a new version when available.",
        "help_autoupdate_delay": "Wait time before restarting the app to finish an automatic update.",
        "alert_type_campaign_expiring_soon": "Campaign expiring soon",
        "alert_type_token_invalid": "Invalid token",
        "alert_type_no_progress": "No progress",
        "alert_type_farm_complete": "Farm complete",
        "alert_type_stream_offline": "Stream offline",
        "alert_type_api_error": "API error",
        "alert_type_watchdog_recovered": "Watchdog recovered",
        "alert_help_campaign_expiring_soon": "Warn when a campaign is close to ending so drops are not missed.",
        "alert_help_token_invalid": "Warn when the token is no longer valid and re-authentication is needed.",
        "alert_help_no_progress": "Warn when drop progress stops for an unusual period.",
        "alert_help_farm_complete": "Warn when farming for the active campaign is completed.",
        "alert_help_stream_offline": "Warn when the target channel goes offline.",
        "alert_help_api_error": "Warn when communication with Twitch API fails.",
        "alert_help_watchdog_recovered": "Warn when watchdog detects an issue and recovers automatically.",
        "redeem_drops": "Redeem drops",
        "redeem_done": "Redeemed drops: {count}.",
        "redeem_none": "No drops are ready to redeem.",
        "redeem_auto_done": "Auto-redeem completed: {count} drops.",
    },
}


@dataclass(frozen=True)
class FilterEntry:
    key: str
    label: str


class MarkerListWidget(QListWidget):
    def __init__(self, marker: str) -> None:
        super().__init__()
        self._marker = marker.replace("âœ“", CHECK_MARK)
        self._selected_keys: set[str] = set()
        self._all_entries: list[FilterEntry] = []
        self._filtered_entries: list[FilterEntry] = []
        self._empty_text = ""
        self._filter_text = ""
        self._has_state = False
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        scrollbar = self.verticalScrollBar()
        scrollbar.setSingleStep(18)
        scrollbar.setPageStep(120)
        self.itemClicked.connect(self._toggle_item)

    def set_entries(self, entries: list[FilterEntry], selected_keys: list[str], empty_text: str) -> None:
        self._selected_keys = {
            key.strip()
            for key in selected_keys
            if isinstance(key, str) and key.strip()
        }
        self._has_state = True
        self._all_entries = [
            entry
            for entry in entries
            if isinstance(entry.key, str)
            and isinstance(entry.label, str)
            and entry.key.strip()
        ]
        self._empty_text = empty_text
        self._rebuild_items()

    def set_filter_text(self, text: str) -> None:
        normalized = (text or "").strip().casefold()
        if normalized == self._filter_text:
            return
        self._filter_text = normalized
        self._rebuild_items()

    def select_visible(self) -> None:
        if not self._all_entries:
            return
        changed = False
        for entry in self._filtered_entries:
            if entry.key in self._selected_keys:
                continue
            self._selected_keys.add(entry.key)
            changed = True
        if changed:
            self._rebuild_items()

    def select_all(self) -> None:
        if not self._all_entries:
            return
        all_keys = {entry.key for entry in self._all_entries if entry.key}
        if all_keys == self._selected_keys:
            return
        self._selected_keys = all_keys
        self._rebuild_items()

    def clear_all(self) -> None:
        if not self._selected_keys:
            return
        self._selected_keys.clear()
        self._rebuild_items()

    def clear_visible(self) -> None:
        if not self._all_entries:
            return
        visible_keys = {entry.key for entry in self._filtered_entries}
        new_selected = {key for key in self._selected_keys if key not in visible_keys}
        if new_selected == self._selected_keys:
            return
        self._selected_keys = new_selected
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        if self._filter_text:
            self._filtered_entries = [
                entry
                for entry in self._all_entries
                if self._filter_text in entry.label.casefold()
            ]
        else:
            self._filtered_entries = list(self._all_entries)
        self.blockSignals(True)
        self.clear()
        if not self._filtered_entries:
            placeholder = QListWidgetItem(self._empty_text)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(placeholder)
            self.blockSignals(False)
            return

        for entry in sorted(self._filtered_entries, key=lambda item: item.label.casefold()):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            item.setData(LABEL_ROLE, entry.label)
            self._update_item_appearance(item)
            self.addItem(item)
        self.blockSignals(False)

    def selected_keys(self) -> list[str]:
        return sorted(self._selected_keys, key=str.casefold)

    def selected_available_count(self) -> int:
        if not self._all_entries:
            return 0
        available = {entry.key for entry in self._all_entries}
        return len(self._selected_keys & available)

    def available_count(self) -> int:
        return len(self._all_entries)

    def has_state(self) -> bool:
        return self._has_state

    def _toggle_item(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(key, str) or not key:
            return
        if key in self._selected_keys:
            self._selected_keys.remove(key)
        else:
            self._selected_keys.add(key)
        self._update_item_appearance(item)
        self.clearSelection()

    def _update_item_appearance(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        label = item.data(LABEL_ROLE) or ""
        selected = bool(key and key in self._selected_keys)
        item.setText(f"{self._marker} {label}" if selected else label)
        font = item.font()
        font.setBold(selected)
        item.setFont(font)


class DashboardGameCard(QFrame):
    def __init__(
        self,
        *,
        game_name: str,
        title_text: str,
        pixmap: QPixmap,
        badge_text: str,
        ribbon_text: str,
        completion_ribbon_text: str,
        completion_ribbon_color: str,
        tooltip_text: str,
        farmable: bool,
        status_kind: str,
        selected: bool,
        on_click: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._game_name = game_name
        self._on_click = on_click
        self._completion_ribbon_text = completion_ribbon_text
        self._completion_ribbon_color = completion_ribbon_color or "#08a060"
        self.setObjectName("DashboardGameCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("farmable", farmable)
        self.setProperty("status", status_kind)
        self.setProperty("selected", selected)
        self.setProperty("hovered", False)
        self.setToolTip(tooltip_text)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setColor(Qt.GlobalColor.black)
        self._shadow.setBlurRadius(10)
        self._shadow.setOffset(0, 2)
        self.setGraphicsEffect(self._shadow)

        self._hover_animation = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._hover_animation.setDuration(140)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        self.ribbon = QLabel(ribbon_text)
        self.ribbon.setObjectName("DashboardRibbon")
        self.ribbon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ribbon.setVisible(selected)
        self.ribbon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        badge_row.addWidget(self.ribbon, alignment=Qt.AlignmentFlag.AlignLeft)
        badge_row.addStretch(1)
        self.badge = QLabel(badge_text)
        self.badge.setObjectName("DashboardBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        badge_row.addWidget(self.badge)

        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.cover.setPixmap(
            pixmap.scaled(
                108,
                144,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        self.title = QLabel(title_text)
        self.title.setObjectName("DashboardTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setMaximumHeight(38)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addLayout(badge_row)
        layout.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.title)

    def set_cover_pixmap(self, pixmap: QPixmap) -> None:
        self.cover.setPixmap(
            pixmap.scaled(
                108,
                144,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self._game_name)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self.setProperty("hovered", True)
        self._restyle()
        self._animate_shadow(22)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.setProperty("hovered", False)
        self._restyle()
        self._animate_shadow(10)
        super().leaveEvent(event)

    def _animate_shadow(self, target_blur: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(float(self._shadow.blurRadius()))
        self._hover_animation.setEndValue(float(target_blur))
        self._hover_animation.start()

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self._completion_ribbon_text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        band = QPolygon(
            [
                QPoint(-24, int(h * 0.30)),
                QPoint(int(w * 0.38), -24),
                QPoint(w + 24, int(h * 0.70)),
                QPoint(int(w * 0.62), h + 24),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        band_color = QColor(self._completion_ribbon_color)
        band_color.setAlpha(228)
        painter.setBrush(band_color)
        painter.drawPolygon(band)

        painter.save()
        painter.translate(w / 2, h / 2)
        painter.rotate(-36)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(14)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            int(-w * 0.45),
            -12,
            int(w * 0.90),
            24,
            Qt.AlignmentFlag.AlignCenter,
            self._completion_ribbon_text,
        )
        painter.restore()
        painter.end()


class ImageFetchBridge(QObject):
    loaded = Signal(str, bytes)
    failed = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        icon_path = _ASSETS_DIR / "icon.ico"
        icon = QIcon()
        for candidate in (icon_path, _ASSETS_DIR / "icon.png"):
            if candidate.exists():
                probe = QIcon(str(candidate))
                if not probe.isNull():
                    icon = probe
                    break
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.config = load_config()
        if self.config.language not in TRANSLATIONS:
            self.config.language = "pt_PT"

        self.client = TwitchClient()
        self.engine = FarmEngine(self.client, self.config)
        self.latest_snapshot: FarmSnapshot | None = None
        self.available_game_entries: list[FilterEntry] = []
        self.available_channel_entries: list[FilterEntry] = []
        self.decision_by_campaign_id: dict[str, FarmDecision] = {}
        self._thumb_cache: dict[str, QPixmap] = {}
        self._oauth_hidden = bool(self.client.login_state.oauth_token)
        self._streamless_channel: str = ""
        self._streamless_failure_channel: str = ""
        self._streamless_no_target_logged = False
        self._forced_farm_channel: str = ""
        self._forced_farm_campaign_id: str = ""
        self._forced_farm_game: str = ""
        self._dashboard_game_cards: list[DashboardGameCard] = []
        self._dashboard_completed_seen_at: dict[str, datetime] = {}
        self._diag_future: Future | None = None
        self._diag_started_at: datetime | None = None
        self._diag_poll_timer = QTimer(self)
        self._diag_poll_timer.setInterval(250)
        self._diag_poll_timer.timeout.connect(self._poll_diagnostic_future)
        self._update_future: Future | None = None
        self._update_started_at: datetime | None = None
        self._update_poll_timer = QTimer(self)
        self._update_poll_timer.setInterval(250)
        self._update_poll_timer.timeout.connect(self._poll_update_future)
        self._last_refresh_at: str = ""
        self._last_auto_claim_at: datetime | None = None
        self._last_display_decision: FarmDecision | None = None
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._thumb_executor = ThreadPoolExecutor(max_workers=4)
        self._thumb_fetch_bridge = ImageFetchBridge(self)
        self._thumb_fetch_bridge.loaded.connect(self._on_box_art_loaded)
        self._thumb_fetch_bridge.failed.connect(self._on_box_art_failed)
        self._thumb_waiters: dict[str, list[tuple[object, int, int, str]]] = {}
        self._thumb_inflight: set[str] = set()
        self._generated_thumb_cache: dict[str, QPixmap] = {}

        self.resize(1280, 800)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QGridLayout(root)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 2)

        layout.addWidget(self._build_left_panel(), 0, 0)
        layout.addWidget(self._build_right_panel(), 0, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_snapshot)
        self.live_refresh_timer = QTimer(self)
        self.live_refresh_timer.setInterval(90_000)
        self.live_refresh_timer.timeout.connect(self.refresh_snapshot)
        self.streamless_timer = QTimer(self)
        self.streamless_timer.setInterval(25_000)
        self.streamless_timer.timeout.connect(self._streamless_heartbeat_tick)

        self._retranslate_ui()
        self._refresh_filter_lists()
        self._apply_theme(self.config.theme)
        self._set_oauth_hidden(self._oauth_hidden)
        self._update_auth_status()

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        self.tabs_left = QTabWidget()
        self.tabs_left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.oauth_group = QGroupBox()
        oauth_layout = QVBoxLayout(self.oauth_group)
        token_row = QHBoxLayout()
        self.oauth_token_label = QLabel()
        self.oauth_help_icon = QLabel("?")
        self.oauth_help_icon.setObjectName("HelpIcon")
        self.oauth_help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.oauth_help_icon.setFixedSize(18, 18)
        token_row.addWidget(self.oauth_token_label)
        token_row.addWidget(self.oauth_help_icon)
        token_row.addStretch(1)
        self.token_input = QLineEdit()
        self.token_input.setClearButtonEnabled(True)
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.auth_status_label = QLabel()
        self.auth_status_label.setWordWrap(True)
        oauth_buttons = QHBoxLayout()
        self.btn_login = QPushButton()
        self.btn_login.clicked.connect(self.handle_login)
        self.btn_edit_oauth = QPushButton()
        self.btn_edit_oauth.clicked.connect(self.handle_edit_oauth)
        oauth_buttons.addWidget(self.btn_login)
        oauth_buttons.addWidget(self.btn_edit_oauth)
        oauth_layout.addLayout(token_row)
        oauth_layout.addWidget(self.token_input)
        oauth_layout.addWidget(self.auth_status_label)
        oauth_layout.addLayout(oauth_buttons)

        self.preferences_group = QGroupBox()
        preferences_layout = QVBoxLayout(self.preferences_group)
        
        # Create tabbed interface for settings
        self.settings_tabs = QTabWidget()
        
        # ========== TAB 1: BÁSICO ==========
        basic_tab = QWidget()
        basic_layout = QVBoxLayout(basic_tab)
        
        language_row = QHBoxLayout()
        self.language_label = QLabel()
        self.language_picker = QComboBox()
        self.language_picker.currentIndexChanged.connect(self.handle_language_change)
        language_row.addWidget(self.language_label)
        language_row.addWidget(self.language_picker, 1)
        
        theme_row = QHBoxLayout()
        self.theme_label = QLabel()
        self.theme_picker = QComboBox()
        self.theme_picker.currentIndexChanged.connect(self.handle_theme_change)
        theme_row.addWidget(self.theme_label)
        theme_row.addWidget(self.theme_picker, 1)
        
        sort_row = QHBoxLayout()
        self.sort_label = QLabel()
        self.sort_picker = QComboBox()
        self.sort_picker.currentIndexChanged.connect(self.handle_sort_change)
        sort_row.addWidget(self.sort_label)
        sort_row.addWidget(self.sort_picker, 1)
        
        basic_layout.addLayout(language_row)
        basic_layout.addLayout(theme_row)
        basic_layout.addLayout(sort_row)
        
        self.auto_claim_checkbox = QCheckBox()
        self.auto_claim_checkbox.setChecked(bool(self.config.auto_claim_drops))
        basic_layout.addWidget(self.auto_claim_checkbox)
        basic_layout.addStretch()
        
        # ========== TAB 2: AVANÇADO ==========
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        
        # Energy Profiles
        self.energy_profile_label = QLabel()
        self.energy_profile_help_icon = QLabel("?")
        self.energy_profile_help_icon.setObjectName("HelpIcon")
        self.energy_profile_help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.energy_profile_help_icon.setFixedSize(18, 18)
        energy_profile_layout = QVBoxLayout()
        energy_profile_title = QHBoxLayout()
        energy_profile_title.addWidget(self.energy_profile_label)
        energy_profile_title.addWidget(self.energy_profile_help_icon)
        energy_profile_title.addStretch()
        
        self.energy_profile_buttons = []
        self.energy_profile_group = None
        profiles_widget = QWidget()
        profiles_buttons_layout = QHBoxLayout(profiles_widget)
        for profile in AVAILABLE_PROFILES:
            profile_name = profile.name
            btn = QRadioButton(profile_name)
            btn.setToolTip(f"Perfil: {profile_name}")
            btn.toggled.connect(lambda checked, pname=profile_name: self.handle_energy_profile_change(pname) if checked else None)
            self.energy_profile_buttons.append((profile_name, btn))
            profiles_buttons_layout.addWidget(btn)
        profiles_buttons_layout.addStretch()
        if self.energy_profile_buttons:
            active_profile = self.config.energy_profile
            for profile_name, btn in self.energy_profile_buttons:
                if profile_name == active_profile:
                    btn.setChecked(True)
                    break
        
        energy_profile_layout.addLayout(energy_profile_title)
        energy_profile_layout.addWidget(profiles_widget)
        advanced_layout.addLayout(energy_profile_layout)
        
        # Watchdog settings
        watchdog_frame = QGroupBox()
        watchdog_layout = QVBoxLayout(watchdog_frame)
        
        watchdog_enable_layout = QHBoxLayout()
        self.watchdog_label = QLabel()
        self.watchdog_help_icon = QLabel("?")
        self.watchdog_help_icon.setObjectName("HelpIcon")
        self.watchdog_help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.watchdog_help_icon.setFixedSize(18, 18)
        self.watchdog_checkbox = QCheckBox()
        self.watchdog_checkbox.setChecked(self.config.watchdog_enabled)
        self.watchdog_checkbox.toggled.connect(self.handle_watchdog_toggle)
        watchdog_enable_layout.addWidget(self.watchdog_label)
        watchdog_enable_layout.addWidget(self.watchdog_help_icon)
        watchdog_enable_layout.addWidget(self.watchdog_checkbox)
        watchdog_enable_layout.addStretch()
        
        watchdog_timeout_layout = QHBoxLayout()
        self.watchdog_timeout_label = QLabel()
        self.watchdog_timeout_help_icon = QLabel("?")
        self.watchdog_timeout_help_icon.setObjectName("HelpIcon")
        self.watchdog_timeout_help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.watchdog_timeout_help_icon.setFixedSize(18, 18)
        self.watchdog_timeout_spinbox = QSpinBox()
        self.watchdog_timeout_spinbox.setMinimum(5)
        self.watchdog_timeout_spinbox.setMaximum(120)
        self.watchdog_timeout_spinbox.setValue(self.config.watchdog_stall_timeout_min)
        self.watchdog_timeout_spinbox.setSuffix(" min")
        watchdog_timeout_layout.addWidget(self.watchdog_timeout_label)
        watchdog_timeout_layout.addWidget(self.watchdog_timeout_help_icon)
        watchdog_timeout_layout.addWidget(self.watchdog_timeout_spinbox)
        watchdog_timeout_layout.addStretch()
        
        watchdog_layout.addLayout(watchdog_enable_layout)
        watchdog_layout.addLayout(watchdog_timeout_layout)
        advanced_layout.addWidget(watchdog_frame)
        
        # Auto-update settings
        autoupdate_frame = QGroupBox()
        autoupdate_layout = QVBoxLayout(autoupdate_frame)
        
        autoupdate_enable_layout = QHBoxLayout()
        self.autoupdate_label = QLabel()
        self.autoupdate_help_icon = QLabel("?")
        self.autoupdate_help_icon.setObjectName("HelpIcon")
        self.autoupdate_help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.autoupdate_help_icon.setFixedSize(18, 18)
        self.autoupdate_checkbox = QCheckBox()
        self.autoupdate_checkbox.setChecked(self.config.auto_update_enabled)
        self.autoupdate_checkbox.toggled.connect(self.handle_autoupdate_toggle)
        autoupdate_enable_layout.addWidget(self.autoupdate_label)
        autoupdate_enable_layout.addWidget(self.autoupdate_help_icon)
        autoupdate_enable_layout.addWidget(self.autoupdate_checkbox)
        autoupdate_enable_layout.addStretch()
        
        autoupdate_delay_layout = QHBoxLayout()
        self.autoupdate_delay_label = QLabel()
        self.autoupdate_delay_help_icon = QLabel("?")
        self.autoupdate_delay_help_icon.setObjectName("HelpIcon")
        self.autoupdate_delay_help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.autoupdate_delay_help_icon.setFixedSize(18, 18)
        self.autoupdate_delay_spinbox = QSpinBox()
        self.autoupdate_delay_spinbox.setMinimum(5)
        self.autoupdate_delay_spinbox.setMaximum(300)
        self.autoupdate_delay_spinbox.setValue(self.config.auto_update_restart_delay_sec)
        self.autoupdate_delay_spinbox.setSuffix(" seg")
        autoupdate_delay_layout.addWidget(self.autoupdate_delay_label)
        autoupdate_delay_layout.addWidget(self.autoupdate_delay_help_icon)
        autoupdate_delay_layout.addWidget(self.autoupdate_delay_spinbox)
        autoupdate_delay_layout.addStretch()
        
        autoupdate_layout.addLayout(autoupdate_enable_layout)
        autoupdate_layout.addLayout(autoupdate_delay_layout)
        advanced_layout.addWidget(autoupdate_frame)
        advanced_layout.addStretch()
        
        # ========== TAB 3: ALERTAS ==========
        alerts_tab = QWidget()
        alerts_layout = QVBoxLayout(alerts_tab)
        
        alerts_grid = QGridLayout()
        self.alert_checkboxes = {}
        self.alert_help_icons = {}
        for i, alert_type in enumerate(AlertType):
            checkbox = QCheckBox(alert_type.value.replace("_", " ").title())
            is_enabled = getattr(self.config, f"alert_{alert_type.value}", True)
            checkbox.setChecked(is_enabled)
            checkbox.toggled.connect(lambda checked, at=alert_type: self.handle_alert_toggle(at, checked))
            self.alert_checkboxes[alert_type] = checkbox
            help_icon = QLabel("?")
            help_icon.setObjectName("HelpIcon")
            help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            help_icon.setFixedSize(18, 18)
            self.alert_help_icons[alert_type] = help_icon

            option_widget = QWidget()
            option_layout = QHBoxLayout(option_widget)
            option_layout.setContentsMargins(0, 0, 0, 0)
            option_layout.setSpacing(6)
            option_layout.addWidget(checkbox)
            option_layout.addWidget(help_icon)
            option_layout.addStretch()
            alerts_grid.addWidget(option_widget, i // 2, i % 2)
        
        alerts_layout.addLayout(alerts_grid)
        alerts_layout.addStretch()
        
        # Add tabs
        self.settings_tabs.addTab(basic_tab, "")  # "Básico" will be set in retranslate
        self.settings_tabs.addTab(advanced_tab, "")  # "Avançado"
        self.settings_tabs.addTab(alerts_tab, "")  # "Alertas"
        
        preferences_layout.addWidget(self.settings_tabs)
        
        # Action buttons (outside tabs)
        buttons_layout = QHBoxLayout()
        self.btn_diagnostic = QPushButton()
        self.btn_diagnostic.clicked.connect(self.handle_run_diagnostic)
        self.btn_check_updates = QPushButton()
        self.btn_check_updates.clicked.connect(self.handle_check_updates)
        buttons_layout.addWidget(self.btn_diagnostic)
        buttons_layout.addWidget(self.btn_check_updates)
        buttons_layout.addStretch()
        preferences_layout.addLayout(buttons_layout)
        
        self.update_status_label = QLabel()
        self.update_status_label.setWordWrap(True)
        preferences_layout.addWidget(self.update_status_label)

        # Session-based authentication group
        self.session_group = QGroupBox()
        session_layout = QVBoxLayout(self.session_group)
        self.session_export_label = QLabel()
        self.session_export_label.setWordWrap(True)
        self.btn_export_session = QPushButton()
        self.btn_export_session.clicked.connect(self.handle_export_session)
        self.session_import_label = QLabel()
        self.session_import_label.setWordWrap(True)
        self.session_input = QTextEdit()
        self.session_input.setPlaceholderText("Colas aqui o JSON da sessão exportada do browser...")
        self.session_input.setMaximumHeight(100)
        self.session_auth_status_label = QLabel()
        self.session_auth_status_label.setWordWrap(True)
        session_buttons = QHBoxLayout()
        self.btn_import_session = QPushButton()
        self.btn_import_session.clicked.connect(self.handle_import_session)
        self.btn_validate_session = QPushButton()
        self.btn_validate_session.clicked.connect(self.handle_validate_session)
        session_buttons.addWidget(self.btn_import_session)
        session_buttons.addWidget(self.btn_validate_session)
        session_layout.addWidget(self.session_export_label)
        session_layout.addWidget(self.btn_export_session)
        session_layout.addWidget(self.session_import_label)
        session_layout.addWidget(self.session_input)
        session_layout.addWidget(self.session_auth_status_label)
        session_layout.addLayout(session_buttons)

        self.active_lists_note = QLabel()
        self.active_lists_note.setWordWrap(True)
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(self.refresh_snapshot)
        self.filters_hint = QLabel()
        self.filters_hint.setWordWrap(True)

        self.games_whitelist_group = QGroupBox()
        games_whitelist_layout = QVBoxLayout(self.games_whitelist_group)
        self.games_whitelist_hint = QLabel()
        self.games_whitelist_hint.setWordWrap(True)
        self.games_whitelist_list = MarkerListWidget("✓")
        self.games_whitelist_list.itemClicked.connect(lambda _item: self._with_errors(self._handle_games_whitelist_selection_changed))
        self.games_whitelist_search = QLineEdit()
        self.games_whitelist_search.textChanged.connect(self.games_whitelist_list.set_filter_text)
        self.games_whitelist_select_all_btn = QPushButton()
        self.games_whitelist_select_all_btn.clicked.connect(self.games_whitelist_list.select_all)
        self.games_whitelist_select_all_btn.clicked.connect(lambda: self._with_errors(self._handle_games_whitelist_selection_changed))
        self.games_whitelist_clear_all_btn = QPushButton()
        self.games_whitelist_clear_all_btn.clicked.connect(self.games_whitelist_list.clear_all)
        self.games_whitelist_clear_all_btn.clicked.connect(lambda: self._with_errors(self._handle_games_whitelist_selection_changed))
        self.games_whitelist_select_visible_btn = QPushButton()
        self.games_whitelist_select_visible_btn.clicked.connect(self.games_whitelist_list.select_visible)
        self.games_whitelist_select_visible_btn.clicked.connect(lambda: self._with_errors(self._handle_games_whitelist_selection_changed))
        self.games_whitelist_clear_visible_btn = QPushButton()
        self.games_whitelist_clear_visible_btn.clicked.connect(self.games_whitelist_list.clear_visible)
        self.games_whitelist_clear_visible_btn.clicked.connect(lambda: self._with_errors(self._handle_games_whitelist_selection_changed))
        games_whitelist_actions = QHBoxLayout()
        games_whitelist_actions.addWidget(self.games_whitelist_select_all_btn)
        games_whitelist_actions.addWidget(self.games_whitelist_clear_all_btn)
        games_whitelist_actions.addWidget(self.games_whitelist_select_visible_btn)
        games_whitelist_actions.addWidget(self.games_whitelist_clear_visible_btn)
        games_whitelist_layout.addWidget(self.games_whitelist_hint)
        games_whitelist_layout.addWidget(self.games_whitelist_search)
        games_whitelist_layout.addLayout(games_whitelist_actions)
        games_whitelist_layout.addWidget(self.games_whitelist_list)

        self.games_blacklist_group = QGroupBox()
        games_blacklist_layout = QVBoxLayout(self.games_blacklist_group)
        self.games_blacklist_hint = QLabel()
        self.games_blacklist_hint.setWordWrap(True)
        self.games_blacklist_list = MarkerListWidget("X")
        self.games_blacklist_list.itemClicked.connect(lambda _item: self._refresh_filter_tab_counts())
        self.games_blacklist_search = QLineEdit()
        self.games_blacklist_search.textChanged.connect(self.games_blacklist_list.set_filter_text)
        self.games_blacklist_select_all_btn = QPushButton()
        self.games_blacklist_select_all_btn.clicked.connect(self.games_blacklist_list.select_all)
        self.games_blacklist_select_all_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.games_blacklist_clear_all_btn = QPushButton()
        self.games_blacklist_clear_all_btn.clicked.connect(self.games_blacklist_list.clear_all)
        self.games_blacklist_clear_all_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.games_blacklist_select_visible_btn = QPushButton()
        self.games_blacklist_select_visible_btn.clicked.connect(self.games_blacklist_list.select_visible)
        self.games_blacklist_select_visible_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.games_blacklist_clear_visible_btn = QPushButton()
        self.games_blacklist_clear_visible_btn.clicked.connect(self.games_blacklist_list.clear_visible)
        self.games_blacklist_clear_visible_btn.clicked.connect(self._refresh_filter_tab_counts)
        games_blacklist_actions = QHBoxLayout()
        games_blacklist_actions.addWidget(self.games_blacklist_select_all_btn)
        games_blacklist_actions.addWidget(self.games_blacklist_clear_all_btn)
        games_blacklist_actions.addWidget(self.games_blacklist_select_visible_btn)
        games_blacklist_actions.addWidget(self.games_blacklist_clear_visible_btn)
        games_blacklist_layout.addWidget(self.games_blacklist_hint)
        games_blacklist_layout.addWidget(self.games_blacklist_search)
        games_blacklist_layout.addLayout(games_blacklist_actions)
        games_blacklist_layout.addWidget(self.games_blacklist_list)

        self.channels_whitelist_group = QGroupBox()
        channels_whitelist_layout = QVBoxLayout(self.channels_whitelist_group)
        self.channels_whitelist_hint = QLabel()
        self.channels_whitelist_hint.setWordWrap(True)
        self.channels_whitelist_list = MarkerListWidget("✓")
        self.channels_whitelist_list.itemClicked.connect(lambda _item: self._refresh_filter_tab_counts())
        self.channels_whitelist_search = QLineEdit()
        self.channels_whitelist_search.textChanged.connect(self.channels_whitelist_list.set_filter_text)
        self.channels_whitelist_select_all_btn = QPushButton()
        self.channels_whitelist_select_all_btn.clicked.connect(self.channels_whitelist_list.select_all)
        self.channels_whitelist_select_all_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.channels_whitelist_clear_all_btn = QPushButton()
        self.channels_whitelist_clear_all_btn.clicked.connect(self.channels_whitelist_list.clear_all)
        self.channels_whitelist_clear_all_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.channels_whitelist_select_visible_btn = QPushButton()
        self.channels_whitelist_select_visible_btn.clicked.connect(self.channels_whitelist_list.select_visible)
        self.channels_whitelist_select_visible_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.channels_whitelist_clear_visible_btn = QPushButton()
        self.channels_whitelist_clear_visible_btn.clicked.connect(self.channels_whitelist_list.clear_visible)
        self.channels_whitelist_clear_visible_btn.clicked.connect(self._refresh_filter_tab_counts)
        channels_whitelist_actions = QHBoxLayout()
        channels_whitelist_actions.addWidget(self.channels_whitelist_select_all_btn)
        channels_whitelist_actions.addWidget(self.channels_whitelist_clear_all_btn)
        channels_whitelist_actions.addWidget(self.channels_whitelist_select_visible_btn)
        channels_whitelist_actions.addWidget(self.channels_whitelist_clear_visible_btn)
        channels_whitelist_layout.addWidget(self.channels_whitelist_hint)
        channels_whitelist_layout.addWidget(self.channels_whitelist_search)
        channels_whitelist_layout.addLayout(channels_whitelist_actions)
        channels_whitelist_layout.addWidget(self.channels_whitelist_list)

        self.channels_blacklist_group = QGroupBox()
        channels_blacklist_layout = QVBoxLayout(self.channels_blacklist_group)
        self.channels_blacklist_hint = QLabel()
        self.channels_blacklist_hint.setWordWrap(True)
        self.channels_blacklist_list = MarkerListWidget("X")
        self.channels_blacklist_list.itemClicked.connect(lambda _item: self._refresh_filter_tab_counts())
        self.channels_blacklist_search = QLineEdit()
        self.channels_blacklist_search.textChanged.connect(self.channels_blacklist_list.set_filter_text)
        self.channels_blacklist_select_all_btn = QPushButton()
        self.channels_blacklist_select_all_btn.clicked.connect(self.channels_blacklist_list.select_all)
        self.channels_blacklist_select_all_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.channels_blacklist_clear_all_btn = QPushButton()
        self.channels_blacklist_clear_all_btn.clicked.connect(self.channels_blacklist_list.clear_all)
        self.channels_blacklist_clear_all_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.channels_blacklist_select_visible_btn = QPushButton()
        self.channels_blacklist_select_visible_btn.clicked.connect(self.channels_blacklist_list.select_visible)
        self.channels_blacklist_select_visible_btn.clicked.connect(self._refresh_filter_tab_counts)
        self.channels_blacklist_clear_visible_btn = QPushButton()
        self.channels_blacklist_clear_visible_btn.clicked.connect(self.channels_blacklist_list.clear_visible)
        self.channels_blacklist_clear_visible_btn.clicked.connect(self._refresh_filter_tab_counts)
        channels_blacklist_actions = QHBoxLayout()
        channels_blacklist_actions.addWidget(self.channels_blacklist_select_all_btn)
        channels_blacklist_actions.addWidget(self.channels_blacklist_clear_all_btn)
        channels_blacklist_actions.addWidget(self.channels_blacklist_select_visible_btn)
        channels_blacklist_actions.addWidget(self.channels_blacklist_clear_visible_btn)
        channels_blacklist_layout.addWidget(self.channels_blacklist_hint)
        channels_blacklist_layout.addWidget(self.channels_blacklist_search)
        channels_blacklist_layout.addLayout(channels_blacklist_actions)
        channels_blacklist_layout.addWidget(self.channels_blacklist_list)

        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self.handle_save_config)
        self.btn_start = QPushButton()
        self.btn_start.clicked.connect(self.handle_start)
        self.btn_stop = QPushButton()
        self.btn_stop.clicked.connect(self.handle_stop)
        self.btn_stop.setEnabled(False)

        dashboard_tab = QWidget()
        dashboard_layout = QVBoxLayout(dashboard_tab)
        self.dashboard_group = QGroupBox()
        self.dashboard_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        dashboard_group_layout = QVBoxLayout(self.dashboard_group)
        self.dashboard_hint_label = QLabel()
        self.dashboard_hint_label.setWordWrap(True)
        self.dashboard_hide_sub_only_checkbox = QCheckBox()
        self.dashboard_hide_sub_only_checkbox.setChecked(
            bool(getattr(self.config, "dashboard_hide_subscription_required", False))
        )
        self.dashboard_hide_sub_only_checkbox.toggled.connect(self.handle_dashboard_hide_sub_only_toggle)
        self.btn_dashboard_refresh = QPushButton()
        self.btn_dashboard_refresh.clicked.connect(self.handle_dashboard_refresh)
        dashboard_actions_layout = QHBoxLayout()
        dashboard_actions_layout.addWidget(self.dashboard_hide_sub_only_checkbox)
        dashboard_actions_layout.addStretch(1)
        dashboard_actions_layout.addWidget(self.btn_dashboard_refresh)
        self.dashboard_games_scroll = QScrollArea()
        self.dashboard_games_scroll.setWidgetResizable(True)
        self.dashboard_games_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.dashboard_games_scroll.setMinimumHeight(252)
        self.dashboard_games_container = QWidget()
        self.dashboard_games_grid = QGridLayout(self.dashboard_games_container)
        self.dashboard_games_grid.setContentsMargins(0, 0, 0, 0)
        self.dashboard_games_grid.setHorizontalSpacing(12)
        self.dashboard_games_grid.setVerticalSpacing(12)
        self.dashboard_games_scroll.setWidget(self.dashboard_games_container)
        self.dashboard_no_games = QLabel()
        self.dashboard_no_games.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dashboard_no_games.setWordWrap(True)
        dashboard_group_layout.addWidget(self.dashboard_hint_label)
        dashboard_group_layout.addLayout(dashboard_actions_layout)
        dashboard_group_layout.addWidget(self.dashboard_games_scroll, 1)
        self.dashboard_target_label = QLabel()
        self.dashboard_target_label.setWordWrap(True)
        dashboard_layout.addWidget(self.dashboard_group, 1)
        dashboard_layout.addWidget(self.dashboard_target_label)

        # Account tab with internal tabs for different auth methods
        account_tab = QWidget()
        account_layout = QVBoxLayout(account_tab)
        
        self.auth_tabs = QTabWidget()
        quick_auth_tab = QWidget()
        quick_auth_layout = QVBoxLayout(quick_auth_tab)
        quick_auth_layout.addWidget(self.oauth_group)
        quick_auth_layout.addStretch(1)
        
        session_auth_tab = QWidget()
        session_auth_layout = QVBoxLayout(session_auth_tab)
        session_auth_layout.addWidget(self.session_group)
        session_auth_layout.addStretch(1)
        
        self.auth_tabs.addTab(session_auth_tab, "")
        self.auth_tabs.addTab(quick_auth_tab, "")
        
        account_layout.addWidget(self.auth_tabs)
        account_layout.addStretch(1)

        filters_tab = QWidget()
        filters_layout = QVBoxLayout(filters_tab)
        self.filters_tabs = QTabWidget()
        games_whitelist_tab = QWidget()
        games_whitelist_tab_layout = QVBoxLayout(games_whitelist_tab)
        games_whitelist_tab_layout.addWidget(self.games_whitelist_group)
        games_blacklist_tab = QWidget()
        games_blacklist_tab_layout = QVBoxLayout(games_blacklist_tab)
        games_blacklist_tab_layout.addWidget(self.games_blacklist_group)
        channels_whitelist_tab = QWidget()
        channels_whitelist_tab_layout = QVBoxLayout(channels_whitelist_tab)
        channels_whitelist_tab_layout.addWidget(self.channels_whitelist_group)
        channels_blacklist_tab = QWidget()
        channels_blacklist_tab_layout = QVBoxLayout(channels_blacklist_tab)
        channels_blacklist_tab_layout.addWidget(self.channels_blacklist_group)
        self.filters_tabs.addTab(games_whitelist_tab, "")
        self.filters_tabs.addTab(games_blacklist_tab, "")
        self.filters_tabs.addTab(channels_whitelist_tab, "")
        self.filters_tabs.addTab(channels_blacklist_tab, "")
        filters_layout.addWidget(self.active_lists_note)
        filters_layout.addWidget(self.filters_hint)
        filters_layout.addWidget(self.btn_refresh)
        filters_layout.addWidget(self.filters_tabs, 1)

        control_tab = QWidget()
        control_layout = QVBoxLayout(control_tab)
        control_layout.addWidget(self.preferences_group)
        control_layout.addWidget(self.btn_save)
        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        control_layout.addStretch(1)

        self.tabs_left.addTab(dashboard_tab, "")
        self.tabs_left.addTab(account_tab, "")
        self.tabs_left.addTab(filters_tab, "")
        self.tabs_left.addTab(control_tab, "")

        vbox.addWidget(self.tabs_left, 1)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)

        self.tabs_right = QTabWidget()

        farming_tab = QWidget()
        farming_layout = QVBoxLayout(farming_tab)
        self.farming_now_group = QGroupBox()
        farming_group_layout = QVBoxLayout(self.farming_now_group)
        farming_header_layout = QHBoxLayout()
        self.farming_now_game_image = QLabel()
        self.farming_now_game_image.setFixedSize(144, 192)
        self.farming_now_game_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        farming_header_layout.addWidget(self.farming_now_game_image, alignment=Qt.AlignmentFlag.AlignTop)

        farming_info_layout = QVBoxLayout()
        self.farming_now_game = QLabel()
        self.farming_now_campaign = QLabel()
        self.farming_now_channel = QLabel()
        self.farming_now_next_drop = QLabel()
        self.farming_now_eta = QLabel()
        self.farming_now_state = QLabel()
        self.farming_now_progress_text = QLabel()
        self.farming_now_progress = QProgressBar()
        self.farming_now_progress.setRange(0, 1000)
        self.farming_now_last_refresh = QLabel()
        self.btn_farming_start = QPushButton()
        self.btn_farming_start.clicked.connect(self.handle_start)
        self.btn_farming_pause = QPushButton()
        self.btn_farming_pause.clicked.connect(self.handle_stop)
        self.btn_farming_next = QPushButton()
        self.btn_farming_next.clicked.connect(self.handle_next_game)
        self.btn_redeem_drops = QPushButton()
        self.btn_redeem_drops.clicked.connect(self.handle_redeem_drops)
        farming_action_row = QHBoxLayout()
        farming_action_row.addWidget(self.btn_farming_start)
        farming_action_row.addWidget(self.btn_farming_pause)
        farming_action_row.addWidget(self.btn_farming_next)
        farming_action_row.addWidget(self.btn_redeem_drops)
        farming_info_layout.addWidget(self.farming_now_game)
        farming_info_layout.addWidget(self.farming_now_campaign)
        farming_info_layout.addWidget(self.farming_now_channel)
        farming_info_layout.addWidget(self.farming_now_next_drop)
        farming_info_layout.addWidget(self.farming_now_eta)
        farming_info_layout.addWidget(self.farming_now_state)
        farming_info_layout.addWidget(self.farming_now_progress_text)
        farming_info_layout.addStretch(1)
        farming_header_layout.addLayout(farming_info_layout, 1)
        farming_group_layout.addLayout(farming_header_layout)
        farming_group_layout.addWidget(self.farming_now_progress)
        farming_group_layout.addWidget(self.farming_now_last_refresh)
        farming_group_layout.addLayout(farming_action_row)
        farming_layout.addWidget(self.farming_now_group)

        self.active_drops_group = QGroupBox()
        self.active_drops_group.setMinimumHeight(210)
        active_drops_layout = QVBoxLayout(self.active_drops_group)
        self.active_drops_list = QListWidget()
        self.active_drops_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.active_drops_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.active_drops_list.setWordWrap(True)
        self.active_drops_list.setSpacing(6)
        self.active_drops_list.setFlow(QListView.Flow.LeftToRight)
        self.active_drops_list.setWrapping(False)
        self.active_drops_list.setMovement(QListView.Movement.Static)
        self.active_drops_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.active_drops_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.active_drops_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.active_drops_list.setMinimumHeight(140)
        active_drops_layout.addWidget(self.active_drops_list)
        farming_layout.addWidget(self.active_drops_group)
        farming_layout.addStretch(1)

        campaigns_tab = QWidget()
        campaigns_layout = QVBoxLayout(campaigns_tab)
        filter_row = QHBoxLayout()
        self.filter_status_label = QLabel()
        self.filter_status_picker = QComboBox()
        self.filter_status_picker.currentIndexChanged.connect(self._handle_campaign_filters_changed)
        self.filter_link_label = QLabel()
        self.filter_link_picker = QComboBox()
        self.filter_link_picker.currentIndexChanged.connect(self._handle_campaign_filters_changed)
        self.campaign_sort_label = QLabel()
        self.campaign_sort_picker = QComboBox()
        self.campaign_sort_picker.currentIndexChanged.connect(self._handle_campaign_filters_changed)
        filter_row.addWidget(self.filter_status_label)
        filter_row.addWidget(self.filter_status_picker, 1)
        filter_row.addWidget(self.filter_link_label)
        filter_row.addWidget(self.filter_link_picker, 1)
        filter_row.addWidget(self.campaign_sort_label)
        filter_row.addWidget(self.campaign_sort_picker, 1)

        self.best_target_label = QLabel()
        self.best_target_label.setWordWrap(True)
        self.campaigns_label = QLabel()
        self.campaign_list = QListWidget()
        self.campaign_list.itemSelectionChanged.connect(self.handle_campaign_selection_changed)
        self.campaign_details_label = QLabel()
        self.campaign_details_label.setWordWrap(True)
        link_row = QHBoxLayout()
        self.btn_link_account = QPushButton()
        self.btn_link_account.clicked.connect(self.handle_link_account)
        self.btn_open_drops_page = QPushButton()
        self.btn_open_drops_page.clicked.connect(self.handle_open_drops_page)
        link_row.addWidget(self.btn_link_account)
        link_row.addWidget(self.btn_open_drops_page)
        self.log_label = QLabel()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        campaigns_layout.addWidget(self.best_target_label)
        campaigns_layout.addLayout(filter_row)
        campaigns_layout.addWidget(self.campaigns_label)
        campaigns_layout.addWidget(self.campaign_list, 2)
        campaigns_layout.addWidget(self.campaign_details_label)
        campaigns_layout.addLayout(link_row)

        self.tabs_right.addTab(farming_tab, "")
        self.tabs_right.addTab(campaigns_tab, "")
        vbox.addWidget(self.tabs_right, 3)
        vbox.addWidget(self.log_label)
        vbox.addWidget(self.log_output, 1)
        version_row = QHBoxLayout()
        version_row.addStretch(1)
        self.version_corner_label = QLabel()
        version_font = QFont(self.version_corner_label.font())
        version_font.setPointSize(8)
        self.version_corner_label.setFont(version_font)
        self.version_corner_label.setStyleSheet("color: #8f95a3;")
        version_row.addWidget(self.version_corner_label)
        vbox.addLayout(version_row)
        return panel

    def _t(self, key: str, **kwargs: object) -> str:
        language = self.config.language if self.config.language in TRANSLATIONS else "en"
        template = TRANSLATIONS.get(language, TRANSLATIONS["en"]).get(key, key)
        return template.format(**kwargs)

    def _current_sort_mode(self) -> str:
        value = self.sort_picker.currentData()
        return value if isinstance(value, str) else self.config.sort_mode

    def _current_language(self) -> str:
        value = self.language_picker.currentData()
        return value if isinstance(value, str) else self.config.language

    def _current_theme(self) -> str:
        value = self.theme_picker.currentData()
        return value if isinstance(value, str) else self.config.theme

    def _selected_values(self, widget: MarkerListWidget, fallback: list[str]) -> list[str]:
        if widget.has_state():
            return widget.selected_keys()
        return list(fallback)

    def _dashboard_whitelist_games(self) -> list[str]:
        raw = self._selected_values(self.games_whitelist_list, self.config.whitelist_games)
        key_to_label = {entry.key.casefold(): entry.label for entry in self.available_game_entries}
        label_lookup = {entry.label.casefold(): entry.label for entry in self.available_game_entries}
        output: list[str] = []
        seen: set[str] = set()
        for game in raw:
            token = (game or "").strip()
            if not token:
                continue
            normalized = token.casefold()
            resolved_label = key_to_label.get(normalized) or label_lookup.get(normalized) or token
            marker = resolved_label.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            output.append(resolved_label)
        output.sort(key=str.casefold)
        return output

    def _dashboard_card_title(self, game_name: str) -> str:
        cleaned = " ".join(game_name.split())
        if len(cleaned) <= 32:
            midpoint = len(cleaned) // 2
            split = cleaned.rfind(" ", 0, midpoint + 1)
            if split <= 0:
                return cleaned
            first = cleaned[:split].strip()
            second = cleaned[split + 1:].strip()
            if len(first) <= 16 and len(second) <= 16:
                return f"{first}\n{second}"
            return cleaned
        truncated = cleaned[:29].rstrip()
        if " " in truncated:
            truncated = truncated[:truncated.rfind(" ")]
        truncated = (truncated or cleaned[:29]).rstrip()
        midpoint = len(truncated) // 2
        split = truncated.rfind(" ", 0, midpoint + 1)
        if split <= 0:
            return f"{truncated}..."
        return f"{truncated[:split].strip()}\n{truncated[split + 1:].strip()}..."

    def _set_farming_controls(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_farming_start.setEnabled(not running)
        self.btn_farming_pause.setEnabled(running)
        self.btn_farming_next.setEnabled(running)
        self.farming_now_state.setText(self._t("farming_state_running") if running else self._t("farming_state_stopped"))

    def _refresh_last_update_label(self) -> None:
        if self._last_refresh_at:
            self.farming_now_last_refresh.setText(
                self._t("farming_last_refresh", time=self._last_refresh_at)
            )
        else:
            self.farming_now_last_refresh.setText(self._t("farming_last_refresh_never"))

    def _selected_decision(self) -> FarmDecision | None:
        item = self.campaign_list.currentItem()
        if item is None:
            return None
        campaign_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(campaign_id, str):
            return None
        return self.decision_by_campaign_id.get(campaign_id)

    def _masked_token_text(self) -> str:
        if not self.client.login_state.oauth_token:
            return ""
        token = self.client.login_state.oauth_token
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}{'*' * max(4, len(token) - 8)}{token[-4:]}"

    def _normalize_marker_text(self, text: str) -> str:
        return text.replace("âœ“", CHECK_MARK)

    def _set_oauth_hidden(self, hidden: bool) -> None:
        self._oauth_hidden = hidden
        if hidden and self.client.login_state.oauth_token:
            self.token_input.setText(self._masked_token_text())
            self.token_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.token_input.setReadOnly(True)
            self.btn_login.setEnabled(False)
        else:
            self.token_input.setText("")
            self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.token_input.setReadOnly(False)
            self.btn_login.setEnabled(True)
        self.btn_edit_oauth.setEnabled(bool(self.client.login_state.oauth_token))

    def _update_auth_status(self) -> None:
        state = self.client.login_state
        if state.logged_in:
            self.auth_status_label.setText(
                self._t("auth_valid", login=state.login_name or "unknown", user_id=state.user_id or "?")
            )
        elif state.oauth_token:
            self.auth_status_label.setText(self._t("auth_saved_hidden") if self._oauth_hidden else self._t("auth_invalid"))
        else:
            self.auth_status_label.setText(self._t("auth_not_saved"))
        
        # Update session status
        if state.logged_in:
            self.session_auth_status_label.setText(
                self._t("session_auth_status", status=f"{state.login_name} ({state.user_id})")
            )
        elif state.login_name:
            self.session_auth_status_label.setText(
                self._t("session_imported_hidden")
            )
        else:
            self.session_auth_status_label.setText(self._t("session_not_imported"))

    def _repopulate_language_picker(self) -> None:
        current = self.config.language
        self.language_picker.blockSignals(True)
        self.language_picker.clear()
        for code, label in LANGUAGE_OPTIONS:
            self.language_picker.addItem(label, code)
        index = self.language_picker.findData(current)
        if index >= 0:
            self.language_picker.setCurrentIndex(index)
        self.language_picker.blockSignals(False)

    def _repopulate_theme_picker(self) -> None:
        current = self.config.theme
        self.theme_picker.blockSignals(True)
        self.theme_picker.clear()
        for theme_name in sorted(THEMES.keys()):
            self.theme_picker.addItem(self._t(f"theme_{theme_name}"), theme_name)
        index = self.theme_picker.findData(current)
        if index >= 0:
            self.theme_picker.setCurrentIndex(index)
        self.theme_picker.blockSignals(False)

    def _repopulate_sort_picker(self) -> None:
        current = self.config.sort_mode
        self.sort_picker.blockSignals(True)
        self.sort_picker.clear()
        for mode in SORT_MODE_OPTIONS:
            self.sort_picker.addItem(self._t(f"sort_{mode}"), mode)
        index = self.sort_picker.findData(current)
        if index >= 0:
            self.sort_picker.setCurrentIndex(index)
        self.sort_picker.blockSignals(False)

    def _refresh_filter_lists(self) -> None:
        games_whitelist = self._selected_values(self.games_whitelist_list, self.config.whitelist_games)
        games_blacklist = self._selected_values(self.games_blacklist_list, self.config.blacklist_games)
        channels_whitelist = self._selected_values(self.channels_whitelist_list, self.config.whitelist_channels)
        channels_blacklist = self._selected_values(self.channels_blacklist_list, self.config.blacklist_channels)

        self.games_whitelist_list.set_entries(self.available_game_entries, games_whitelist, self._t("no_active_games"))
        self.games_blacklist_list.set_entries(self.available_game_entries, games_blacklist, self._t("no_active_games"))
        self.channels_whitelist_list.set_entries(self.available_channel_entries, channels_whitelist, self._t("no_active_channels"))
        self.channels_blacklist_list.set_entries(self.available_channel_entries, channels_blacklist, self._t("no_active_channels"))
        self._refresh_filter_tab_counts()

    def _refresh_filter_tab_counts(self) -> None:
        self.filters_tabs.setTabText(
            0,
            self._t(
                "filter_tab_games_whitelist_count",
                selected=self.games_whitelist_list.selected_available_count(),
                total=self.games_whitelist_list.available_count(),
            ),
        )
        self.filters_tabs.setTabText(
            1,
            self._t(
                "filter_tab_games_blacklist_count",
                selected=self.games_blacklist_list.selected_available_count(),
                total=self.games_blacklist_list.available_count(),
            ),
        )
        self.filters_tabs.setTabText(
            2,
            self._t(
                "filter_tab_channels_whitelist_count",
                selected=self.channels_whitelist_list.selected_available_count(),
                total=self.channels_whitelist_list.available_count(),
            ),
        )
        self.filters_tabs.setTabText(
            3,
            self._t(
                "filter_tab_channels_blacklist_count",
                selected=self.channels_blacklist_list.selected_available_count(),
                total=self.channels_blacklist_list.available_count(),
            ),
        )

    def _handle_games_whitelist_selection_changed(self) -> None:
        self._refresh_dashboard_games()
        self._refresh_filter_tab_counts()

    def _refresh_dashboard_games(self) -> None:
        # Render dashboard using the original GameCard visual format.
        self._refresh_dashboard()
        self._refresh_dashboard_hide_sub_only_label()

        whitelist_games = self._dashboard_whitelist_games()
        if not whitelist_games:
            self.dashboard_target_label.setText(self._t("dashboard_empty"))
            return
        if self._forced_farm_game:
            self.dashboard_target_label.setText(self._t("dashboard_selected", game=self._forced_farm_game))
            return
        self.dashboard_target_label.setText(self._t("dashboard_unset"))

    def _refresh_dashboard_hide_sub_only_label(self) -> None:
        base = self._t("dashboard_hide_sub_only")
        count = 0
        if self.latest_snapshot is not None:
            count = sum(
                1
                for campaign in self.latest_snapshot.campaigns
                if self._campaign_matches_hide_sub_only(campaign) and not campaign.all_drops_claimed
            )
        self.dashboard_hide_sub_only_checkbox.setText(f"{base} ({count})")

    def _refresh_campaigns_label(self) -> None:
        count = len(self._filtered_decisions()) if self.latest_snapshot else 0
        if count:
            self.campaigns_label.setText(self._t("campaigns_detected_count", count=count))
        else:
            self.campaigns_label.setText(self._t("campaigns_detected"))

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self._t("window_title"))
        self.tabs_left.setTabText(0, self._t("tab_dashboard"))
        self.tabs_left.setTabText(1, self._t("tab_account"))
        self.tabs_left.setTabText(2, self._t("tab_filters"))
        self.tabs_left.setTabText(3, self._t("tab_settings"))
        self.tabs_left.setTabText(0, self._t("tab_dashboard"))
        self.tabs_left.setTabText(1, self._t("tab_account"))
        self.tabs_left.setTabText(2, self._t("tab_filters"))
        self.tabs_left.setTabText(3, self._t("tab_settings"))
        self.tabs_right.setTabText(0, self._t("tab_farming_now"))
        self.tabs_right.setTabText(1, self._t("tab_campaign_explorer"))
        
        self.auth_tabs.setTabText(0, self._t("auth_session_export"))
        self.auth_tabs.setTabText(1, self._t("auth_quick_token"))
        self.version_corner_label.setText(self._t("version_corner", version=__version__))

        self.dashboard_group.setTitle(self._t("dashboard_group"))
        self.dashboard_hint_label.setText(self._t("dashboard_hint"))
        self._refresh_dashboard_hide_sub_only_label()
        self.dashboard_hide_sub_only_checkbox.setToolTip(self._t("dashboard_hide_sub_only_help"))
        self.btn_dashboard_refresh.setText(self._t("dashboard_refresh"))
        
        self.oauth_group.setTitle(self._t("oauth_group"))
        self.oauth_token_label.setText(self._t("oauth_token_label"))
        self.token_input.setPlaceholderText(self._t("oauth_placeholder"))
        self.oauth_help_icon.setToolTip(self._t("oauth_help"))
        self.btn_login.setText(self._t("save_oauth"))
        self.btn_edit_oauth.setText(self._t("edit_oauth"))

        self.session_group.setTitle(self._t("session_group"))
        self.session_export_label.setText(self._t("session_export_label"))
        self.btn_export_session.setText(self._t("btn_export_session"))
        self.session_import_label.setText(self._t("session_import_label"))
        self.btn_import_session.setText(self._t("btn_import_session"))
        self.btn_validate_session.setText(self._t("btn_validate_session"))

        self.preferences_group.setTitle(self._t("preferences_group"))
        self.language_label.setText(self._t("language_label"))
        self.theme_label.setText(self._t("theme_label"))
        self.sort_label.setText(self._t("sort_label"))
        self.auto_claim_checkbox.setText(self._t("auto_claim_checkbox"))
        self._repopulate_language_picker()
        self._repopulate_theme_picker()
        self._repopulate_sort_picker()

        # v2 translations - Settings Tabs
        self.settings_tabs.setTabText(0, self._t("settings_tab_basic"))
        self.settings_tabs.setTabText(1, self._t("settings_tab_advanced"))
        self.settings_tabs.setTabText(2, self._t("settings_tab_alerts"))
        
        self.energy_profile_label.setText(self._t("energy_profile_label"))
        self.energy_profile_help_icon.setToolTip(self._t("help_energy_profile"))
        self.watchdog_label.setText(self._t("watchdog_enabled"))
        self.watchdog_help_icon.setToolTip(self._t("help_watchdog"))
        self.watchdog_timeout_label.setText(self._t("watchdog_timeout"))
        self.watchdog_timeout_help_icon.setToolTip(self._t("help_watchdog_timeout"))
        self.autoupdate_label.setText(self._t("autoupdate_enabled"))
        self.autoupdate_help_icon.setToolTip(self._t("help_autoupdate"))
        self.autoupdate_delay_label.setText(self._t("autoupdate_delay"))
        self.autoupdate_delay_help_icon.setToolTip(self._t("help_autoupdate_delay"))
        self.btn_diagnostic.setText(self._t("btn_diagnostic"))
        self.btn_check_updates.setText(self._t("btn_check_updates"))
        for alert_type, checkbox in self.alert_checkboxes.items():
            checkbox.setText(self._t(f"alert_type_{alert_type.value}"))
        for alert_type, help_icon in self.alert_help_icons.items():
            help_icon.setToolTip(self._t(f"alert_help_{alert_type.value}"))

        self.active_lists_note.setText(self._t("active_lists_note"))
        self.filters_hint.setText(self._t("filters_hint"))
        self.btn_refresh.setText(self._t("refresh_active"))
        self.games_whitelist_group.setTitle(self._t("games_whitelist_group"))
        self.games_whitelist_hint.setText(self._normalize_marker_text(self._t("games_whitelist_hint", mark=CHECK_MARK)))
        self.games_whitelist_search.setPlaceholderText(self._t("filters_search_games"))
        self.games_whitelist_select_all_btn.setText(self._t("filters_select_all"))
        self.games_whitelist_clear_all_btn.setText(self._t("filters_clear_all"))
        self.games_whitelist_select_visible_btn.setText(self._t("filters_select_visible"))
        self.games_whitelist_clear_visible_btn.setText(self._t("filters_clear_visible"))
        self.games_blacklist_group.setTitle(self._t("games_blacklist_group"))
        self.games_blacklist_hint.setText(self._t("games_blacklist_hint"))
        self.games_blacklist_search.setPlaceholderText(self._t("filters_search_games"))
        self.games_blacklist_select_all_btn.setText(self._t("filters_select_all"))
        self.games_blacklist_clear_all_btn.setText(self._t("filters_clear_all"))
        self.games_blacklist_select_visible_btn.setText(self._t("filters_select_visible"))
        self.games_blacklist_clear_visible_btn.setText(self._t("filters_clear_visible"))
        self.channels_whitelist_group.setTitle(self._t("channels_whitelist_group"))
        self.channels_whitelist_hint.setText(self._normalize_marker_text(self._t("channels_whitelist_hint", mark=CHECK_MARK)))
        self.channels_whitelist_search.setPlaceholderText(self._t("filters_search_channels"))
        self.channels_whitelist_select_all_btn.setText(self._t("filters_select_all"))
        self.channels_whitelist_clear_all_btn.setText(self._t("filters_clear_all"))
        self.channels_whitelist_select_visible_btn.setText(self._t("filters_select_visible"))
        self.channels_whitelist_clear_visible_btn.setText(self._t("filters_clear_visible"))
        self.channels_blacklist_group.setTitle(self._t("channels_blacklist_group"))
        self.channels_blacklist_hint.setText(self._t("channels_blacklist_hint"))
        self.channels_blacklist_search.setPlaceholderText(self._t("filters_search_channels"))
        self.channels_blacklist_select_all_btn.setText(self._t("filters_select_all"))
        self.channels_blacklist_clear_all_btn.setText(self._t("filters_clear_all"))
        self.channels_blacklist_select_visible_btn.setText(self._t("filters_select_visible"))
        self.channels_blacklist_clear_visible_btn.setText(self._t("filters_clear_visible"))
        self.btn_save.setText(self._t("save_settings"))
        self.btn_start.setText(self._t("start_farm"))
        self.btn_stop.setText(self._t("stop_farm"))
        self.btn_farming_start.setText(self._t("farming_start_main"))
        self.btn_farming_pause.setText(self._t("farming_pause_main"))
        self.btn_farming_next.setText(self._t("farming_next_game"))
        self.btn_redeem_drops.setText(self._t("redeem_drops"))
        self.active_drops_group.setTitle(self._t("active_drops_group"))
        if self.active_drops_list.count() == 0:
            self.active_drops_list.addItem(self._t("active_drops_empty"))
        self._refresh_last_update_label()
        self.filter_status_label.setText(self._t("campaign_filter_status"))
        self.filter_link_label.setText(self._t("campaign_filter_link"))
        self.campaign_sort_label.setText(self._t("campaign_sort_label"))

        current_status = self.filter_status_picker.currentData() or "all"
        current_link = self.filter_link_picker.currentData() or "all"
        current_sort = self.campaign_sort_picker.currentData() or "priority"

        self.filter_status_picker.blockSignals(True)
        self.filter_status_picker.clear()
        self.filter_status_picker.addItem(self._t("campaign_status_all"), "all")
        self.filter_status_picker.addItem(self._t("campaign_status_active"), "active")
        self.filter_status_picker.addItem(self._t("campaign_status_upcoming"), "upcoming")
        self.filter_status_picker.addItem(self._t("campaign_status_farmable"), "farmable")
        self.filter_status_picker.setCurrentIndex(max(0, self.filter_status_picker.findData(current_status)))
        self.filter_status_picker.blockSignals(False)

        self.filter_link_picker.blockSignals(True)
        self.filter_link_picker.clear()
        self.filter_link_picker.addItem(self._t("campaign_link_all"), "all")
        self.filter_link_picker.addItem(self._t("campaign_link_eligible"), "eligible")
        self.filter_link_picker.addItem(self._t("campaign_link_unlinked"), "unlinked")
        self.filter_link_picker.setCurrentIndex(max(0, self.filter_link_picker.findData(current_link)))
        self.filter_link_picker.blockSignals(False)

        self.campaign_sort_picker.blockSignals(True)
        self.campaign_sort_picker.clear()
        self.campaign_sort_picker.addItem(self._t("campaign_sort_priority"), "priority")
        self.campaign_sort_picker.addItem(self._t("campaign_sort_ending"), "ending")
        self.campaign_sort_picker.addItem(self._t("campaign_sort_progress"), "progress")
        self.campaign_sort_picker.addItem(self._t("campaign_sort_remaining"), "remaining")
        self.campaign_sort_picker.addItem(self._t("campaign_sort_game"), "game")
        self.campaign_sort_picker.setCurrentIndex(max(0, self.campaign_sort_picker.findData(current_sort)))
        self.campaign_sort_picker.blockSignals(False)

        self._refresh_campaigns_label()
        self.btn_link_account.setText(self._t("link_account"))
        self.btn_open_drops_page.setText(self._t("open_drops_page"))
        self.log_label.setText(self._t("log_label"))
        self._refresh_filter_lists()
        self._refresh_filter_tab_counts()
        self._refresh_dashboard_games()
        self._refresh_priority_label()
        self._refresh_farming_now()
        self._refresh_campaign_list()
        self._refresh_campaign_details()
        self._update_auth_status()
        self._set_farming_controls(self.timer.isActive())

    def _apply_theme(self, name: str) -> None:
        self.setStyleSheet(THEMES.get(name, THEMES["twitch"]))

    def _with_errors(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:
            QMessageBox.critical(self, self._t("error_title"), str(exc))

    def _log(self, message: str) -> None:
        self.log_output.append(message)

    def _sort_mode_label(self) -> str:
        return self._t(f"sort_{self.config.sort_mode}")

    def _format_duration(self, total_seconds: int) -> str:
        minutes_total = max(0, total_seconds // 60)
        days, minutes_left = divmod(minutes_total, 24 * 60)
        hours, minutes = divmod(minutes_left, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)

    def _format_diagnostic_report(self, results: dict[str, object]) -> str:
        status = str(results.get("overall_status", "unknown")).upper()
        summary = str(results.get("summary", "")).strip()
        tests_raw = results.get("tests")

        lines: list[str] = [f"{self._t('status_diag_done')} Status: {status}"]
        if summary:
            lines.append(summary)

        if not isinstance(tests_raw, dict) or not tests_raw:
            return "\n".join(lines)

        rows: list[tuple[str, str, str, str]] = []
        for test_name, test_result in tests_raw.items():
            name = str(test_name)
            result_map = test_result if isinstance(test_result, dict) else {}
            test_status = str(result_map.get("status", "n/a")).upper()
            duration_raw = result_map.get("duration_ms", 0)
            try:
                duration_text = f"{float(duration_raw):.1f}ms"
            except (TypeError, ValueError):
                duration_text = "N/A"
            message = str(result_map.get("message", "")).strip().replace("\n", " ")
            rows.append((name, test_status, duration_text, message))

        name_w = max(4, min(28, max(len(row[0]) for row in rows)))
        status_w = max(6, min(10, max(len(row[1]) for row in rows)))
        time_w = max(6, min(10, max(len(row[2]) for row in rows)))
        header = (
            f"{'Test'.ljust(name_w)} | {'Status'.ljust(status_w)} | "
            f"{'Time'.ljust(time_w)} | Message"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for name, test_status, duration_text, message in rows:
            name_cell = name[:name_w]
            status_cell = test_status[:status_w]
            time_cell = duration_text[:time_w]
            lines.append(
                f"{name_cell.ljust(name_w)} | {status_cell.ljust(status_w)} | "
                f"{time_cell.ljust(time_w)} | {message}"
            )
        return "\n".join(lines)

    def _decision_is_farmable_now(self, decision: FarmDecision) -> bool:
        campaign = decision.campaign
        if self._campaign_is_known_subscription_locked(campaign) and not campaign.all_drops_claimed:
            return False
        if not (campaign.active and campaign.eligible and decision.stream is not None):
            return False
        if campaign.required_minutes > 0 and campaign.remaining_minutes <= 0:
            return False
        return True

    def _decision_is_displayable_active(self, decision: FarmDecision) -> bool:
        campaign = decision.campaign
        if self._campaign_is_known_subscription_locked(campaign) and not campaign.all_drops_claimed:
            return False
        if not (campaign.active and campaign.eligible):
            return False
        if campaign.required_minutes > 0 and campaign.remaining_minutes <= 0:
            return False
        return True

    def _campaign_is_known_subscription_locked(self, campaign: DropCampaign) -> bool:
        if campaign.requires_subscription:
            return True

        text_chunks: list[str] = [campaign.title, campaign.next_drop_name, campaign.link_url]
        for drop in campaign.drops or []:
            if not isinstance(drop, dict):
                continue
            text_chunks.append(str(drop.get("name") or ""))

        combined = "\n".join(chunk for chunk in text_chunks if chunk).casefold()
        if not combined:
            return False

        patterns = (
            "subscribe to redeem",
            "subscription required",
            "subscription-only",
            "subscription only",
            "subscriber only",
            "subscribers only",
            "sub only",
            "subs only",
            "subscrição",
            "subscricao",
            "apenas subs",
            "apenas para subs",
            "so para subs",
        )
        return any(pattern in combined for pattern in patterns)

    def _campaign_has_actionable_drop_data(self, campaign: DropCampaign) -> bool:
        if campaign.required_minutes > 0:
            return True
        if campaign.next_drop_required_minutes > 0:
            return True
        if campaign.next_drop_name.strip():
            return True
        if campaign.drops:
            return True
        return False

    def _campaign_matches_hide_sub_only(self, campaign: DropCampaign) -> bool:
        if self._campaign_is_known_subscription_locked(campaign):
            return True
        # Browser fallback campaigns can be active but lack actionable drop metadata.
        # In practice these entries behave like non-farmable subscription-only campaigns.
        return not self._campaign_has_actionable_drop_data(campaign)

    def _current_display_decision(self) -> FarmDecision | None:
        active = self._current_farm_decision()
        if active is not None:
            return active
        if self.latest_snapshot is None:
            return None

        candidates = [
            decision
            for decision in self.latest_snapshot.decisions
            if self._decision_is_displayable_active(decision)
        ]
        if not candidates:
            return None
        if self._forced_farm_game:
            forced_game_candidates = [
                decision
                for decision in candidates
                if decision.campaign.game_name.casefold() == self._forced_farm_game.casefold()
            ]
            if forced_game_candidates:
                candidates = forced_game_candidates
        if self._forced_farm_campaign_id:
            forced_by_campaign = next(
                (decision for decision in candidates if decision.campaign.id == self._forced_farm_campaign_id),
                None,
            )
            if forced_by_campaign is not None:
                return forced_by_campaign
        return candidates[0]

    def _select_dashboard_game(self, game_name: str) -> None:
        self._forced_farm_game = game_name
        self._forced_farm_campaign_id = ""
        self._forced_farm_channel = ""
        self._refresh_dashboard_games()
        self._refresh_farming_now()
        if self.timer.isActive():
            self._streamless_heartbeat_tick()

    def handle_dashboard_game_clicked(self, game_name: str) -> None:
        if not isinstance(game_name, str) or not game_name.strip():
            return
        game_name = game_name.strip()
        self._select_dashboard_game(game_name)
        self._log(self._t("dashboard_selected", game=game_name))
        if self.latest_snapshot is not None:
            has_candidate = any(
                self._decision_is_farmable_now(decision)
                and decision.campaign.game_name.casefold() == game_name.casefold()
                for decision in self.latest_snapshot.decisions
            )
            if not has_candidate:
                self._log(self._t("dashboard_game_unavailable", game=game_name))

    def _load_box_art_pixmap(self, url: str) -> QPixmap:
        target_url = (url or "").strip() or BOX_ART_FALLBACK_URL
        cached = self._thumb_cache.get(target_url)
        if cached is not None:
            return cached
        return self._placeholder_box_art_pixmap()

    def _placeholder_box_art_pixmap(self) -> QPixmap:
        pixmap = QPixmap(144, 192)
        pixmap.fill(QColor("#1f1f24"))
        return pixmap

    def _game_initials(self, game_name: str) -> str:
        parts = [item for item in game_name.replace("-", " ").split() if item]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()

    def _generated_game_placeholder(self, game_name: str) -> QPixmap:
        key = (game_name or "Unknown").strip() or "Unknown"
        cache_key = key.casefold()
        cached = self._generated_thumb_cache.get(cache_key)
        if cached is not None:
            return cached

        digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
        hue = int(digest[:2], 16) % 360
        bg_color = QColor.fromHsv(hue, 120, 92)
        accent_color = QColor.fromHsv((hue + 26) % 360, 160, 180)

        pixmap = QPixmap(144, 192)
        pixmap.fill(bg_color)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent_color)
        painter.drawRoundedRect(10, 10, 124, 124, 14, 14)

        initials = self._game_initials(key)
        initials_font = QFont(self.font())
        initials_font.setBold(True)
        initials_font.setPixelSize(38)
        painter.setFont(initials_font)
        painter.setPen(QColor("#f8f8ff"))
        painter.drawText(10, 20, 124, 104, Qt.AlignmentFlag.AlignCenter, initials)

        painter.fillRect(0, 142, 144, 50, QColor(0, 0, 0, 130))
        name_font = QFont(self.font())
        name_font.setBold(True)
        name_font.setPixelSize(12)
        painter.setFont(name_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            10,
            148,
            124,
            38,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            key,
        )
        painter.end()

        self._generated_thumb_cache[cache_key] = pixmap
        return pixmap

    def _download_url_bytes(self, url: str) -> bytes:
        """Download image bytes from a single URL. Returns b'' on any failure."""
        if not url or url == BOX_ART_FALLBACK_URL:
            return b""
        headers = {"User-Agent": self.client.session.headers.get("User-Agent", "Mozilla/5.0")}
        try:
            response = requests.get(url, timeout=6, headers=headers)
            response.raise_for_status()
            return response.content or b""
        except requests.RequestException:
            return b""

    def _resolve_and_download_box_art_bytes(
        self,
        target_url: str,
        game_name: str,
        game_slug: str,
        *,
        prefer_direct_url: bool = False,
    ) -> bytes:
        """
        Download game box art via a prioritised chain:
          1. Twitch GQL  ->  2. Steam  ->  3. Google Images
             (all handled internally by resolve_game_box_art_url)
          4. Initial URL from campaign data as last resort
        """
        tried: set[str] = set()

        def _try(url: str) -> bytes:
            u = (url or "").strip()
            if not u or u in tried or u == BOX_ART_FALLBACK_URL:
                return b""
            tried.add(u)
            return self._download_url_bytes(u)

        if prefer_direct_url:
            result = _try(target_url)
            if result:
                return result

        # Steps 1-3: full API chain (Twitch GQL -> Steam -> Google)
        if game_name.strip():
            resolved = self.client.resolve_game_box_art_url(game_name, game_slug=game_slug)
            result = _try(resolved)
            if result:
                return result

            # If game-slug resolver failed due API throttling/integrity checks,
            # try external providers directly before giving up.
            external = self.client.resolve_external_box_art_url(game_name)
            result = _try(external)
            if result:
                return result

        # Step 4: try the original URL supplied by the campaign
        result = _try(target_url)
        if result:
            return result

        return b""

    def _queue_box_art_load(
        self,
        url: str,
        label: QLabel,
        *,
        width: int,
        height: int,
        game_name: str = "",
        game_slug: str = "",
        prefer_direct_url: bool = False,
    ) -> None:
        target_url = (url or "").strip() or BOX_ART_FALLBACK_URL
        generated_key = (game_name or "").strip().casefold()
        generated_cached = self._generated_thumb_cache.get(generated_key) if generated_key else None
        if generated_cached is not None:
            label.setPixmap(
                generated_cached.scaled(
                    width,
                    height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            return

        cached = self._thumb_cache.get(target_url)
        if cached is not None:
            label.setPixmap(
                cached.scaled(
                    width,
                    height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            return

        label.setPixmap(
            self._placeholder_box_art_pixmap().scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._thumb_waiters.setdefault(target_url, []).append((label, width, height, game_name))
        if target_url in self._thumb_inflight:
            return
        self._thumb_inflight.add(target_url)

        def worker(image_url: str, requested_game: str, requested_slug: str, direct_first: bool) -> None:
            image_bytes = self._resolve_and_download_box_art_bytes(
                image_url,
                requested_game,
                requested_slug,
                prefer_direct_url=direct_first,
            )
            if image_bytes:
                self._thumb_fetch_bridge.loaded.emit(image_url, image_bytes)
            else:
                self._thumb_fetch_bridge.failed.emit(image_url)

        self._thumb_executor.submit(worker, target_url, game_name, game_slug, prefer_direct_url)

    def _queue_game_card_art_load(
        self,
        url: str,
        card: GameCard,
        *,
        game_name: str = "",
        game_slug: str = "",
    ) -> None:
        target_url = (url or "").strip() or BOX_ART_FALLBACK_URL
        cached = self._thumb_cache.get(target_url)
        if cached is not None:
            card.set_pixmap(cached)
            return

        # Keep a weak reference so async callbacks do not hold stale cards alive.
        card_ref: object = weakref.ref(card)
        self._thumb_waiters.setdefault(target_url, []).append((card_ref, 144, 192, game_name))
        if target_url in self._thumb_inflight:
            return
        self._thumb_inflight.add(target_url)

        def worker(image_url: str, requested_game: str, requested_slug: str) -> None:
            image_bytes = self._resolve_and_download_box_art_bytes(image_url, requested_game, requested_slug)
            if image_bytes:
                self._thumb_fetch_bridge.loaded.emit(image_url, image_bytes)
            else:
                self._thumb_fetch_bridge.failed.emit(image_url)

        self._thumb_executor.submit(worker, target_url, game_name, game_slug)

    def _on_box_art_loaded(self, target_url: str, image_bytes: bytes) -> None:
        loaded = QPixmap()
        pixmap = self._placeholder_box_art_pixmap()
        if loaded.loadFromData(image_bytes):
            pixmap = loaded
        scaled_base = pixmap.scaled(
            144,
            192,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_cache[target_url] = scaled_base
        waiters = self._thumb_waiters.pop(target_url, [])
        self._thumb_inflight.discard(target_url)
        for target, width, height, _game_name in waiters:
            try:
                resolved_target = target() if isinstance(target, weakref.ReferenceType) else target
                if resolved_target is None:
                    continue
                if isinstance(resolved_target, GameCard):
                    resolved_target.set_pixmap(scaled_base)
                elif isinstance(resolved_target, QLabel):
                    resolved_target.setPixmap(
                        scaled_base.scaled(
                            width,
                            height,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                else:
                    continue
            except RuntimeError:
                continue

    def _on_box_art_failed(self, target_url: str) -> None:
        fallback = self._placeholder_box_art_pixmap()
        waiters = self._thumb_waiters.pop(target_url, [])
        self._thumb_inflight.discard(target_url)
        for target, width, height, game_name in waiters:
            candidate = self._generated_game_placeholder(game_name) if game_name.strip() else fallback
            try:
                resolved_target = target() if isinstance(target, weakref.ReferenceType) else target
                if resolved_target is None:
                    continue
                if isinstance(resolved_target, GameCard):
                    resolved_target.set_pixmap(candidate)
                elif isinstance(resolved_target, QLabel):
                    resolved_target.setPixmap(
                        candidate.scaled(
                            width,
                            height,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                else:
                    continue
            except RuntimeError:
                continue

    def _guess_box_art_url(self, game_name: str, game_slug: str = "") -> str:
        normalized = (game_slug or game_name).strip()
        if normalized:
            slug = quote(normalized, safe="")
            return f"https://static-cdn.jtvnw.net/ttv-boxart/{slug}-144x192.jpg"
        return BOX_ART_FALLBACK_URL

    def _filtered_decisions(self) -> list[FarmDecision]:
        if self.latest_snapshot is None:
            return []
        status_filter = self.filter_status_picker.currentData()
        link_filter = self.filter_link_picker.currentData()

        def status_ok(decision: FarmDecision) -> bool:
            if status_filter == "active":
                return decision.campaign.active
            if status_filter == "upcoming":
                return decision.campaign.upcoming
            if status_filter == "farmable":
                return self._decision_is_farmable_now(decision)
            return True

        def link_ok(decision: FarmDecision) -> bool:
            if link_filter == "eligible":
                return decision.campaign.eligible
            if link_filter == "unlinked":
                return decision.campaign.linkable
            return True

        output = [decision for decision in self.latest_snapshot.decisions if status_ok(decision) and link_ok(decision)]
        sort_mode = self.campaign_sort_picker.currentData()
        if sort_mode == "ending":
            output.sort(key=lambda d: d.campaign.seconds_until_end)
        elif sort_mode == "progress":
            output.sort(key=lambda d: d.campaign.completion, reverse=True)
        elif sort_mode == "remaining":
            output.sort(key=lambda d: d.campaign.remaining_minutes)
        elif sort_mode == "game":
            output.sort(key=lambda d: (d.campaign.game_name.casefold(), d.campaign.title.casefold()))
        return output

    def _refresh_farming_now(self) -> None:
        if self.latest_snapshot is None:
            self.farming_now_group.setTitle(self._t("farming_now_group"))
            self.farming_now_game.setText(self._t("farming_now_idle"))
            self.farming_now_campaign.clear()
            self.farming_now_channel.clear()
            self.farming_now_next_drop.clear()
            self.farming_now_eta.clear()
            self.farming_now_progress_text.clear()
            self.farming_now_progress.setValue(0)
            self.farming_now_game_image.clear()
            self.farming_now_state.setText(self._t("farming_state_running") if self.timer.isActive() else self._t("farming_state_stopped"))
            self._refresh_active_drops_panel(None)
            self._refresh_last_update_label()
            return

        active = self._current_display_decision()
        if (
            active is None
            and self.timer.isActive()
            and self._last_display_decision is not None
            and not self.latest_snapshot.decisions
        ):
            active = self._last_display_decision
        self.farming_now_group.setTitle(self._t("farming_now_group"))
        if active is None:
            self.farming_now_game.setText(self._t("farming_now_idle"))
            self.farming_now_campaign.clear()
            self.farming_now_channel.clear()
            self.farming_now_next_drop.clear()
            self.farming_now_eta.clear()
            self.farming_now_progress_text.clear()
            self.farming_now_progress.setValue(0)
            self.farming_now_game_image.clear()
            self.farming_now_state.setText(self._t("farming_state_running") if self.timer.isActive() else self._t("farming_state_stopped"))
            self._refresh_active_drops_panel(None)
            self._refresh_last_update_label()
            return

        campaign = active.campaign
        self._last_display_decision = active
        channel_name = (
            active.stream.display_name or active.stream.login
            if active.stream is not None
            else self._t("reason_no_valid_stream")
        )
        next_drop_name = campaign.next_drop_name or self._t("drop_unknown")
        next_drop_eta = self._format_duration(campaign.next_drop_eta_seconds)
        self.farming_now_game.setText(self._t("farming_now_game", game=campaign.game_name))
        self.farming_now_campaign.setText(self._t("farming_now_campaign", campaign=campaign.title))
        self.farming_now_channel.setText(self._t("farming_now_channel", channel=channel_name))
        self.farming_now_next_drop.setText(self._t("farming_now_next_drop", drop=next_drop_name))
        self.farming_now_eta.setText(self._t("farming_now_eta", eta=next_drop_eta))
        self.farming_now_state.setText(self._t("farming_state_running") if self.timer.isActive() else self._t("farming_state_stopped"))
        self.farming_now_progress_text.setText(
            self._t(
                "farming_now_progress",
                progress=campaign.progress_minutes,
                required=campaign.required_minutes,
            )
        )
        self.farming_now_progress.setValue(int(campaign.completion * 1000))
        box_art_url = campaign.game_box_art_url or self._guess_box_art_url(
            campaign.game_name,
            campaign.game_slug,
        )
        self._queue_box_art_load(
            box_art_url,
            self.farming_now_game_image,
            width=144,
            height=192,
            game_name=campaign.game_name,
            game_slug=campaign.game_slug,
        )
        self._refresh_active_drops_panel(campaign)
        self._refresh_last_update_label()

    def _refresh_active_drops_panel(self, active_campaign: DropCampaign | None) -> None:
        self.active_drops_list.clear()
        if active_campaign is None:
            self.active_drops_group.setTitle(self._t("active_drops_group"))
            self.active_drops_list.addItem(self._t("active_drops_empty"))
            return

        self.active_drops_group.setTitle(
            self._t("active_drops_group_game", game=active_campaign.game_name)
        )
        drops = [
            item for item in (active_campaign.drops or [])
            if isinstance(item, dict)
        ]
        has_items = False
        for drop in drops:
            name = str(drop.get("name") or self._t("drop_unknown")).strip()
            required = int(drop.get("required_minutes") or 0)
            current = int(drop.get("current_minutes") or 0)
            is_claimed = bool(drop.get("claimed"))
            image_url = str(drop.get("image_url") or "").strip()

            row = QWidget()
            row.setMinimumWidth(152)
            row.setStyleSheet("background: #171922; border: 1px solid #2c3140; border-radius: 8px;")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(8, 8, 8, 8)
            row_layout.setSpacing(6)

            thumb = QLabel()
            thumb.setFixedSize(116, 72)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("border: 1px solid #2f3340; border-radius: 6px; background: #151823;")
            row_layout.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(3)

            name_label = QLabel(name)
            name_label.setWordWrap(True)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content_layout.addWidget(name_label)

            progress_label = QLabel()
            progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if required > 0:
                bounded_current = min(max(current, 0), required)
                percent = int((bounded_current / max(1, required)) * 100)
                progress_label.setText(
                    f"{self._t('active_drops_progress', current=bounded_current, required=required)} ({percent}%)"
                )
                bar = QProgressBar()
                bar.setRange(0, 1000)
                bar.setValue(int((bounded_current / max(1, required)) * 1000))
                bar.setMaximumHeight(10)
                bar.setTextVisible(False)
                content_layout.addWidget(bar)
            else:
                progress_label.setText(self._t("active_drops_claimed") if is_claimed else "")
            content_layout.addWidget(progress_label)

            if is_claimed:
                claimed_label = QLabel(self._t("active_drops_claimed"))
                claimed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                claimed_label.setStyleSheet("color: #50d890; font-weight: 600;")
                content_layout.addWidget(claimed_label)

            row_layout.addWidget(content, 1)

            item = QListWidgetItem()
            item.setSizeHint(QSize(160, 130))
            self.active_drops_list.addItem(item)
            self.active_drops_list.setItemWidget(item, row)

            self._queue_box_art_load(
                image_url or active_campaign.game_box_art_url,
                thumb,
                width=116,
                height=72,
                game_name=active_campaign.game_name,
                game_slug=active_campaign.game_slug,
                prefer_direct_url=bool(image_url),
            )
            has_items = True

        if self._campaign_matches_hide_sub_only(active_campaign):
            self.active_drops_list.addItem(self._t("active_drops_subscription_hint"))
            has_items = True

        if not has_items:
            self.active_drops_list.addItem(self._t("active_drops_empty"))

    def _reason_text(self, decision: FarmDecision) -> str:
        if decision.reason_code == "game_filtered":
            return self._t("reason_game_filtered")
        if decision.reason_code == "campaign_upcoming":
            return self._t("reason_campaign_upcoming")
        if decision.reason_code == "campaign_not_active":
            return self._t("reason_campaign_not_active")
        if decision.reason_code == "campaign_completed":
            return self._t("reason_campaign_completed")
        if decision.reason_code == "no_valid_stream":
            return self._t("reason_no_valid_stream")
        if decision.reason_code == "account_not_linked":
            return self._t("reason_account_not_linked")
        if decision.reason_code == "subscription_required":
            return self._t("reason_subscription_required")
        if decision.used_channel_whitelist:
            return f"{self._t('reason_channel_priority')} {self._t('reason_stream_selected')}"
        return self._t("reason_stream_selected")

    def _refresh_priority_label(self) -> None:
        if not self.latest_snapshot or not self.latest_snapshot.decisions:
            self.best_target_label.setText(self._t("best_target_none"))
            return
        top = self._current_display_decision()
        if top is None:
            self.best_target_label.setText(self._t("best_target_none"))
            return
        if top.stream is None:
            self.best_target_label.setText(
                self._t("best_target_no_stream", game=top.campaign.game_name, sort_mode=self._sort_mode_label())
            )
            return
        self.best_target_label.setText(
            self._t(
                "best_target",
                game=top.campaign.game_name,
                channel=top.stream.display_name or top.stream.login,
                sort_mode=self._sort_mode_label(),
            )
        )

    def _refresh_campaign_list(self) -> None:
        self.campaign_list.blockSignals(True)
        selected_id = None
        if self.campaign_list.currentItem() is not None:
            selected_id = self.campaign_list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.campaign_list.clear()
        self.decision_by_campaign_id.clear()
        if self.latest_snapshot is None:
            self.campaign_list.blockSignals(False)
            return

        decisions = self._filtered_decisions()
        if self.campaign_sort_picker.currentData() in {None, "priority"}:
            decisions = list(decisions)
            decisions.sort(key=self.engine._decision_sort_key)

        for decision in decisions:
            campaign = decision.campaign
            self.decision_by_campaign_id[campaign.id] = decision
            target = decision.stream.display_name if decision.stream else "-"
            linked = self._t("linked_yes") if campaign.linked else self._t("linked_no")
            item = QListWidgetItem(
                (
                    f"{campaign.game_name} | {campaign.title} | "
                    f"{self._t('channel_word')}: {target} | "
                    f"{self._t('remaining_word')}: {campaign.remaining_minutes}m | "
                    f"{self._t('ends_in_word')}: {self._format_duration(campaign.seconds_until_end)} | "
                    f"{self._t('linked_label')}: {linked} | {self._reason_text(decision)}"
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, campaign.id)
            self.campaign_list.addItem(item)

        if selected_id:
            for row in range(self.campaign_list.count()):
                item = self.campaign_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == selected_id:
                    self.campaign_list.setCurrentItem(item)
                    break
        elif self.campaign_list.count() > 0:
            self.campaign_list.setCurrentRow(0)
        self.campaign_list.blockSignals(False)

    def _refresh_campaign_details(self) -> None:
        decision = self._selected_decision()
        if decision is None:
            self.campaign_details_label.setText(self._t("campaign_details_none"))
            self.btn_link_account.setEnabled(False)
            self.btn_link_account.setToolTip(self._t("link_button_disabled"))
            return

        campaign = decision.campaign
        allowed = ", ".join(campaign.allowed_channels) if campaign.allowed_channels else self._t("allowed_any")
        linked = self._t("linked_yes") if campaign.linked else self._t("linked_no")
        link_status = self._t("link_status_open_browser") if campaign.linkable else self._t("link_status_unavailable")
        self.campaign_details_label.setText(
            self._t(
                "campaign_details",
                game=campaign.game_name,
                title=campaign.title,
                status=campaign.status or ("ACTIVE" if campaign.active else "UNKNOWN"),
                linked=linked,
                progress=campaign.progress_minutes,
                required=campaign.required_minutes,
                allowed=allowed,
                link_status=link_status,
            )
        )
        can_link = campaign.linkable
        self.btn_link_account.setEnabled(can_link)
        self.btn_link_account.setToolTip("" if can_link else self._t("link_button_disabled"))

    def _refresh_dashboard(self) -> None:
        """Atualiza o dashboard com os jogos da whitelist em grelha."""
        # Limpa a grelha
        while self.dashboard_games_grid.count() > 0:
            item = self.dashboard_games_grid.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if widget is self.dashboard_no_games:
                widget.setParent(None)
            else:
                widget.deleteLater()

        # Obtém os jogos da whitelist (compatível com config antiga por label).
        # If nothing is selected, default to showing all currently available games.
        selected_values = self._selected_values(self.games_whitelist_list, self.config.whitelist_games)
        selected_tokens = {value.casefold() for value in selected_values if isinstance(value, str) and value.strip()}
        if not selected_tokens:
            filtered_games = list(self.available_game_entries)
        else:
            # Filtra apenas os jogos na whitelist (suporta key e label)
            filtered_games = [
                entry
                for entry in self.available_game_entries
                if entry.key.casefold() in selected_tokens or entry.label.casefold() in selected_tokens
            ]

        if not filtered_games:
            self.dashboard_no_games.setText(self._t("dashboard_empty"))
            self.dashboard_games_grid.addWidget(self.dashboard_no_games, 0, 0)
            return

        # Determina o jogo atualmente em farm e os que têm stream farmável
        active_decision = self._current_farm_decision()
        active_game_label = active_decision.campaign.game_name if active_decision else ""
        farmable_game_labels: set[str] = set()
        if self.latest_snapshot:
            for decision in self.latest_snapshot.decisions:
                if self._decision_is_farmable_now(decision):
                    farmable_game_labels.add(decision.campaign.game_name)

        campaigns_by_game: dict[str, list[DropCampaign]] = {}
        if self.latest_snapshot:
            for campaign in self.latest_snapshot.campaigns:
                key = campaign.game_name.casefold()
                campaigns_by_game.setdefault(key, []).append(campaign)

        # Popula a grelha (3 colunas)
        columns = 3
        visible_index = 0
        for entry in sorted(filtered_games, key=lambda e: e.label.casefold()):

            related_campaigns = campaigns_by_game.get(entry.label.casefold(), [])
            actionable_campaigns = [
                item
                for item in related_campaigns
                if not item.all_drops_claimed
            ]
            non_subscription_actionable_campaigns = [
                item
                for item in actionable_campaigns
                if not self._campaign_matches_hide_sub_only(item)
            ]
            subscription_only_game = bool(actionable_campaigns) and not non_subscription_actionable_campaigns
            if self.dashboard_hide_sub_only_checkbox.isChecked() and subscription_only_game:
                continue

            row = visible_index // columns
            col = visible_index % columns
            visible_index += 1

            is_farming = (entry.label == active_game_label and active_decision is not None)
            has_live   = entry.label in farmable_game_labels

            # Ribbon de estado
            if is_farming:
                ribbon = RIBBON_FARMING
            elif has_live:
                ribbon = RIBBON_LIVE
            else:
                ribbon = None

            # Box art: prefere URL da campanha se disponível
            best_decision = None
            if self.latest_snapshot:
                for decision in self.latest_snapshot.decisions:
                    if decision.campaign.game_name == entry.label and self._decision_is_farmable_now(decision):
                        best_decision = decision
                        break
            if best_decision:
                box_art_url = best_decision.campaign.game_box_art_url or self._guess_box_art_url(
                    entry.label,
                    best_decision.campaign.game_slug,
                )
            else:
                box_art_url = self._guess_box_art_url(entry.label)
            pixmap = self._load_box_art_pixmap(box_art_url)

            card = GameCard(
                game_key=entry.key,
                game_label=entry.label,
                pixmap=pixmap,
                ribbon=ribbon,
                is_farming=is_farming,
                on_click=self._force_farm_game,
            )

            self.dashboard_games_grid.addWidget(card, row, col)
            self._queue_game_card_art_load(
                box_art_url,
                card,
                game_name=entry.label,
                game_slug=best_decision.campaign.game_slug if best_decision is not None else "",
            )

        if visible_index == 0:
            self.dashboard_no_games.setText(self._t("dashboard_empty"))
            self.dashboard_games_grid.addWidget(self.dashboard_no_games, 0, 0)

    def _force_farm_game(self, game_key: str, game_label: str) -> None:
        """Força o farm de um jogo específico clicado no dashboard."""
        if self.latest_snapshot is None:
            return

        # Encontra o melhor stream para este jogo
        best_decision = None
        for decision in self.latest_snapshot.decisions:
            if decision.campaign.game_name == game_label and self._decision_is_farmable_now(decision):
                if best_decision is None or decision.stream.display_name.casefold() < best_decision.stream.display_name.casefold():
                    best_decision = decision

        if best_decision is None or best_decision.stream is None:
            self._log(self._t("dashboard_no_stream", game=game_label))
            return

        # Força o farm deste jogo
        self._forced_farm_game = game_label
        self._forced_farm_campaign_id = best_decision.campaign.id
        self._forced_farm_channel = best_decision.stream.login
        self._refresh_dashboard_games()
        self._refresh_farming_now()
        self._streamless_heartbeat_tick()
        self._log(
            self._t(
                "dashboard_game_selected",
                game=game_label,
            )
        )

    def _current_farm_decision(self) -> FarmDecision | None:
        if self.latest_snapshot is None:
            return None
        all_decisions = self.latest_snapshot.decisions
        candidates = [
            decision
            for decision in all_decisions
            if self._decision_is_farmable_now(decision)
        ]
        if self._forced_farm_game:
            forced_key = self._forced_farm_game.casefold()
            forced_decisions = [
                decision
                for decision in all_decisions
                if decision.campaign.game_name.casefold() == forced_key
            ]
            forced_candidates = [
                decision
                for decision in forced_decisions
                if self._decision_is_farmable_now(decision)
            ]
            if forced_candidates:
                candidates = forced_candidates
            else:
                # Keep manual dashboard target sticky while campaign is still active/eligible,
                # even if there is temporarily no valid stream.
                forced_still_relevant = any(
                    self._decision_is_displayable_active(decision)
                    for decision in forced_decisions
                )
                if forced_still_relevant:
                    return None
                self._forced_farm_game = ""

        if not candidates:
            self._forced_farm_channel = ""
            self._forced_farm_campaign_id = ""
            return None
        if self._forced_farm_campaign_id:
            forced_by_campaign = next(
                (decision for decision in candidates if decision.campaign.id == self._forced_farm_campaign_id),
                None,
            )
            if forced_by_campaign is not None:
                return forced_by_campaign
            self._forced_farm_campaign_id = ""
        if self._forced_farm_channel:
            forced = next(
                (
                    decision
                    for decision in candidates
                    if decision.stream is not None
                    and decision.stream.login.casefold() == self._forced_farm_channel.casefold()
                ),
                None,
            )
            if forced is not None:
                return forced
            self._forced_farm_channel = ""
        return candidates[0]

    def handle_next_game(self) -> None:
        candidates: list[FarmDecision] = []
        if self.latest_snapshot is not None:
            candidates = [
                decision
                for decision in self.latest_snapshot.decisions
                if self._decision_is_farmable_now(decision)
            ]
        if len(candidates) <= 1:
            self._log(self._t("farming_next_game_unavailable"))
            return

        current = self._current_farm_decision()
        current_index = -1
        if current is not None:
            for index, decision in enumerate(candidates):
                if decision.campaign.id == current.campaign.id:
                    current_index = index
                    break

        next_decision = candidates[(current_index + 1) % len(candidates)]
        assert next_decision.stream is not None
        self._forced_farm_game = ""
        self._forced_farm_campaign_id = next_decision.campaign.id
        self._forced_farm_channel = next_decision.stream.login
        self._refresh_dashboard_games()
        self._refresh_farming_now()
        self._streamless_heartbeat_tick()
        self._log(
            self._t(
                "farming_next_game_selected",
                game=next_decision.campaign.game_name,
                channel=next_decision.stream.display_name or next_decision.stream.login,
            )
        )

    def _streamless_heartbeat_tick(self) -> None:
        if not self.timer.isActive():
            return
        decision = self._current_farm_decision()
        if decision is None or decision.stream is None:
            if not self._streamless_no_target_logged:
                self._log(self._t("streamless_no_target"))
                self._streamless_no_target_logged = True
            self._streamless_channel = ""
            self._streamless_failure_channel = ""
            return

        self._streamless_no_target_logged = False
        channel_login = decision.stream.login
        if channel_login.casefold() != self._streamless_channel.casefold():
            self._streamless_channel = channel_login
            self._streamless_failure_channel = ""
            self._log(self._t("streamless_target", channel=channel_login))

        ok = self.client.streamless_watch_heartbeat(
            channel_login,
            channel_id=decision.stream.channel_id,
            broadcast_id=decision.stream.broadcast_id,
        )
        for message in self.client.consume_diagnostics():
            self._log(message)
        if not ok and channel_login.casefold() != self._streamless_failure_channel.casefold():
            self._streamless_failure_channel = channel_login
            self._log(self._t("streamless_failed", channel=channel_login))

    def handle_language_change(self) -> None:
        self.config.language = self._current_language()
        self._retranslate_ui()

    def handle_theme_change(self) -> None:
        self.config.theme = self._current_theme()
        self._apply_theme(self.config.theme)

    def handle_sort_change(self) -> None:
        self.config.sort_mode = self._current_sort_mode()
        self.engine.config = self.config
        if self.latest_snapshot is not None:
            self.refresh_snapshot()
        else:
            self._refresh_priority_label()

    def handle_energy_profile_change(self, profile_name: str) -> None:
        """Handle energy profile selection change."""
        self.config.energy_profile = profile_name
        profile = get_profile_by_name(profile_name)
        if profile:
            logger.info(f"Perfil de energia alterado para: {profile_name}")
            self.config.watchdog_stall_timeout_min = profile.watchdog_stall_timeout_min
            if hasattr(self, "watchdog_timeout_spinbox"):
                self.watchdog_timeout_spinbox.setValue(profile.watchdog_stall_timeout_min)

    def handle_watchdog_toggle(self, checked: bool) -> None:
        """Handle watchdog enable/disable."""
        self.config.watchdog_enabled = checked
        self.watchdog_timeout_spinbox.setEnabled(checked)
        logger.info(f"Watchdog: {'ativado' if checked else 'desativado'}")

    def handle_alert_toggle(self, alert_type: AlertType, checked: bool) -> None:
        """Handle alert enable/disable."""
        config_key = f"alert_{alert_type.value}"
        setattr(self.config, config_key, checked)
        alert_manager = get_alert_manager()
        alert_manager.set_alert_enabled(alert_type, checked)
        logger.info(f"Alerta {alert_type.value}: {'ativado' if checked else 'desativado'}")

    def handle_autoupdate_toggle(self, checked: bool) -> None:
        """Handle auto-update enable/disable."""
        self.config.auto_update_enabled = checked
        self.autoupdate_delay_spinbox.setEnabled(checked)
        logger.info(f"Auto-update: {'ativado' if checked else 'desativado'}")

    def handle_dashboard_hide_sub_only_toggle(self, checked: bool) -> None:
        """Handle hide subscription-only games toggle."""
        self.config.dashboard_hide_subscription_required = checked
        self._refresh_dashboard_games()
        if checked and self.latest_snapshot is not None:
            has_sub_only = any(
                self._campaign_matches_hide_sub_only(campaign) and not campaign.all_drops_claimed
                for campaign in self.latest_snapshot.campaigns
            )
            if not has_sub_only:
                self._log("Não há jogos com drops de subs detetados neste ciclo.")

    def handle_run_diagnostic(self) -> None:
        """Run diagnostic tests."""
        if self._diag_future is not None:
            self.update_status_label.setText(self._t("status_diag_running"))
            self._log(self._t("status_diag_running"))
            return
        if self._update_future is not None:
            # Keep a single heavy background operation at a time to avoid lockups.
            self.update_status_label.setText(self._t("status_updates_checking"))
            self._log(self._t("status_updates_checking"))
            return
        self.btn_diagnostic.setEnabled(False)
        self.btn_check_updates.setEnabled(False)
        self.update_status_label.setText(self._t("status_diag_running"))
        self._log(self._t("status_diag_running"))

        def run_diag():
            try:
                from .diagnostic import DiagnosticEngine

                engine = DiagnosticEngine(self.client)
                report = asyncio.run(engine.run_all_diagnostics())
                tests: dict[str, dict[str, object]] = {}
                for item in report.results:
                    tests[item.name] = {
                        "status": item.status.value,
                        "message": item.message,
                        "duration_ms": round(item.duration_ms, 1),
                    }
                return {
                    "overall_status": report.overall_status.value,
                    "summary": report.summary,
                    "tests": tests,
                }
            except Exception as e:
                logger.exception("Erro ao executar diagnósticos")
                return {"error": str(e), "overall_status": "failed"}

        self._diag_future = self.executor.submit(run_diag)
        self._diag_started_at = datetime.now()
        self._diag_poll_timer.start()

    def _poll_diagnostic_future(self) -> None:
        future = self._diag_future
        if future is None:
            self._diag_poll_timer.stop()
            return

        if future.done():
            self._diag_poll_timer.stop()
            self._diag_future = None
            self._diag_started_at = None
            try:
                results = future.result()
                status = results.get("overall_status", "unknown")
                report_text = self._format_diagnostic_report(results)
                self.update_status_label.setText(report_text)
                self._log(self._t("status_diag_done"))
                self._log(f"Diagnostic status: {status}")
                for line in report_text.splitlines():
                    self._log(line)
                logger.info(f"Diagnóstico concluído: {status}")
            except Exception as exc:
                self.update_status_label.setText(self._t("status_operation_error", error=exc))
                QMessageBox.warning(
                    self,
                    self._t("btn_diagnostic"),
                    self._t("status_operation_error", error=exc),
                )
                logger.exception("Erro ao processar resultado diagnóstico")
            finally:
                self.btn_diagnostic.setEnabled(True)
                if self._update_future is None:
                    self.btn_check_updates.setEnabled(True)
            return

        if self._diag_started_at and (datetime.now() - self._diag_started_at).total_seconds() > 90:
            self._diag_poll_timer.stop()
            self._diag_future = None
            self._diag_started_at = None
            self.update_status_label.setText(self._t("status_diag_timeout"))
            self._log(self._t("status_diag_timeout"))
            QMessageBox.warning(self, self._t("btn_diagnostic"), self._t("status_diag_timeout"))
            self.btn_diagnostic.setEnabled(True)
            if self._update_future is None:
                self.btn_check_updates.setEnabled(True)
            return

    def handle_check_updates(self) -> None:
        """Check for updates."""
        if self._update_future is not None:
            self.update_status_label.setText(self._t("status_updates_checking"))
            self._log(self._t("status_updates_checking"))
            return
        if self._diag_future is not None:
            self.update_status_label.setText(self._t("status_diag_running"))
            self._log(self._t("status_diag_running"))
            return
        self.btn_check_updates.setEnabled(False)
        self.btn_diagnostic.setEnabled(False)
        self.update_status_label.setText(self._t("status_updates_checking"))
        self._log(self._t("status_updates_checking"))

        def check_updates():
            try:
                from . import __version__
                current = __version__
                latest_info = updater.check_for_updates(current)
                return latest_info
            except Exception as e:
                logger.exception("Erro ao verificar atualizações")
                return {"error": str(e), "update_available": False}

        self._update_future = self.executor.submit(check_updates)
        self._update_started_at = datetime.now()
        self._update_poll_timer.start()

    def _poll_update_future(self) -> None:
        future = self._update_future
        if future is None:
            self._update_poll_timer.stop()
            return

        if future.done():
            self._update_poll_timer.stop()
            self._update_future = None
            self._update_started_at = None
            try:
                info = future.result()
                if info is None:
                    status_message = self._t("status_updates_failed")
                elif isinstance(info, dict):
                    if info.get("error"):
                        status_message = self._t("status_operation_error", error=info["error"])
                    elif info.get("update_available"):
                        status_message = self._t(
                            "status_updates_available",
                            version=info.get("latest_version", "desconhecida"),
                            url=info.get("download_url", "N/A"),
                        )
                    else:
                        status_message = self._t("status_updates_uptodate")
                elif info.is_update_available:
                    status_message = self._t(
                        "status_updates_available",
                        version=info.latest or "desconhecida",
                        url=info.download_url or "N/A",
                    )
                else:
                    status_message = self._t("status_updates_uptodate")
                self.update_status_label.setText(status_message)
                self._log(status_message)
                logger.info("Verificação de atualização concluída")
            except Exception as exc:
                self.update_status_label.setText(self._t("status_operation_error", error=exc))
                QMessageBox.warning(
                    self,
                    self._t("btn_check_updates"),
                    self._t("status_operation_error", error=exc),
                )
                logger.exception("Erro ao processar resultado de atualização")
            finally:
                self.btn_check_updates.setEnabled(True)
                if self._diag_future is None:
                    self.btn_diagnostic.setEnabled(True)
            return

        if self._update_started_at and (datetime.now() - self._update_started_at).total_seconds() > 45:
            self._update_poll_timer.stop()
            self._update_future = None
            self._update_started_at = None
            self.update_status_label.setText(self._t("status_updates_timeout"))
            self._log(self._t("status_updates_timeout"))
            QMessageBox.warning(self, self._t("btn_check_updates"), self._t("status_updates_timeout"))
            self.btn_check_updates.setEnabled(True)
            if self._diag_future is None:
                self.btn_diagnostic.setEnabled(True)
            return

    def handle_login(self) -> None:
        self._with_errors(self._do_login)

    def _do_login(self) -> None:
        token = self.token_input.text().strip()
        if not token:
            raise ValueError(self._t("token_required"))
        self.client.set_oauth_token(token)
        self._set_oauth_hidden(True)
        self._update_auth_status()
        self._log(self._t("oauth_saved"))
        self._log(self._t("oauth_refreshing"))
        self._do_refresh()

    def handle_edit_oauth(self) -> None:
        self._set_oauth_hidden(False)
        self._update_auth_status()
        self.token_input.setFocus()

    def handle_export_session(self) -> None:
        self._with_errors(self._do_export_session)

    def _do_export_session(self) -> None:
        session_json = self.client.export_session_json()
        self.session_input.setText(session_json)
        self._log(self._t("session_export_success"))

    def handle_import_session(self) -> None:
        self._with_errors(self._do_import_session)

    def _do_import_session(self) -> None:
        session_json = self.session_input.toPlainText().strip()
        if not session_json:
            raise ValueError("Tens de colar o JSON da sessão antes de importar.")
        self.client.import_session_json(session_json)
        self._update_auth_status()
        self._log("Sessão importada com sucesso!")

    def handle_validate_session(self) -> None:
        self._with_errors(self._do_validate_session)

    def _do_validate_session(self) -> None:
        if not self.client.login_state.oauth_token:
            raise ValueError("Nenhuma sessão importada para validar.")
        self.client.validate_oauth_token()
        self._update_auth_status()
        self._log(self._t("oauth_refreshing"))
        self._do_refresh()

    def handle_save_config(self) -> None:
        self._with_errors(self._do_save_config)

    def _do_save_config(self) -> None:
        self.config.whitelist_games = self.games_whitelist_list.selected_keys()
        self.config.blacklist_games = self.games_blacklist_list.selected_keys()
        self.config.whitelist_channels = self.channels_whitelist_list.selected_keys()
        self.config.blacklist_channels = self.channels_blacklist_list.selected_keys()
        self.config.language = self._current_language()
        self.config.theme = self._current_theme()
        self.config.sort_mode = self._current_sort_mode()
        self.config.auto_claim_drops = self.auto_claim_checkbox.isChecked()
        self.config.dashboard_hide_subscription_required = self.dashboard_hide_sub_only_checkbox.isChecked()
        save_config(self.config)
        self.engine.config = self.config
        self._log(self._t("settings_saved"))
        if self.latest_snapshot is not None:
            self.refresh_snapshot()

    def handle_start(self) -> None:
        self._with_errors(self._do_start)

    def _do_start(self) -> None:
        self.timer.start(self.config.auto_switch_interval_sec * 1000)
        self.live_refresh_timer.start()
        self.streamless_timer.start()
        self._set_farming_controls(True)
        self._forced_farm_channel = ""
        self._forced_farm_campaign_id = ""
        self._streamless_channel = ""
        self._streamless_failure_channel = ""
        self._streamless_no_target_logged = False
        self.refresh_snapshot()
        self._streamless_heartbeat_tick()
        self._log(self._t("farming_started"))
        self._log(self._t("streamless_running"))

    def handle_stop(self) -> None:
        self.timer.stop()
        self.live_refresh_timer.stop()
        self.streamless_timer.stop()
        self._set_farming_controls(False)
        self._forced_farm_channel = ""
        self._forced_farm_campaign_id = ""
        self._streamless_channel = ""
        self._streamless_failure_channel = ""
        self._streamless_no_target_logged = False
        self._log(self._t("farming_stopped"))

    def handle_campaign_selection_changed(self) -> None:
        self._refresh_campaign_details()

    def _handle_campaign_filters_changed(self) -> None:
        self._refresh_campaigns_label()
        self._refresh_campaign_list()
        self._refresh_campaign_details()
        self._refresh_dashboard_games()

    def handle_link_account(self) -> None:
        decision = self._selected_decision()
        if decision is None or not decision.campaign.link_url:
            return
        QDesktopServices.openUrl(QUrl(decision.campaign.link_url))
        self._log(self._t("link_opened"))

    def handle_open_drops_page(self) -> None:
        QDesktopServices.openUrl(QUrl("https://www.twitch.tv/drops/inventory"))
        self._log(self._t("drops_page_opened"))

    def handle_redeem_drops(self) -> None:
        self._with_errors(self._do_redeem_drops)

    def handle_dashboard_refresh(self) -> None:
        self._with_errors(self._do_dashboard_refresh)

    def _do_dashboard_refresh(self) -> None:
        self._thumb_cache.clear()
        self._thumb_waiters.clear()
        self._thumb_inflight.clear()
        self._generated_thumb_cache.clear()
        self.client.clear_box_art_caches()
        self.refresh_snapshot()

    def _do_redeem_drops(self, *, auto_mode: bool = False) -> int:
        claimed = self.client.claim_available_drops()
        for message in self.client.consume_diagnostics():
            self._log(message)
        if claimed > 0:
            self.refresh_snapshot()
            self._log(self._t("redeem_auto_done", count=claimed) if auto_mode else self._t("redeem_done", count=claimed))
            return claimed
        if not auto_mode:
            self._log(self._t("redeem_none"))
        return claimed

    def _auto_advance_after_claim(self) -> None:
        if not self.timer.isActive() or self.latest_snapshot is None:
            return

        # Do not override manual dashboard selection.
        if self._forced_farm_game:
            return

        candidates = [
            decision
            for decision in self.latest_snapshot.decisions
            if self._decision_is_farmable_now(decision)
        ]
        if len(candidates) <= 1:
            return

        current = self._current_farm_decision()
        current_index = -1
        if current is not None:
            for index, decision in enumerate(candidates):
                if decision.campaign.id == current.campaign.id:
                    current_index = index
                    break

        next_decision = candidates[(current_index + 1) % len(candidates)]
        if next_decision.stream is None:
            return

        self._forced_farm_game = ""
        self._forced_farm_campaign_id = next_decision.campaign.id
        self._forced_farm_channel = next_decision.stream.login
        self._refresh_dashboard_games()
        self._refresh_farming_now()
        self._streamless_heartbeat_tick()
        self._log(
            self._t(
                "farming_next_game_selected",
                game=next_decision.campaign.game_name,
                channel=next_decision.stream.display_name or next_decision.stream.login,
            )
        )

    def refresh_snapshot(self) -> None:
        self._with_errors(self._do_refresh)

    def _do_refresh(self) -> None:
        snapshot = self.engine.poll()
        self._last_refresh_at = datetime.now().strftime("%H:%M:%S")
        self.latest_snapshot = snapshot
        self.engine.config = self.config
        self.available_game_entries = [FilterEntry(key=game_name, label=game_name) for game_name in snapshot.available_games]
        self.available_channel_entries = [FilterEntry(key=channel.login, label=channel.label) for channel in snapshot.available_channels]
        self._refresh_filter_lists()
        self._refresh_dashboard_games()
        self._refresh_campaigns_label()
        self._refresh_priority_label()
        self._refresh_farming_now()
        self._refresh_campaign_list()
        self._refresh_campaign_details()
        self._update_auth_status()
        if self.config.auto_claim_drops:
            now = datetime.now()
            if self._last_auto_claim_at is None or (now - self._last_auto_claim_at).total_seconds() >= 120:
                self._last_auto_claim_at = now
                claimed = self._do_redeem_drops(auto_mode=True)
                if claimed > 0:
                    self._auto_advance_after_claim()
        for message in snapshot.messages:
            self._log(message)
        self._log(self._t("refresh_done", count=len(snapshot.decisions)))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.executor.shutdown(wait=False)
        self._thumb_executor.shutdown(wait=False)
        super().closeEvent(event)


def run() -> None:
    def _global_excepthook(exc_type, exc_value, exc_traceback) -> None:
        try:
            log_dir = Path.home() / ".twitch-drop-farmer"
            log_dir.mkdir(parents=True, exist_ok=True)
            crash_log = log_dir / "crash.log"
            with crash_log.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[{datetime.now().isoformat()}] Uncaught exception\n")
                handle.writelines(traceback.format_exception(exc_type, exc_value, exc_traceback))
                handle.write("\n")
        except Exception:
            pass

        try:
            QMessageBox.critical(
                None,
                "Twitch Drop Farmer",
                "Ocorreu um erro inesperado.\n"
                "Foi guardado em ~/.twitch-drop-farmer/crash.log",
            )
        except Exception:
            pass

    sys.excepthook = _global_excepthook

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NightmareFTW.TwitchDropFarmer"
            )
        except Exception:
            pass

    app = QApplication([])
    _ico_path = _ASSETS_DIR / "icon.ico"
    _png_path = _ASSETS_DIR / "icon.png"
    _icon = QIcon()
    for _candidate in (_ico_path, _png_path):
        if _candidate.exists():
            _probe = QIcon(str(_candidate))
            if not _probe.isNull():
                _icon = _probe
                break
    if not _icon.isNull():
        app.setWindowIcon(_icon)
    app.setApplicationName("TwitchDropFarmer")
    win = MainWindow()
    if not _icon.isNull():
        win.setWindowIcon(_icon)
    win.show()

    if not _icon.isNull():
        for widget in app.topLevelWidgets():
            try:
                widget.setWindowIcon(_icon)
            except Exception:
                continue

    # Force the correct icon via Win32 API (bypasses Qt/taskbar cache edge cases)
    if sys.platform == "win32":
        try:
            import ctypes
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            GCLP_HICON = -14
            GCLP_HICONSM = -34

            # Must declare correct return types for 64-bit handles; ctypes defaults
            # to c_int (32-bit) which silently truncates 64-bit HICON values.
            _user32 = ctypes.windll.user32
            _user32.LoadImageW.restype = ctypes.c_void_p
            _user32.LoadImageW.argtypes = [
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ]
            _user32.SendMessageW.restype = ctypes.c_ssize_t
            _user32.SendMessageW.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
            ]
            _user32.SetClassLongPtrW.restype = ctypes.c_size_t
            _user32.SetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]

            _native_icon_path = _ico_path if _ico_path.exists() else _png_path

            def _apply_native_icon() -> None:
                hwnd = int(win.winId())
                icon_str = str(_native_icon_path)
                hicon_big = _user32.LoadImageW(
                    None, icon_str, IMAGE_ICON, 32, 32, LR_LOADFROMFILE
                )
                hicon_small = _user32.LoadImageW(
                    None, icon_str, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
                )
                if hicon_big:
                    _user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                if hicon_small:
                    _user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)

                # Also set class icons: some Windows builds/taskbar paths read class icon first.
                if hicon_big:
                    _user32.SetClassLongPtrW(hwnd, GCLP_HICON, hicon_big)
                if hicon_small:
                    _user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, hicon_small)

            _apply_native_icon()
            QTimer.singleShot(0, _apply_native_icon)
            QTimer.singleShot(250, _apply_native_icon)
            QTimer.singleShot(1000, _apply_native_icon)
        except Exception:
            pass

    app.exec()
