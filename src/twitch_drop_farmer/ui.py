from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, QUrl, QPoint
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap, QPolygon

_ASSETS_DIR = Path(__file__).parent / "assets"
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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import load_config, save_config
from .farmer import FarmEngine, FarmSnapshot
from .models import DropCampaign, FarmDecision
from .twitch_client import TwitchClient

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
            background: #3a3120;
            color: #ffd892;
        }
        QFrame#DashboardGameCard[status="offline"] QLabel#DashboardBadge {
            background: #2d2f36;
            color: #c6c9d3;
        }
        QFrame#DashboardGameCard[status="completed"] QLabel#DashboardBadge {
            background: #0f3f2c;
            color: #9cf2cb;
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
            background: #3b2f1d;
            color: #ffd48a;
        }
        QFrame#DashboardGameCard[status="offline"] QLabel#DashboardBadge {
            background: #2f2729;
            color: #c5b6b8;
        }
        QFrame#DashboardGameCard[status="completed"] QLabel#DashboardBadge {
            background: #103425;
            color: #8de6ba;
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
            background: #f8ecd3;
            color: #7f5b15;
        }
        QFrame#DashboardGameCard[status="offline"] QLabel#DashboardBadge {
            background: #ebe9ef;
            color: #675f77;
        }
        QFrame#DashboardGameCard[status="completed"] QLabel#DashboardBadge {
            background: #d7f1e4;
            color: #19603d;
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
        "dashboard_empty": "Adiciona jogos na whitelist para aparecerem aqui.",
        "dashboard_selected": "Alvo manual por jogo: {game}.",
        "dashboard_unset": "Sem alvo manual por jogo.",
        "dashboard_ribbon": "▶ Selecionado",
        "dashboard_ribbon_completed": "CONCLUIDO",
        "dashboard_game_unavailable": "O jogo selecionado ({game}) não está farmável agora.",
        "dashboard_badge_active": "Ativo",
        "dashboard_badge_upcoming": "Brevemente",
        "dashboard_badge_offline": "Sem stream",
        "dashboard_badge_no_data": "Sem dados",
        "dashboard_badge_completed": "Completo",
        "dashboard_completed_tooltip": "Todos os drops deste jogo ja foram concluidos nesta conta.",
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
        "dashboard_empty": "Add games to your whitelist to show them here.",
        "dashboard_selected": "Manual game target: {game}.",
        "dashboard_unset": "No manual game target.",
        "dashboard_ribbon": "▶ Selected",
        "dashboard_ribbon_completed": "COMPLETED",
        "dashboard_game_unavailable": "Selected game ({game}) is not farmable right now.",
        "dashboard_badge_active": "Active",
        "dashboard_badge_upcoming": "Upcoming",
        "dashboard_badge_offline": "No stream",
        "dashboard_badge_no_data": "No data",
        "dashboard_badge_completed": "Completed",
        "dashboard_completed_tooltip": "All drops for this game are already completed on this account.",
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
        self._has_state = False
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        scrollbar = self.verticalScrollBar()
        scrollbar.setSingleStep(5)
        scrollbar.setPageStep(5)
        self.itemClicked.connect(self._toggle_item)

    def set_entries(self, entries: list[FilterEntry], selected_keys: list[str], empty_text: str) -> None:
        self._selected_keys = set(selected_keys)
        self._has_state = True
        self.blockSignals(True)
        self.clear()
        if not entries:
            placeholder = QListWidgetItem(empty_text)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(placeholder)
            self.blockSignals(False)
            return

        for entry in sorted(entries, key=lambda item: item.label.casefold()):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            item.setData(LABEL_ROLE, entry.label)
            self._update_item_appearance(item)
            self.addItem(item)
        self.blockSignals(False)

    def selected_keys(self) -> list[str]:
        return sorted(self._selected_keys)

    def has_state(self) -> bool:
        return self._has_state

    def _toggle_item(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key:
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
        painter.setBrush(QColor(8, 160, 96, 228))
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
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
        self._last_refresh_at: str = ""
        self._last_auto_claim_at: datetime | None = None
        self._last_display_decision: FarmDecision | None = None

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
        self.live_refresh_timer.setInterval(60_000)
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
        preferences_layout.addLayout(language_row)
        preferences_layout.addLayout(theme_row)
        preferences_layout.addLayout(sort_row)
        self.auto_claim_checkbox = QCheckBox()
        self.auto_claim_checkbox.setChecked(bool(self.config.auto_claim_drops))
        preferences_layout.addWidget(self.auto_claim_checkbox)

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

        self.games_whitelist_group = QGroupBox()
        games_whitelist_layout = QVBoxLayout(self.games_whitelist_group)
        self.games_whitelist_hint = QLabel()
        self.games_whitelist_hint.setWordWrap(True)
        self.games_whitelist_list = MarkerListWidget("✓")
        self.games_whitelist_list.itemClicked.connect(lambda _item: self._refresh_dashboard_games())
        games_whitelist_layout.addWidget(self.games_whitelist_hint)
        games_whitelist_layout.addWidget(self.games_whitelist_list)

        self.games_blacklist_group = QGroupBox()
        games_blacklist_layout = QVBoxLayout(self.games_blacklist_group)
        self.games_blacklist_hint = QLabel()
        self.games_blacklist_hint.setWordWrap(True)
        self.games_blacklist_list = MarkerListWidget("X")
        games_blacklist_layout.addWidget(self.games_blacklist_hint)
        games_blacklist_layout.addWidget(self.games_blacklist_list)

        self.channels_whitelist_group = QGroupBox()
        channels_whitelist_layout = QVBoxLayout(self.channels_whitelist_group)
        self.channels_whitelist_hint = QLabel()
        self.channels_whitelist_hint.setWordWrap(True)
        self.channels_whitelist_list = MarkerListWidget("✓")
        channels_whitelist_layout.addWidget(self.channels_whitelist_hint)
        channels_whitelist_layout.addWidget(self.channels_whitelist_list)

        self.channels_blacklist_group = QGroupBox()
        channels_blacklist_layout = QVBoxLayout(self.channels_blacklist_group)
        self.channels_blacklist_hint = QLabel()
        self.channels_blacklist_hint.setWordWrap(True)
        self.channels_blacklist_list = MarkerListWidget("X")
        channels_blacklist_layout.addWidget(self.channels_blacklist_hint)
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
        account_layout.addWidget(self.active_lists_note)
        account_layout.addWidget(self.btn_refresh)
        account_layout.addStretch(1)

        filters_tab = QWidget()
        filters_layout = QVBoxLayout(filters_tab)
        filters_layout.addWidget(self.games_whitelist_group)
        filters_layout.addWidget(self.games_blacklist_group)
        filters_layout.addWidget(self.channels_whitelist_group)
        filters_layout.addWidget(self.channels_blacklist_group)
        filters_layout.addStretch(1)

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
        self.farming_now_game_image = QLabel()
        self.farming_now_game_image.setFixedSize(144, 192)
        self.farming_now_game_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        farming_group_layout.addWidget(self.farming_now_game_image, alignment=Qt.AlignmentFlag.AlignHCenter)
        farming_group_layout.addWidget(self.farming_now_game)
        farming_group_layout.addWidget(self.farming_now_campaign)
        farming_group_layout.addWidget(self.farming_now_channel)
        farming_group_layout.addWidget(self.farming_now_next_drop)
        farming_group_layout.addWidget(self.farming_now_eta)
        farming_group_layout.addWidget(self.farming_now_state)
        farming_group_layout.addWidget(self.farming_now_progress_text)
        farming_group_layout.addWidget(self.farming_now_progress)
        farming_group_layout.addWidget(self.farming_now_last_refresh)
        farming_group_layout.addLayout(farming_action_row)
        farming_layout.addWidget(self.farming_now_group)
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

    def _refresh_dashboard_games(self) -> None:
        selected_game = self._forced_farm_game.casefold() if self._forced_farm_game else ""
        whitelist_games = self._dashboard_whitelist_games()
        by_game: dict[str, DropCampaign] = {}
        campaigns_by_game: dict[str, list[DropCampaign]] = {}
        if self.latest_snapshot is not None:
            for campaign in self.latest_snapshot.campaigns:
                key = campaign.game_name.casefold()
                campaigns_by_game.setdefault(key, []).append(campaign)
                if key not in by_game:
                    by_game[key] = campaign
                elif campaign.active and not by_game[key].active:
                    by_game[key] = campaign

        while self.dashboard_games_grid.count():
            child = self.dashboard_games_grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._dashboard_game_cards.clear()

        columns = 3
        for index, game in enumerate(whitelist_games):
            key = game.casefold()
            campaign = by_game.get(key)
            related_campaigns = campaigns_by_game.get(key, [])
            art_url = ""
            if campaign is not None:
                art_url = campaign.game_box_art_url or self._guess_box_art_url(
                    campaign.game_name,
                    campaign.game_slug,
                )
            else:
                art_url = self._guess_box_art_url(game)
            is_farmable_game = False
            if self.latest_snapshot is not None:
                is_farmable_game = any(
                    self._decision_is_farmable_now(decision)
                    and decision.campaign.game_name.casefold() == key
                    for decision in self.latest_snapshot.decisions
                )

            trackable_campaigns = [item for item in related_campaigns if item.required_minutes > 0]
            is_game_completed = bool(trackable_campaigns) and all(item.remaining_minutes <= 0 for item in trackable_campaigns)

            status_kind = "offline"
            badge_text = self._t("dashboard_badge_no_data")
            completion_ribbon_text = ""
            tooltip_text = game
            if is_game_completed:
                status_kind = "completed"
                badge_text = self._t("dashboard_badge_completed")
                completion_ribbon_text = self._t("dashboard_ribbon_completed")
                tooltip_text = self._t("dashboard_completed_tooltip")
            elif campaign is not None:
                if campaign.active and is_farmable_game:
                    status_kind = "active"
                    badge_text = self._t("dashboard_badge_active")
                elif campaign.upcoming:
                    status_kind = "upcoming"
                    badge_text = self._t("dashboard_badge_upcoming")
                else:
                    status_kind = "offline"
                    badge_text = self._t("dashboard_badge_offline")
            card = DashboardGameCard(
                game_name=game,
                title_text=self._dashboard_card_title(game),
                pixmap=self._load_box_art_pixmap(art_url),
                badge_text=badge_text,
                ribbon_text=self._t("dashboard_ribbon"),
                completion_ribbon_text=completion_ribbon_text,
                tooltip_text=tooltip_text,
                farmable=is_farmable_game,
                status_kind=status_kind,
                selected=(key == selected_game),
                on_click=self.handle_dashboard_game_clicked,
            )
            row = index // columns
            col = index % columns
            self.dashboard_games_grid.addWidget(card, row, col)
            self._dashboard_game_cards.append(card)

        for col in range(columns):
            self.dashboard_games_grid.setColumnStretch(col, 1)

        if not whitelist_games:
            self.dashboard_target_label.setText(self._t("dashboard_empty"))
            return
        if self._forced_farm_game:
            self.dashboard_target_label.setText(self._t("dashboard_selected", game=self._forced_farm_game))
            return
        self.dashboard_target_label.setText(self._t("dashboard_unset"))

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

        self.dashboard_group.setTitle(self._t("dashboard_group"))
        self.dashboard_hint_label.setText(self._t("dashboard_hint"))
        
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

        self.active_lists_note.setText(self._t("active_lists_note"))
        self.btn_refresh.setText(self._t("refresh_active"))
        self.games_whitelist_group.setTitle(self._t("games_whitelist_group"))
        self.games_whitelist_hint.setText(self._normalize_marker_text(self._t("games_whitelist_hint", mark=CHECK_MARK)))
        self.games_blacklist_group.setTitle(self._t("games_blacklist_group"))
        self.games_blacklist_hint.setText(self._t("games_blacklist_hint"))
        self.channels_whitelist_group.setTitle(self._t("channels_whitelist_group"))
        self.channels_whitelist_hint.setText(self._normalize_marker_text(self._t("channels_whitelist_hint", mark=CHECK_MARK)))
        self.channels_blacklist_group.setTitle(self._t("channels_blacklist_group"))
        self.channels_blacklist_hint.setText(self._t("channels_blacklist_hint"))
        self.btn_save.setText(self._t("save_settings"))
        self.btn_start.setText(self._t("start_farm"))
        self.btn_stop.setText(self._t("stop_farm"))
        self.btn_farming_start.setText(self._t("farming_start_main"))
        self.btn_farming_pause.setText(self._t("farming_pause_main"))
        self.btn_farming_next.setText(self._t("farming_next_game"))
        self.btn_redeem_drops.setText(self._t("redeem_drops"))
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

    def _decision_is_farmable_now(self, decision: FarmDecision) -> bool:
        campaign = decision.campaign
        if not (campaign.active and campaign.eligible and decision.stream is not None):
            return False
        if campaign.required_minutes > 0 and campaign.remaining_minutes <= 0:
            return False
        return True

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
        pixmap = QPixmap(144, 192)
        pixmap.fill(Qt.GlobalColor.transparent)
        try:
            response = self.client.session.get(target_url, timeout=10)
            response.raise_for_status()
            loaded = QPixmap()
            if loaded.loadFromData(response.content):
                pixmap = loaded
        except requests.RequestException:
            if target_url != BOX_ART_FALLBACK_URL:
                try:
                    response = self.client.session.get(BOX_ART_FALLBACK_URL, timeout=10)
                    response.raise_for_status()
                    loaded = QPixmap()
                    if loaded.loadFromData(response.content):
                        pixmap = loaded
                except requests.RequestException:
                    pass
        scaled = pixmap.scaled(144, 192, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._thumb_cache[target_url] = scaled
        return scaled

    def _guess_box_art_url(self, game_name: str, game_slug: str = "") -> str:
        resolved = self.client.resolve_game_box_art_url(game_name, game_slug=game_slug)
        if resolved:
            return resolved
        slug = quote(game_name.strip(), safe="")
        return f"https://static-cdn.jtvnw.net/ttv-boxart/{slug}-144x192.jpg"

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
            self._refresh_last_update_label()
            return

        active = self._current_farm_decision()
        if active is None:
            active = next(
                (
                    decision
                    for decision in self.latest_snapshot.decisions
                    if self._decision_is_farmable_now(decision)
                ),
                None,
            )
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
            self._refresh_last_update_label()
            return

        campaign = active.campaign
        self._last_display_decision = active
        channel_name = (
            active.stream.display_name or active.stream.login
            if active.stream is not None
            else self._t("channel_unknown")
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
        self.farming_now_game_image.setPixmap(self._load_box_art_pixmap(box_art_url))
        self._refresh_last_update_label()

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
        if decision.used_channel_whitelist:
            return f"{self._t('reason_channel_priority')} {self._t('reason_stream_selected')}"
        return self._t("reason_stream_selected")

    def _refresh_priority_label(self) -> None:
        if not self.latest_snapshot or not self.latest_snapshot.decisions:
            self.best_target_label.setText(self._t("best_target_none"))
            return
        top = next((decision for decision in self.latest_snapshot.decisions if self._decision_is_farmable_now(decision)), None)
        if top is None:
            top = next(
                (
                    decision
                    for decision in self.latest_snapshot.decisions
                    if self._decision_is_farmable_now(decision)
                ),
                None,
            )
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

        # Obtém os jogos da whitelist (compatível com config antiga por label)
        selected_values = self._selected_values(self.games_whitelist_list, self.config.whitelist_games)
        selected_tokens = {value.casefold() for value in selected_values if isinstance(value, str) and value.strip()}
        if not selected_tokens:
            self.dashboard_no_games.setText(self._t("dashboard_empty"))
            self.dashboard_games_grid.addWidget(self.dashboard_no_games, 0, 0)
            return

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

        # Popula a grelha (3 colunas)
        columns = 3
        for idx, entry in enumerate(sorted(filtered_games, key=lambda e: e.label.casefold())):
            row = idx // columns
            col = idx % columns

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
        self._forced_farm_campaign_id = best_decision.campaign.id
        self._forced_farm_channel = best_decision.stream.login
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
        candidates = [
            decision
            for decision in self.latest_snapshot.decisions
            if self._decision_is_farmable_now(decision)
        ]
        if not candidates:
            self._forced_farm_channel = ""
            self._forced_farm_campaign_id = ""
            self._forced_farm_game = ""
            return None
        if self._forced_farm_game:
            game_candidates = [
                decision
                for decision in candidates
                if decision.campaign.game_name.casefold() == self._forced_farm_game.casefold()
            ]
            if game_candidates:
                candidates = game_candidates
            else:
                self._forced_farm_game = ""
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

    def _do_redeem_drops(self, *, auto_mode: bool = False) -> int:
        claimed = self.client.claim_available_drops()
        for message in self.client.consume_diagnostics():
            self._log(message)
        if claimed > 0:
            self._log(self._t("redeem_auto_done", count=claimed) if auto_mode else self._t("redeem_done", count=claimed))
            return claimed
        if not auto_mode:
            self._log(self._t("redeem_none"))
        return claimed

    def _auto_advance_after_claim(self) -> None:
        if not self.timer.isActive() or self.latest_snapshot is None:
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


def run() -> None:
    app = QApplication([])
    _icon = QIcon(str(_ASSETS_DIR / "icon.png"))
    if not _icon.isNull():
        app.setWindowIcon(_icon)
    win = MainWindow()
    win.setWindowIcon(_icon)
    win.show()
    app.exec()
