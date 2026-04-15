from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import requests

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
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
            "Token necessario: copia o valor do cookie 'auth-token' da sessao em https://www.twitch.tv .\n"
            "Nao copies 'api_token' nem o nome do cookie.\n"
            "Passos rapidos:\n"
            "1. Inicia sessao na Twitch no navegador.\n"
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
        "auth_invalid": "O auth-token atual nao foi validado.",
        "preferences_group": "Preferencias",
        "language_label": "Idioma:",
        "theme_label": "Tema:",
        "sort_label": "Prioridade de farm:",
        "theme_twitch": "Twitch",
        "theme_black_red": "Black / Red",
        "theme_light": "Claro",
        "sort_ending_soonest": "Terminam mais cedo",
        "sort_least_remaining": "Menos minutos em falta",
        "sort_most_remaining": "Mais minutos em falta",
        "sort_shortest_campaign": "Menor duracao total",
        "sort_longest_campaign": "Maior duracao total",
        "refresh_active": "Atualizar campanhas e streams",
        "active_lists_note": "As listas abaixo sao geradas a partir das campanhas e canais ativos devolvidos pela Twitch.",
        "games_whitelist_group": "Whitelist de jogos",
        "games_blacklist_group": "Blacklist de jogos",
        "channels_whitelist_group": "Whitelist de canais",
        "channels_blacklist_group": "Blacklist de canais",
        "games_whitelist_hint": "✓ Seleciona apenas os jogos que queres farmar. Se nada estiver marcado, todos os jogos ativos podem ser farmados.",
        "games_blacklist_hint": "X Marca os jogos que devem ser ignorados. Se nada estiver marcado, nenhum jogo e excluido.",
        "channels_whitelist_hint": "✓ Estes canais tem prioridade. Se nenhum estiver disponivel, a app usa os restantes canais ativos.",
        "channels_blacklist_hint": "X Estes canais nunca serao usados. Se nada estiver marcado, nenhum canal e bloqueado.",
        "no_active_games": "Ainda nao ha jogos ativos para mostrar.",
        "no_active_channels": "Ainda nao ha canais ativos para mostrar.",
        "save_settings": "Guardar definicoes",
        "start_farm": "Iniciar farm",
        "stop_farm": "Parar farm",
        "campaigns_detected": "Campanhas detetadas",
        "campaigns_detected_count": "Campanhas detetadas ({count})",
        "tab_farming_now": "A farmar agora",
        "tab_campaign_explorer": "Campanhas",
        "farming_now_group": "Estado atual de farming",
        "farming_now_idle": "Nenhuma campanha ativa a ser farmada neste momento.",
        "farming_now_game": "Jogo: {game}",
        "farming_now_campaign": "Campanha: {campaign}",
        "farming_now_channel": "Canal em visualizacao: {channel}",
        "farming_now_next_drop": "Proximo drop: {drop}",
        "farming_now_eta": "Tempo para o proximo drop: {eta}",
        "farming_now_progress": "Progresso da campanha: {progress}/{required} min",
        "drop_unknown": "Desconhecido",
        "campaign_filter_status": "Mostrar:",
        "campaign_filter_link": "Ligacao:",
        "campaign_sort_label": "Ordenar por:",
        "campaign_status_all": "Todas",
        "campaign_status_active": "Ativas",
        "campaign_status_upcoming": "Futuras",
        "campaign_status_farmable": "Farmaveis agora",
        "campaign_link_all": "Todas",
        "campaign_link_eligible": "Conta ligada/eligivel",
        "campaign_link_unlinked": "Por ligar",
        "campaign_sort_priority": "Prioridade de farm",
        "campaign_sort_ending": "Terminam mais cedo",
        "campaign_sort_progress": "Mais progresso",
        "campaign_sort_remaining": "Menos minutos em falta",
        "campaign_sort_game": "Jogo (A-Z)",
        "best_target_none": "Sem alvo prioritario neste momento.",
        "best_target": "Melhor alvo atual: {game} -> {channel} | ordenacao: {sort_mode}",
        "best_target_no_stream": "Nenhuma stream valida para {game} | ordenacao: {sort_mode}",
        "campaign_details_none": "Seleciona uma campanha para veres o estado da ligacao e o link de conta.",
        "campaign_details": (
            "Jogo: {game}\n"
            "Campanha: {title}\n"
            "Estado: {status}\n"
            "Conta ligada: {linked}\n"
            "Progresso: {progress}/{required} min\n"
            "Canais permitidos pela campanha: {allowed}\n"
            "Ligacao da conta: {link_status}"
        ),
        "linked_yes": "Sim",
        "linked_no": "Nao",
        "linked_label": "ligada",
        "allowed_any": "Qualquer canal drops-enabled",
        "link_status_open_browser": "Disponivel pelo botao abaixo",
        "link_status_unavailable": "Nao necessario ou indisponivel",
        "link_account": "Ligar conta desta campanha",
        "open_drops_page": "Abrir pagina de Drops",
        "link_button_disabled": "Seleciona uma campanha com conta por ligar.",
        "log_label": "Log",
        "error_title": "Erro",
        "oauth_saved": "auth-token guardado e validado.",
        "oauth_refreshing": "Token validado. A atualizar campanhas...",
        "settings_saved": "Definicoes guardadas.",
        "farming_started": "Farm automatico iniciado.",
        "farming_stopped": "Farm parado.",
        "refresh_done": "Atualizacao concluida: {count} campanhas.",
        "channel_word": "canal",
        "remaining_word": "faltam",
        "ends_in_word": "termina em",
        "reason_game_filtered": "Jogo filtrado por whitelist/blacklist.",
        "reason_no_valid_stream": "Sem stream valida depois dos filtros.",
        "reason_stream_selected": "Melhor stream por drops ativos e viewers.",
        "reason_channel_priority": "Whitelist de canais aplicada.",
        "reason_account_not_linked": "Conta do jogo ainda nao ligada a esta campanha.",
        "reason_campaign_upcoming": "Campanha ainda nao comecou.",
        "reason_campaign_not_active": "Campanha nao esta ativa neste momento.",
        "link_opened": "Link de campanha aberto no navegador.",
        "drops_page_opened": "Pagina de Drops aberta no navegador.",
        "token_required": "Tens de colar o valor do cookie auth-token antes de guardar.",
    },
    "en": {
        "window_title": "Twitch Drop Farmer",
        "oauth_group": "OAuth",
        "oauth_token_label": "auth-token value",
        "oauth_placeholder": "Paste the auth-token cookie value here",
        "oauth_help": (
            "Required token: copy the value of the 'auth-token' cookie from https://www.twitch.tv .\n"
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
        "campaigns_detected": "Detected campaigns",
        "campaigns_detected_count": "Detected campaigns ({count})",
        "tab_farming_now": "Farming now",
        "tab_campaign_explorer": "Campaigns",
        "farming_now_group": "Current farming status",
        "farming_now_idle": "No active campaign is being farmed right now.",
        "farming_now_game": "Game: {game}",
        "farming_now_campaign": "Campaign: {campaign}",
        "farming_now_channel": "Watching channel: {channel}",
        "farming_now_next_drop": "Next drop: {drop}",
        "farming_now_eta": "Time to next drop: {eta}",
        "farming_now_progress": "Campaign progress: {progress}/{required} min",
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
        "refresh_done": "Refresh complete: {count} campaigns.",
        "channel_word": "channel",
        "remaining_word": "remaining",
        "ends_in_word": "ends in",
        "reason_game_filtered": "Game filtered by whitelist/blacklist.",
        "reason_no_valid_stream": "No valid stream after filters.",
        "reason_stream_selected": "Best stream by drops enabled and viewers.",
        "reason_channel_priority": "Channel whitelist priority applied.",
        "reason_account_not_linked": "Game account is not linked for this campaign yet.",
        "reason_campaign_upcoming": "Campaign has not started yet.",
        "reason_campaign_not_active": "Campaign is not active right now.",
        "link_opened": "Campaign link opened in the browser.",
        "drops_page_opened": "Drops page opened in the browser.",
        "token_required": "You need to paste the auth-token cookie value before saving.",
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

        self._retranslate_ui()
        self._refresh_filter_lists()
        self._apply_theme(self.config.theme)
        self._set_oauth_hidden(self._oauth_hidden)
        self._update_auth_status()

    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        vbox = QVBoxLayout(panel)

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

        self.active_lists_note = QLabel()
        self.active_lists_note.setWordWrap(True)
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(self.refresh_snapshot)

        self.games_whitelist_group = QGroupBox()
        games_whitelist_layout = QVBoxLayout(self.games_whitelist_group)
        self.games_whitelist_hint = QLabel()
        self.games_whitelist_hint.setWordWrap(True)
        self.games_whitelist_list = MarkerListWidget("✓")
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

        vbox.addWidget(self.oauth_group)
        vbox.addWidget(self.preferences_group)
        vbox.addWidget(self.active_lists_note)
        vbox.addWidget(self.btn_refresh)
        vbox.addWidget(self.games_whitelist_group)
        vbox.addWidget(self.games_blacklist_group)
        vbox.addWidget(self.channels_whitelist_group)
        vbox.addWidget(self.channels_blacklist_group)
        vbox.addWidget(self.btn_save)
        vbox.addWidget(self.btn_start)
        vbox.addWidget(self.btn_stop)
        vbox.addStretch(1)

        scroll.setWidget(panel)
        return scroll

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
        self.farming_now_progress_text = QLabel()
        self.farming_now_progress = QProgressBar()
        self.farming_now_progress.setRange(0, 1000)
        farming_group_layout.addWidget(self.farming_now_game_image, alignment=Qt.AlignmentFlag.AlignHCenter)
        farming_group_layout.addWidget(self.farming_now_game)
        farming_group_layout.addWidget(self.farming_now_campaign)
        farming_group_layout.addWidget(self.farming_now_channel)
        farming_group_layout.addWidget(self.farming_now_next_drop)
        farming_group_layout.addWidget(self.farming_now_eta)
        farming_group_layout.addWidget(self.farming_now_progress_text)
        farming_group_layout.addWidget(self.farming_now_progress)
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

    def _refresh_campaigns_label(self) -> None:
        count = len(self._filtered_decisions()) if self.latest_snapshot else 0
        if count:
            self.campaigns_label.setText(self._t("campaigns_detected_count", count=count))
        else:
            self.campaigns_label.setText(self._t("campaigns_detected"))

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self._t("window_title"))
        self.tabs_right.setTabText(0, self._t("tab_farming_now"))
        self.tabs_right.setTabText(1, self._t("tab_campaign_explorer"))
        self.oauth_group.setTitle(self._t("oauth_group"))
        self.oauth_token_label.setText(self._t("oauth_token_label"))
        self.token_input.setPlaceholderText(self._t("oauth_placeholder"))
        self.oauth_help_icon.setToolTip(self._t("oauth_help"))
        self.btn_login.setText(self._t("save_oauth"))
        self.btn_edit_oauth.setText(self._t("edit_oauth"))

        self.preferences_group.setTitle(self._t("preferences_group"))
        self.language_label.setText(self._t("language_label"))
        self.theme_label.setText(self._t("theme_label"))
        self.sort_label.setText(self._t("sort_label"))
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
        self._refresh_priority_label()
        self._refresh_farming_now()
        self._refresh_campaign_list()
        self._refresh_campaign_details()
        self._update_auth_status()

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

    def _load_box_art_pixmap(self, url: str) -> QPixmap:
        cached = self._thumb_cache.get(url)
        if cached is not None:
            return cached
        pixmap = QPixmap(144, 192)
        pixmap.fill(Qt.GlobalColor.transparent)
        if url:
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                loaded = QPixmap()
                if loaded.loadFromData(response.content):
                    pixmap = loaded
            except requests.RequestException:
                pass
        scaled = pixmap.scaled(144, 192, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._thumb_cache[url] = scaled
        return scaled

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
                return decision.campaign.active and decision.campaign.eligible and decision.stream is not None
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
            return

        active = next(
            (
                decision
                for decision in self.latest_snapshot.decisions
                if decision.campaign.active and decision.campaign.eligible and decision.stream is not None
            ),
            None,
        )
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
            return

        campaign = active.campaign
        channel_name = active.stream.display_name or active.stream.login
        next_drop_name = campaign.next_drop_name or self._t("drop_unknown")
        next_drop_eta = self._format_duration(campaign.next_drop_eta_seconds)
        self.farming_now_game.setText(self._t("farming_now_game", game=campaign.game_name))
        self.farming_now_campaign.setText(self._t("farming_now_campaign", campaign=campaign.title))
        self.farming_now_channel.setText(self._t("farming_now_channel", channel=channel_name))
        self.farming_now_next_drop.setText(self._t("farming_now_next_drop", drop=next_drop_name))
        self.farming_now_eta.setText(self._t("farming_now_eta", eta=next_drop_eta))
        self.farming_now_progress_text.setText(
            self._t(
                "farming_now_progress",
                progress=campaign.progress_minutes,
                required=campaign.required_minutes,
            )
        )
        self.farming_now_progress.setValue(int(campaign.completion * 1000))
        self.farming_now_game_image.setPixmap(self._load_box_art_pixmap(campaign.game_box_art_url))

    def _reason_text(self, decision: FarmDecision) -> str:
        if decision.reason_code == "game_filtered":
            return self._t("reason_game_filtered")
        if decision.reason_code == "campaign_upcoming":
            return self._t("reason_campaign_upcoming")
        if decision.reason_code == "campaign_not_active":
            return self._t("reason_campaign_not_active")
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
        top = next((decision for decision in self.latest_snapshot.decisions if decision.stream is not None), None)
        if top is None:
            top = next(
                (
                    decision
                    for decision in self.latest_snapshot.decisions
                    if decision.campaign.active and decision.campaign.eligible
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
        save_config(self.config)
        self.engine.config = self.config
        self._log(self._t("settings_saved"))
        if self.latest_snapshot is not None:
            self.refresh_snapshot()

    def handle_start(self) -> None:
        self._with_errors(self._do_start)

    def _do_start(self) -> None:
        self.timer.start(self.config.auto_switch_interval_sec * 1000)
        self.refresh_snapshot()
        self._log(self._t("farming_started"))

    def handle_stop(self) -> None:
        self.timer.stop()
        self._log(self._t("farming_stopped"))

    def handle_campaign_selection_changed(self) -> None:
        self._refresh_campaign_details()

    def _handle_campaign_filters_changed(self) -> None:
        self._refresh_campaigns_label()
        self._refresh_campaign_list()
        self._refresh_campaign_details()

    def handle_link_account(self) -> None:
        decision = self._selected_decision()
        if decision is None or not decision.campaign.link_url:
            return
        QDesktopServices.openUrl(QUrl(decision.campaign.link_url))
        self._log(self._t("link_opened"))

    def handle_open_drops_page(self) -> None:
        QDesktopServices.openUrl(QUrl("https://www.twitch.tv/drops/inventory"))
        self._log(self._t("drops_page_opened"))

    def refresh_snapshot(self) -> None:
        self._with_errors(self._do_refresh)

    def _do_refresh(self) -> None:
        snapshot = self.engine.poll()
        self.latest_snapshot = snapshot
        self.engine.config = self.config
        self.available_game_entries = [FilterEntry(key=game_name, label=game_name) for game_name in snapshot.available_games]
        self.available_channel_entries = [FilterEntry(key=channel.login, label=channel.label) for channel in snapshot.available_channels]
        self._refresh_filter_lists()
        self._refresh_campaigns_label()
        self._refresh_priority_label()
        self._refresh_farming_now()
        self._refresh_campaign_list()
        self._refresh_campaign_details()
        self._update_auth_status()
        for message in snapshot.messages:
            self._log(message)
        self._log(self._t("refresh_done", count=len(snapshot.decisions)))


def run() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
