from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from twitch_drop_farmer.config import AppConfig, load_config, save_config
    from twitch_drop_farmer.farmer import FarmEngine
    from twitch_drop_farmer.twitch_client import TwitchClient
else:
    from .config import AppConfig, load_config, save_config
    from .farmer import FarmEngine
    from .twitch_client import TwitchClient


THEMES: dict[str, str] = {
    "twitch": "QWidget { background: #0E0E10; color: #EFEFF1; } QPushButton { background: #9147FF; color: white; padding: 6px; border-radius: 6px; }",
    "black_red": "QWidget { background: #050505; color: #F2F2F2; } QPushButton { background: #B00020; color: white; padding: 6px; border-radius: 6px; }",
    "light": "QWidget { background: #F7F7F8; color: #111; } QPushButton { background: #6441A4; color: white; padding: 6px; border-radius: 6px; }",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Twitch Drop Farmer")
        self.resize(960, 620)

        self.config = load_config()
        self.client = TwitchClient()
        self.engine = FarmEngine(self.client, self.config)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QGridLayout(root)

        left = self._build_left_panel()
        right = self._build_right_panel()
        layout.addWidget(left, 0, 0)
        layout.addWidget(right, 0, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_snapshot)
        self._apply_theme(self.config.theme)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)

        auth = QGroupBox("OAuth")
        auth_layout = QVBoxLayout(auth)
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Cole aqui o token OAuth")
        btn_login = QPushButton("Guardar OAuth")
        btn_login.clicked.connect(self.handle_login)
        auth_layout.addWidget(self.token_input)
        auth_layout.addWidget(btn_login)

        filters = QGroupBox("Filtros")
        filters_layout = QVBoxLayout(filters)
        self.whitelist_input = QLineEdit(", ".join(self.config.whitelist_games))
        self.blacklist_input = QLineEdit(", ".join(self.config.blacklist_games))
        self.channel_blacklist_input = QLineEdit(", ".join(self.config.blacklist_channels))
        filters_layout.addWidget(QLabel("Whitelist de jogos (csv):"))
        filters_layout.addWidget(self.whitelist_input)
        filters_layout.addWidget(QLabel("Blacklist de jogos (csv):"))
        filters_layout.addWidget(self.blacklist_input)
        filters_layout.addWidget(QLabel("Blacklist de canais (csv):"))
        filters_layout.addWidget(self.channel_blacklist_input)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Tema:"))
        self.theme_picker = QComboBox()
        self.theme_picker.addItems(sorted(THEMES.keys()))
        self.theme_picker.setCurrentText(self.config.theme)
        self.theme_picker.currentTextChanged.connect(self._apply_theme)
        theme_row.addWidget(self.theme_picker)

        btn_save = QPushButton("Guardar definições")
        btn_save.clicked.connect(self.handle_save_config)
        btn_start = QPushButton("Iniciar farm")
        btn_start.clicked.connect(self.handle_start)
        btn_stop = QPushButton("Parar farm")
        btn_stop.clicked.connect(self.handle_stop)

        vbox.addWidget(auth)
        vbox.addWidget(filters)
        vbox.addLayout(theme_row)
        vbox.addWidget(btn_save)
        vbox.addWidget(btn_start)
        vbox.addWidget(btn_stop)
        vbox.addStretch(1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.addWidget(QLabel("Campanhas detectadas"))
        self.campaign_list = QListWidget()
        vbox.addWidget(self.campaign_list)
        vbox.addWidget(QLabel("Log"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        vbox.addWidget(self.log_output)
        return panel

    def _csv(self, raw: str) -> list[str]:
        return [x.strip() for x in raw.split(",") if x.strip()]

    def _apply_theme(self, name: str) -> None:
        css = THEMES.get(name, THEMES["twitch"])
        self.setStyleSheet(css)

    def _log(self, message: str) -> None:
        self.log_output.append(message)

    def _with_errors(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:
            QMessageBox.critical(self, "Erro", str(exc))

    def handle_login(self) -> None:
        self._with_errors(lambda: self._do_login())

    def _do_login(self) -> None:
        self.client.set_oauth_token(self.token_input.text())
        self._log("OAuth guardado em cookies locais.")

    def handle_save_config(self) -> None:
        self._with_errors(lambda: self._do_save_config())

    def _do_save_config(self) -> None:
        self.config.whitelist_games = self._csv(self.whitelist_input.text())
        self.config.blacklist_games = self._csv(self.blacklist_input.text())
        self.config.blacklist_channels = self._csv(self.channel_blacklist_input.text())
        self.config.theme = self.theme_picker.currentText()
        save_config(self.config)
        self.engine.config = self.config
        self._log("Definições guardadas.")

    def handle_start(self) -> None:
        self._with_errors(lambda: self._do_start())

    def _do_start(self) -> None:
        self.timer.start(self.config.auto_switch_interval_sec * 1000)
        self.refresh_snapshot()
        self._log("Farm automático iniciado.")

    def handle_stop(self) -> None:
        self.timer.stop()
        self._log("Farm parado.")

    def refresh_snapshot(self) -> None:
        self._with_errors(lambda: self._do_refresh())

    def _do_refresh(self) -> None:
        snapshot = self.engine.poll()
        self.campaign_list.clear()
        for decision in snapshot.decisions:
            target = decision.stream.display_name if decision.stream else "-"
            item = QListWidgetItem(
                f"{decision.campaign.game_name} | {decision.campaign.title} | canal: {target} | {decision.reason}"
            )
            self.campaign_list.addItem(item)
        self._log(f"Atualização concluída: {len(snapshot.decisions)} campanhas.")


def run() -> None:
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    run()
