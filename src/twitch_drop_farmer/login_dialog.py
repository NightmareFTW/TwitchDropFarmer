"""The "Log in" window: two ways to sign in, each explained step by step.

The window only shows the steps and the result. What each button really does lives in the
main window (``owner``), so the "Account" tab and this window can never disagree.
"""
from __future__ import annotations

import html
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

TWITCH_URL = "https://www.twitch.tv"


class LoginOwner(Protocol):
    """What the window needs from the main window."""

    def _t(self, key: str, **kwargs: object) -> str: ...
    def login_status_text(self) -> str: ...
    def login_remember_enabled(self) -> bool: ...
    def login_set_remember(self, enabled: bool) -> bool: ...
    def login_import_session(self, text: str) -> None: ...
    def login_validate_session(self) -> None: ...
    def login_export_session(self) -> str: ...
    def login_with_token(self, token: str) -> None: ...
    def login_open_twitch(self) -> None: ...


class LoginDialog(QDialog):
    def __init__(self, owner: LoginOwner, parent: QWidget | None = None, *, error: str = "") -> None:
        super().__init__(parent)
        self._owner = owner
        self.setModal(True)
        self.setMinimumWidth(600)
        self.resize(660, 660)  # fits a 768 px high screen; each tab scrolls if the text needs more

        layout = QVBoxLayout(self)
        self.intro_label = self._label()
        self.status_label = self._label()
        layout.addWidget(self.intro_label)
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_session_tab(), "")
        self.tabs.addTab(self._build_token_tab(), "")
        layout.addWidget(self.tabs, 1)

        self.remember_checkbox = QCheckBox()
        self.remember_checkbox.setChecked(owner.login_remember_enabled())
        self.remember_checkbox.toggled.connect(self._on_remember_toggled)
        self.remember_help = self._label()
        self.remember_help.setStyleSheet("color: #8f95a3;")
        layout.addWidget(self.remember_checkbox)
        layout.addWidget(self.remember_help)

        self.message_label = self._label()
        layout.addWidget(self.message_label)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.btn_close = QPushButton()
        self.btn_close.clicked.connect(self.reject)
        footer.addWidget(self.btn_close)
        layout.addLayout(footer)

        self.retranslate()
        if error:
            self.show_message(error, ok=False)

    # ---- construction ----

    @staticmethod
    def _label() -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _build_session_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.session_intro = self._label()
        self.step1_label = self._label()
        self.session_input = QTextEdit()
        self.session_input.setAcceptRichText(False)
        self.session_input.setMaximumHeight(90)
        self.btn_import = QPushButton()
        self.btn_import.clicked.connect(self._do_import)
        self.step2_label = self._label()
        self.btn_validate = QPushButton()
        self.btn_validate.clicked.connect(self._do_validate)
        self.step3_label = self._label()
        self.btn_export = QPushButton()
        self.btn_export.clicked.connect(self._do_export)
        for widget in (
            self.session_intro,
            self.step1_label,
            self.session_input,
            self.btn_import,
            self.step2_label,
            self.btn_validate,
            self.step3_label,
            self.btn_export,
        ):
            layout.addWidget(widget)
        layout.addStretch(1)
        return self._scrollable(page)

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(page)
        return area

    def _build_token_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.token_intro = self._label()
        self.btn_open_twitch = QPushButton()
        self.btn_open_twitch.clicked.connect(self._owner.login_open_twitch)
        self.token_warning = self._label()
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setClearButtonEnabled(True)
        self.token_input.returnPressed.connect(self._do_token)
        self.token_show = QCheckBox()
        self.token_show.toggled.connect(self._on_show_token)
        self.btn_token = QPushButton()
        self.btn_token.clicked.connect(self._do_token)
        open_row = QHBoxLayout()
        open_row.addWidget(self.btn_open_twitch)
        open_row.addStretch(1)
        for item in (self.token_intro, open_row, self.token_warning, self.token_input, self.token_show, self.btn_token):
            if isinstance(item, QHBoxLayout):
                layout.addLayout(item)
            else:
                layout.addWidget(item)
        layout.addStretch(1)
        return self._scrollable(page)

    def retranslate(self) -> None:
        t = self._owner._t
        self.setWindowTitle(t("login_dialog_title"))
        self.intro_label.setText(t("login_dialog_intro"))
        self.refresh_status()
        self.tabs.setTabText(0, t("auth_session_export"))
        self.tabs.setTabText(1, t("auth_quick_token"))
        self.session_intro.setText(t("login_session_intro"))
        self.step1_label.setText(t("login_step1"))
        self.session_input.setPlaceholderText(t("login_session_placeholder"))
        self.btn_import.setText(t("btn_import_session"))
        self.step2_label.setText(t("login_step2"))
        self.btn_validate.setText(t("btn_validate_session"))
        self.step3_label.setText(t("login_step3"))
        self.btn_export.setText(t("btn_export_session"))
        self.token_intro.setText(t("login_token_intro"))
        self.btn_open_twitch.setText(t("login_open_twitch"))
        self.token_warning.setText(t("login_token_warning"))
        self.token_input.setPlaceholderText(t("oauth_placeholder"))
        self.token_show.setText(t("login_token_show"))
        self.btn_token.setText(t("login_token_button"))
        self.remember_checkbox.setText(t("login_remember"))
        self.remember_help.setText(t("login_remember_help"))
        self.btn_close.setText(t("login_close"))

    def refresh_status(self) -> None:
        self.status_label.setText(self._owner.login_status_text())

    # ---- feedback ----

    def show_message(self, text: str, *, ok: bool) -> None:
        color = "#2ecc71" if ok else "#ff6b6b"
        self.message_label.setText(f'<span style="color:{color};">{html.escape(text)}</span>')

    def _run(self, action) -> bool:
        """Run one button's action; show what went wrong next to the buttons, not in a popup."""
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - every failure is shown to the user
            self.show_message(self._owner._t("login_failed", error=str(exc)), ok=False)
            self.refresh_status()
            return False
        self.refresh_status()
        return True

    # ---- the buttons ----

    def _do_import(self) -> None:
        if self._run(lambda: self._owner.login_import_session(self.session_input.toPlainText())):
            self.show_message(self._owner._t("login_import_ok"), ok=True)

    def _do_validate(self) -> None:
        if self._run(self._owner.login_validate_session):
            self._succeeded()

    def _do_export(self) -> None:
        exported: list[str] = []
        if self._run(lambda: exported.append(self._owner.login_export_session())):
            self.session_input.setPlainText(exported[0])
            QGuiApplication.clipboard().setText(exported[0])
            self.show_message(self._owner._t("login_export_ok"), ok=True)

    def _do_token(self) -> None:
        if self._run(lambda: self._owner.login_with_token(self.token_input.text())):
            self.token_input.clear()
            self._succeeded()

    def _succeeded(self) -> None:
        # The main window confirms the login with a toast; nothing is left to do here.
        self.accept()

    def _on_show_token(self, shown: bool) -> None:
        self.token_input.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)

    def _on_remember_toggled(self, enabled: bool) -> None:
        # The owner asks the user to confirm saving; if they say no, the box goes back to off.
        accepted = self._owner.login_set_remember(enabled)
        if accepted != enabled:
            self.remember_checkbox.blockSignals(True)
            self.remember_checkbox.setChecked(accepted)
            self.remember_checkbox.blockSignals(False)
        else:
            key = "login_remember_saved" if enabled else "login_remember_forgotten"
            self.show_message(self._owner._t(key), ok=True)
