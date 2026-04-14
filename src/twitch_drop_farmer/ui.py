from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, QTimer
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
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig, load_config, save_config
from .farmer import FarmEngine, FarmSnapshot
from .models import FarmDecision
from .twitch_client import TwitchClient

LABEL_ROLE = int(Qt.ItemDataRole.UserRole) + 1


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
        QLabel#HelpIcon {
            background: #6441a4;
            color: white;
            border-radius: 9px;
            font-weight: 700;
        }
    """,
}

LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("pt_PT", "Português (Portugal)"),
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
        "oauth_token_label": "Token OAuth",
        "oauth_placeholder": "Cole aqui o token OAuth",
        "oauth_help": (
            "Como obter o OAuth:\n"
            "1. Inicia sessão na Twitch no navegador.\n"
            "2. Abre as ferramentas de programador ou um editor de cookies.\n"
            "3. Procura o cookie/token de autenticação da Twitch.\n"
            "4. Cola o valor aqui sem o prefixo 'OAuth '.\n"
            "5. O token fica guardado localmente em ~/.twitch-drop-farmer/cookies.json."
        ),
        "save_oauth": "Guardar OAuth",
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
        "refresh_active": "Atualizar ativos agora",
        "active_lists_note": "As listas abaixo são geradas a partir dos jogos e canais ativos neste momento.",
        "games_whitelist_group": "Whitelist de jogos",
        "games_blacklist_group": "Blacklist de jogos",
        "channels_whitelist_group": "Whitelist de canais",
        "channels_blacklist_group": "Blacklist de canais",
        "games_whitelist_hint": "✓ Seleciona apenas os jogos que queres farmar. Se nada estiver marcado, todos podem ser farmados.",
        "games_blacklist_hint": "X Marca os jogos que devem ser ignorados. Se nada estiver marcado, nenhum jogo é excluído.",
        "channels_whitelist_hint": "✓ Estes canais têm prioridade. Se nenhum estiver online, a app usa os restantes canais ativos.",
        "channels_blacklist_hint": "X Estes canais nunca serão usados. Se nada estiver marcado, nenhum canal é bloqueado.",
        "no_active_games": "Ainda não há jogos ativos para mostrar.",
        "no_active_channels": "Ainda não há canais ativos para mostrar.",
        "save_settings": "Guardar definições",
        "start_farm": "Iniciar farm",
        "stop_farm": "Parar farm",
        "campaigns_detected": "Campanhas detetadas",
        "best_target_none": "Sem alvo prioritário neste momento.",
        "best_target": "Melhor alvo atual: {game} -> {channel} | ordenação: {sort_mode}",
        "best_target_no_stream": "Nenhuma stream válida para {game} | ordenação: {sort_mode}",
        "log_label": "Log",
        "error_title": "Erro",
        "oauth_saved": "OAuth guardado em cookies locais.",
        "settings_saved": "Definições guardadas.",
        "farming_started": "Farm automático iniciado.",
        "farming_stopped": "Farm parado.",
        "refresh_done": "Atualização concluída: {count} campanhas.",
        "channel_word": "canal",
        "remaining_word": "faltam",
        "ends_in_word": "termina em",
        "reason_game_filtered": "Jogo filtrado por whitelist/blacklist.",
        "reason_no_valid_stream": "Sem stream válida depois dos filtros.",
        "reason_stream_selected": "Melhor stream por drops ativos e viewers.",
        "reason_channel_priority": "Whitelist de canais aplicada.",
    },
    "en": {
        "window_title": "Twitch Drop Farmer",
        "oauth_group": "OAuth",
        "oauth_token_label": "OAuth token",
        "oauth_placeholder": "Paste the OAuth token here",
        "oauth_help": (
            "How to obtain the OAuth token:\n"
            "1. Sign in to Twitch in your browser.\n"
            "2. Open developer tools or a cookie editor.\n"
            "3. Find the Twitch authentication cookie/token.\n"
            "4. Paste the value here without the 'OAuth ' prefix.\n"
            "5. The token is stored locally in ~/.twitch-drop-farmer/cookies.json."
        ),
        "save_oauth": "Save OAuth",
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
        "refresh_active": "Refresh active data",
        "active_lists_note": "The lists below are built from the games and channels that are active right now.",
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
        "best_target_none": "No priority target right now.",
        "best_target": "Current best target: {game} -> {channel} | order: {sort_mode}",
        "best_target_no_stream": "No valid stream for {game} | order: {sort_mode}",
        "log_label": "Log",
        "error_title": "Error",
        "oauth_saved": "OAuth stored in local cookies.",
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
    },
}


@dataclass(frozen=True)
class FilterEntry:
    key: str
    label: str


class MarkerListWidget(QListWidget):
    def __init__(self, marker: str) -> None:
        super().__init__()
        self._marker = marker
        self._selected_keys: set[str] = set()
        self._has_state = False
        self._has_real_entries = False
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.itemClicked.connect(self._toggle_item)

    def set_entries(
        self,
        entries: list[FilterEntry],
        selected_keys: list[str],
        empty_text: str,
    ) -> None:
        self._selected_keys = set(selected_keys)
        self._has_state = True
        self._has_real_entries = bool(entries)
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

    def has_real_entries(self) -> bool:
        return self._has_real_entries

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
        is_selected = bool(key and key in self._selected_keys)
        item.setText(f"{self._marker} {label}" if is_selected else label)
        font = item.font()
        font.setBold(is_selected)
        item.setFont(font)
        item.setToolTip(label)


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

        self.setWindowTitle("Twitch Drop Farmer")
        self.resize(1240, 760)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QGridLayout(root)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 2)

        left = self._build_left_panel()
        right = self._build_right_panel()
        layout.addWidget(left, 0, 0)
        layout.addWidget(right, 0, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_snapshot)

        self.token_input.setText(self.client.login_state.oauth_token)
        self._retranslate_ui()
        self._refresh_filter_lists()
        self._apply_theme(self.config.theme)

    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        panel = QWidget()
        vbox = QVBoxLayout(panel)

        self.oauth_group = QGroupBox()
        auth_layout = QVBoxLayout(self.oauth_group)
        token_label_row = QHBoxLayout()
        self.oauth_token_label = QLabel()
        self.oauth_help_icon = QLabel("?")
        self.oauth_help_icon.setObjectName("HelpIcon")
        self.oauth_help_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.oauth_help_icon.setFixedSize(18, 18)
        token_label_row.addWidget(self.oauth_token_label)
        token_label_row.addWidget(self.oauth_help_icon)
        token_label_row.addStretch(1)
        self.token_input = QLineEdit()
        self.btn_login = QPushButton()
        self.btn_login.clicked.connect(self.handle_login)
        auth_layout.addLayout(token_label_row)
        auth_layout.addWidget(self.token_input)
        auth_layout.addWidget(self.btn_login)

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
        self.best_target_label = QLabel()
        self.best_target_label.setWordWrap(True)
        self.campaigns_label = QLabel()
        self.campaign_list = QListWidget()
        self.log_label = QLabel()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        vbox.addWidget(self.best_target_label)
        vbox.addWidget(self.campaigns_label)
        vbox.addWidget(self.campaign_list, 2)
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

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self._t("window_title"))
        self.oauth_group.setTitle(self._t("oauth_group"))
        self.oauth_token_label.setText(self._t("oauth_token_label"))
        self.token_input.setPlaceholderText(self._t("oauth_placeholder"))
        self.oauth_help_icon.setToolTip(self._t("oauth_help"))
        self.btn_login.setText(self._t("save_oauth"))

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
        self.games_whitelist_hint.setText(self._t("games_whitelist_hint"))
        self.games_blacklist_group.setTitle(self._t("games_blacklist_group"))
        self.games_blacklist_hint.setText(self._t("games_blacklist_hint"))
        self.channels_whitelist_group.setTitle(self._t("channels_whitelist_group"))
        self.channels_whitelist_hint.setText(self._t("channels_whitelist_hint"))
        self.channels_blacklist_group.setTitle(self._t("channels_blacklist_group"))
        self.channels_blacklist_hint.setText(self._t("channels_blacklist_hint"))

        self.btn_save.setText(self._t("save_settings"))
        self.btn_start.setText(self._t("start_farm"))
        self.btn_stop.setText(self._t("stop_farm"))
        self.campaigns_label.setText(self._t("campaigns_detected"))
        self.log_label.setText(self._t("log_label"))
        self._refresh_filter_lists()
        self._refresh_priority_label()
        self._refresh_campaign_list()

    def _selected_values(self, widget: MarkerListWidget, fallback: list[str]) -> list[str]:
        if widget.has_state():
            return widget.selected_keys()
        return list(fallback)

    def _refresh_filter_lists(self) -> None:
        game_selection_whitelist = self._selected_values(self.games_whitelist_list, self.config.whitelist_games)
        game_selection_blacklist = self._selected_values(self.games_blacklist_list, self.config.blacklist_games)
        channel_selection_whitelist = self._selected_values(self.channels_whitelist_list, self.config.whitelist_channels)
        channel_selection_blacklist = self._selected_values(self.channels_blacklist_list, self.config.blacklist_channels)

        self.games_whitelist_list.set_entries(self.available_game_entries, game_selection_whitelist, self._t("no_active_games"))
        self.games_blacklist_list.set_entries(self.available_game_entries, game_selection_blacklist, self._t("no_active_games"))
        self.channels_whitelist_list.set_entries(self.available_channel_entries, channel_selection_whitelist, self._t("no_active_channels"))
        self.channels_blacklist_list.set_entries(self.available_channel_entries, channel_selection_blacklist, self._t("no_active_channels"))

    def _apply_theme(self, name: str) -> None:
        self.setStyleSheet(THEMES.get(name, THEMES["twitch"]))

    def _log(self, message: str) -> None:
        self.log_output.append(message)

    def _with_errors(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:
            QMessageBox.critical(self, self._t("error_title"), str(exc))

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

    def _reason_text(self, decision: FarmDecision) -> str:
        if decision.reason_code == "game_filtered":
            return self._t("reason_game_filtered")
        if decision.reason_code == "no_valid_stream":
            return self._t("reason_no_valid_stream")
        if decision.used_channel_whitelist:
            return f"{self._t('reason_channel_priority')} {self._t('reason_stream_selected')}"
        return self._t("reason_stream_selected")

    def _refresh_priority_label(self) -> None:
        if not self.latest_snapshot or not self.latest_snapshot.decisions:
            self.best_target_label.setText(self._t("best_target_none"))
            return
        top_decision = self.latest_snapshot.decisions[0]
        if top_decision.stream is None:
            self.best_target_label.setText(
                self._t(
                    "best_target_no_stream",
                    game=top_decision.campaign.game_name,
                    sort_mode=self._sort_mode_label(),
                )
            )
            return
        self.best_target_label.setText(
            self._t(
                "best_target",
                game=top_decision.campaign.game_name,
                channel=top_decision.stream.display_name or top_decision.stream.login,
                sort_mode=self._sort_mode_label(),
            )
        )

    def _refresh_campaign_list(self) -> None:
        self.campaign_list.clear()
        if not self.latest_snapshot:
            return
        for decision in self.latest_snapshot.decisions:
            target = decision.stream.display_name if decision.stream else "-"
            item = QListWidgetItem(
                (
                    f"{decision.campaign.game_name} | {decision.campaign.title} | "
                    f"{self._t('channel_word')}: {target} | "
                    f"{self._t('remaining_word')}: {decision.campaign.remaining_minutes}m | "
                    f"{self._t('ends_in_word')}: {self._format_duration(decision.campaign.seconds_until_end)} | "
                    f"{self._reason_text(decision)}"
                )
            )
            self.campaign_list.addItem(item)

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
        self.client.set_oauth_token(self.token_input.text())
        self._log(self._t("oauth_saved"))

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

    def handle_start(self) -> None:
        self._with_errors(self._do_start)

    def _do_start(self) -> None:
        self.timer.start(self.config.auto_switch_interval_sec * 1000)
        self.refresh_snapshot()
        self._log(self._t("farming_started"))

    def handle_stop(self) -> None:
        self.timer.stop()
        self._log(self._t("farming_stopped"))

    def refresh_snapshot(self) -> None:
        self._with_errors(self._do_refresh)

    def _do_refresh(self) -> None:
        snapshot = self.engine.poll()
        self.latest_snapshot = snapshot
        self.available_game_entries = [FilterEntry(key=game_name, label=game_name) for game_name in snapshot.available_games]
        self.available_channel_entries = [FilterEntry(key=channel.login, label=channel.label) for channel in snapshot.available_channels]
        self._refresh_filter_lists()
        self._refresh_priority_label()
        self._refresh_campaign_list()
        self._log(self._t("refresh_done", count=len(snapshot.decisions)))


def run() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
