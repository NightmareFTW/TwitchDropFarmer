"""Every button of the real window does what its label says (no network, no dialogs, no browser)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import requests

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton  # noqa: E402

import twitch_drop_farmer.ui as ui  # noqa: E402
from twitch_drop_farmer import config as config_module  # noqa: E402
from twitch_drop_farmer import twitch_client as tc  # noqa: E402
from twitch_drop_farmer import updater  # noqa: E402
from twitch_drop_farmer.farmer import FarmSnapshot  # noqa: E402
from twitch_drop_farmer.models import DropCampaign, FarmDecision, StreamCandidate  # noqa: E402

UTC = timezone.utc


def _campaign(name: str, *, link_url: str = "", cid: str | None = None) -> DropCampaign:
    return DropCampaign(
        id=cid or f"id-{name}", game_name=name, title=f"{name} campaign",
        starts_at=datetime.now(UTC) - timedelta(days=1), ends_at=datetime.now(UTC) + timedelta(days=3),
        status="ACTIVE", required_minutes=360, progress_minutes=100, has_watchable_drops=True,
        link_url=link_url,
        drops=[{"id": "d", "name": "r", "required_minutes": 360, "current_minutes": 100, "claimed": False}],
    )


def _decision(campaign: DropCampaign, *, stream: bool = True) -> FarmDecision:
    candidate = StreamCandidate(login=f"{campaign.id}-chan", display_name="Chan", game_name=campaign.game_name,
                                viewer_count=10, drops_enabled=True, channel_id="1") if stream else None
    return FarmDecision(campaign=campaign, stream=candidate, reason_code="stream_selected" if stream else "no_valid_stream")


class _WindowCase(unittest.TestCase):
    """One real MainWindow per test class, isolated from the user's files and from the network."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls._stack = ExitStack()
        enter = cls._stack.enter_context
        enter(patch.object(config_module, "CONFIG_DIR", base))
        enter(patch.object(config_module, "CONFIG_FILE", base / "config.json"))
        enter(patch.object(config_module, "COOKIE_FILE", base / "cookies.json"))
        enter(patch.object(config_module, "CAMPAIGN_CACHE_FILE", base / "campaign_cache.json"))
        enter(patch.object(config_module, "SESSION_FILE", base / "session.json"))
        enter(patch.object(tc, "SESSION_FILE", base / "session.json"))
        enter(patch.object(config_module, "REGISTRY_REWARDS_FILE", base / "registry_rewards.json"))
        enter(patch.object(tc, "REGISTRY_REWARDS_FILE", base / "registry_rewards.json"))
        enter(patch.object(tc, "CONFIG_DIR", base))
        enter(patch.object(tc, "COOKIE_FILE", base / "cookies.json"))
        enter(patch.object(tc, "CAMPAIGN_CACHE_FILE", base / "campaign_cache.json"))
        enter(patch.object(ui, "CONFIG_DIR", base))
        # No network at all, no browser, no dialogs, no desktop services.
        enter(patch("requests.Session.request", side_effect=requests.ConnectionError("offline")))
        enter(patch.object(updater, "urlopen", side_effect=URLError("offline")))
        enter(patch.object(tc.TwitchClient, "claim_available_drops", return_value=0))
        cls.msgbox = enter(patch.object(ui, "QMessageBox"))
        cls.desktop = enter(patch.object(ui, "QDesktopServices"))
        cls.window = ui.MainWindow()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.window.client.segment_watcher.stop()
        for timer in (cls.window.timer, cls.window.streamless_timer, cls.window._autosave_timer):
            timer.stop()
        cls.window.executor.shutdown(wait=False)
        cls._stack.close()
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.msgbox.reset_mock()
        self.desktop.reset_mock()
        self.window.log_output.clear()
        self.window._autosave_timer.stop()

    # ------------------------------------------------------------------ helpers
    def wait_until(self, condition, timeout: float = 5.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return condition()

    def log_text(self) -> str:
        return self.window.log_output.toPlainText()

    def t(self, key: str, **kwargs) -> str:
        return self.window._t(key, **kwargs)


class TestAccountButtons(_WindowCase):
    def test_login_without_a_token_says_a_token_is_needed(self):
        self.window.token_input.setText("")

        self.window.btn_login.click()

        self.msgbox.critical.assert_called_once()
        self.assertIn(self.t("token_required"), self.msgbox.critical.call_args.args)

    def test_login_with_a_token_stores_it_and_reports_instead_of_crashing_when_offline(self):
        self.window.token_input.setText("a" * 30)

        self.window.btn_login.click()

        self.assertEqual(self.window.client.login_state.oauth_token, "a" * 30)
        self.assertTrue(self.msgbox.critical.called or "oauth" in self.log_text().lower() or self.log_text())

    def test_edit_token_shows_the_token_field_again(self):
        self.window.client.login_state.oauth_token = "c" * 30
        self.window._set_oauth_hidden(True)
        self.assertTrue(self.window.btn_edit_oauth.isEnabled())
        self.assertTrue(self.window.token_input.isReadOnly())

        self.window.btn_edit_oauth.click()

        self.assertFalse(self.window._oauth_hidden)
        self.assertFalse(self.window.token_input.isReadOnly())

    def test_edit_token_is_disabled_when_there_is_no_token_to_edit(self):
        self.window.client.login_state.oauth_token = ""
        self.window._set_oauth_hidden(True)

        self.assertFalse(self.window.btn_edit_oauth.isEnabled())

    def test_export_session_without_a_session_says_there_is_nothing_to_export(self):
        self.window.client.login_state.oauth_token = ""

        self.window.btn_export_session.click()

        self.msgbox.critical.assert_called_once()
        self.assertIn(self.t("login_export_needs_session"), self.msgbox.critical.call_args.args)

    def test_export_session_fills_the_box_with_a_json_and_says_so(self):
        self.window.client.login_state.oauth_token = "e" * 30
        self.window.session_input.clear()

        self.window.btn_export_session.click()

        data = json.loads(self.window.session_input.toPlainText())
        self.assertIn("cookies", data)
        self.assertIn(self.t("session_export_success"), self.log_text())

    def test_import_session_with_nothing_pasted_asks_for_the_json(self):
        self.window.session_input.clear()

        self.window.btn_import_session.click()

        self.msgbox.critical.assert_called_once()

    def test_import_session_takes_back_what_was_exported(self):
        self.window.client.login_state.oauth_token = "e" * 30
        self.window.client.login_state.login_name = "someone"
        self.window.btn_export_session.click()
        self.window.client.login_state.login_name = ""

        self.window.btn_import_session.click()

        self.assertEqual(self.window.client.login_state.login_name, "someone")
        self.assertIn("importada", self.log_text())

    def test_import_session_with_garbage_reports_an_error(self):
        self.window.session_input.setPlainText("this is not json")

        self.window.btn_import_session.click()

        self.msgbox.critical.assert_called_once()

    def test_validate_session_without_a_session_says_so(self):
        self.window.client.login_state.oauth_token = ""

        self.window.btn_validate_session.click()

        self.msgbox.critical.assert_called_once()

    def test_validate_session_with_a_token_reports_the_network_error_instead_of_crashing(self):
        self.window.client.login_state.oauth_token = "b" * 30

        self.window.btn_validate_session.click()

        self.msgbox.critical.assert_called_once()

    def test_the_diagnostic_runs_disables_the_buttons_meanwhile_and_shows_the_result(self):
        status = SimpleNamespace(value="passed")
        report = SimpleNamespace(
            results=[SimpleNamespace(name="Token check", status=status, message="all good", duration_ms=12.0)],
            overall_status=status, summary="1 test",
        )

        class FakeEngine:
            def __init__(self, _client): ...
            async def run_all_diagnostics(self):
                return report

        with patch("twitch_drop_farmer.diagnostic.DiagnosticEngine", FakeEngine):
            self.window.btn_diagnostic.click()
            self.assertFalse(self.window.btn_diagnostic.isEnabled())
            self.assertFalse(self.window.btn_check_updates.isEnabled())
            self.assertTrue(self.wait_until(self.window.btn_diagnostic.isEnabled))

        self.assertTrue(self.window.btn_check_updates.isEnabled())
        self.assertIn("Token check", self.window.update_status_label.text())

    def test_check_for_updates_reports_a_newer_version(self):
        info = updater.VersionInfo(current="2.2.55", latest="9.9.9", download_url="https://example/x.zip",
                                   is_update_available=True, release_notes="")
        with patch.object(updater, "check_for_updates", return_value=info):
            self.window.btn_check_updates.click()
            self.assertTrue(self.wait_until(self.window.btn_check_updates.isEnabled))

        self.assertIn("9.9.9", self.window.update_status_label.text())

    def test_check_for_updates_says_up_to_date(self):
        info = updater.VersionInfo(current="2.2.55", latest="2.2.55", download_url="", is_update_available=False, release_notes="")
        with patch.object(updater, "check_for_updates", return_value=info):
            self.window.btn_check_updates.click()
            self.assertTrue(self.wait_until(self.window.btn_check_updates.isEnabled))

        self.assertEqual(self.window.update_status_label.text(), self.t("status_updates_uptodate"))

    def test_check_for_updates_offline_says_it_failed_and_re_enables_the_buttons(self):
        self.window.btn_check_updates.click()  # the real updater, with the network cut
        self.assertTrue(self.wait_until(self.window.btn_check_updates.isEnabled))

        self.assertEqual(self.window.update_status_label.text(), self.t("status_updates_failed"))
        self.assertTrue(self.window.btn_diagnostic.isEnabled())

    def test_about_shows_the_version(self):
        self.window.btn_about.click()

        self.msgbox.about.assert_called_once()
        self.assertTrue(any("2." in str(arg) for arg in self.msgbox.about.call_args.args))


class TestFilterButtons(_WindowCase):
    GAMES = ["Alpha Game", "Beta Game", "Gamma Game", "Delta Other", "Echo Other"]
    CHANNELS = ["chan_a", "chan_b", "chan_c", "other_d"]

    def setUp(self) -> None:
        super().setUp()
        w = self.window
        w.available_game_entries = [ui.FilterEntry(key=n, label=n) for n in self.GAMES]
        w.available_channel_entries = [ui.FilterEntry(key=n, label=n) for n in self.CHANNELS]
        w._extra_game_names.clear()
        for widget, entries in (
            (w.games_whitelist_list, w.available_game_entries), (w.games_blacklist_list, w.available_game_entries),
            (w.channels_whitelist_list, w.available_channel_entries), (w.channels_blacklist_list, w.available_channel_entries),
        ):
            widget.set_filter_text("")
            widget.set_entries(entries, [], "")
        w.games_whitelist_search.clear()
        w.games_blacklist_search.clear()
        w.channels_whitelist_search.clear()
        w.channels_blacklist_search.clear()
        w.refresh_snapshot = MagicMock()
        w.config.whitelist_games, w.config.blacklist_games = [], []
        w.config.whitelist_channels, w.config.blacklist_channels = [], []
        w._refresh_filter_lists()
        w._autosave_timer.stop()

    def _lists(self):
        w = self.window
        yield "games whitelist", w.games_whitelist_list, w.games_whitelist_search, [
            w.games_whitelist_select_all_btn, w.games_whitelist_clear_all_btn,
            w.games_whitelist_select_visible_btn, w.games_whitelist_clear_visible_btn], "Other"
        yield "games blacklist", w.games_blacklist_list, w.games_blacklist_search, [
            w.games_blacklist_select_all_btn, w.games_blacklist_clear_all_btn,
            w.games_blacklist_select_visible_btn, w.games_blacklist_clear_visible_btn], "Other"
        yield "channels whitelist", w.channels_whitelist_list, w.channels_whitelist_search, [
            w.channels_whitelist_select_all_btn, w.channels_whitelist_clear_all_btn,
            w.channels_whitelist_select_visible_btn, w.channels_whitelist_clear_visible_btn], "chan"
        yield "channels blacklist", w.channels_blacklist_list, w.channels_blacklist_search, [
            w.channels_blacklist_select_all_btn, w.channels_blacklist_clear_all_btn,
            w.channels_blacklist_select_visible_btn, w.channels_blacklist_clear_visible_btn], "chan"

    def test_the_four_buttons_of_each_of_the_four_lists_do_what_they_say(self):
        for name, widget, search, (select_all, clear_all, select_visible, clear_visible), term in self._lists():
            with self.subTest(name):
                everything = {entry.key for entry in widget._all_entries}
                select_all.click()
                self.assertEqual(set(widget.selected_keys()), everything, "select all")
                clear_all.click()
                self.assertEqual(widget.selected_keys(), [], "clear all")

                search.setText(term)  # only some entries stay visible
                visible = {entry.key for entry in widget._filtered_entries}
                self.assertTrue(0 < len(visible) < len(everything))
                select_visible.click()
                self.assertEqual(set(widget.selected_keys()), visible, "select visible")
                search.clear()
                select_all.click()
                search.setText(term)
                clear_visible.click()
                self.assertEqual(set(widget.selected_keys()), everything - visible, "clear visible")
                search.clear()
                clear_all.click()

    def test_every_one_of_those_clicks_is_saved_automatically(self):
        w = self.window
        w.games_blacklist_select_all_btn.click()

        self.assertTrue(w._autosave_timer.isActive())
        w._autosave_now()
        self.assertEqual(set(config_module.load_config().blacklist_games), set(self.GAMES))

    def test_the_add_button_adds_the_typed_game_and_selects_it(self):
        w = self.window
        w.games_whitelist_add_input.setText("My Brand New Game")

        w.games_whitelist_add_btn.click()

        self.assertIn("My Brand New Game", w.games_whitelist_list.selected_keys())
        self.assertEqual(w.games_whitelist_add_input.text(), "")
        self.assertIn(self.t("whitelist_game_added", game="My Brand New Game"), self.log_text())
        self.assertTrue(w._autosave_timer.isActive())

    def test_pressing_enter_in_the_add_box_does_the_same(self):
        w = self.window
        w.games_whitelist_add_input.setText("Another New Game")

        w.games_whitelist_add_input.returnPressed.emit()

        self.assertIn("Another New Game", w.games_whitelist_list.selected_keys())

    def test_the_add_button_with_nothing_typed_says_so_and_changes_nothing(self):
        w = self.window
        w.games_whitelist_add_input.setText("   ")

        w.games_whitelist_add_btn.click()

        self.assertEqual(w.games_whitelist_list.selected_keys(), [])
        self.assertIn(self.t("whitelist_game_add_empty"), self.log_text())

    def test_clicking_a_game_in_a_list_toggles_it(self):
        w = self.window
        lst = w.games_whitelist_list
        item = next(lst.item(i) for i in range(lst.count()) if lst.item(i).data(Qt.ItemDataRole.UserRole) == "Beta Game")

        lst.itemClicked.emit(item)
        self.assertEqual(lst.selected_keys(), ["Beta Game"])
        lst.itemClicked.emit(item)
        self.assertEqual(lst.selected_keys(), [])

    def test_the_refresh_button_forces_a_fresh_campaign_fetch(self):
        w = self.window
        w.refresh_snapshot = MagicMock()

        w.btn_refresh.click()

        w.refresh_snapshot.assert_called_once_with(force=True)


class TestSettingsButtons(_WindowCase):
    def test_save_settings_writes_the_file_and_confirms_with_a_message_that_fades(self):
        w = self.window
        w.refresh_snapshot = MagicMock()
        w.games_whitelist_list.set_entries([ui.FilterEntry(key="Alpha Game", label="Alpha Game")], ["Alpha Game"], "")

        w.btn_save.click()

        self.assertEqual(config_module.load_config().whitelist_games, ["Alpha Game"])
        self.assertIn(self.t("settings_saved"), self.log_text())
        self.assertEqual(w._toast.text(), self.t("toast_saved"))
        self.assertFalse(w._autosave_timer.isActive())

    def test_save_log_writes_a_file_and_copies_its_path(self):
        w = self.window
        w._log("hello from the button audit")

        w.btn_save_log.click()

        files = list((Path(self._tmp.name) / "logs").glob("log-*.txt"))
        self.assertTrue(files)
        self.assertEqual(QApplication.clipboard().text(), str(sorted(files)[-1]))

    def test_the_language_picker_switches_the_whole_ui(self):
        w = self.window
        index = w.language_picker.findData("en")
        w.language_picker.setCurrentIndex(index)
        w.language_picker.activated.emit(index)
        self.assertEqual(w.btn_save.text(), TRANSLATION("en", "save_settings"))
        self.assertTrue(w._autosave_timer.isActive())

        index = w.language_picker.findData("pt_PT")
        w.language_picker.setCurrentIndex(index)
        w.language_picker.activated.emit(index)
        self.assertEqual(w.btn_save.text(), TRANSLATION("pt_PT", "save_settings"))

    def test_a_setting_changed_by_the_user_is_saved_without_pressing_save(self):
        w = self.window
        w.refresh_snapshot = MagicMock()
        before = w.auto_claim_checkbox.isChecked()

        w.auto_claim_checkbox.click()
        self.assertTrue(w._autosave_timer.isActive())
        w._autosave_now()

        self.assertEqual(config_module.load_config().auto_claim_drops, not before)
        w.auto_claim_checkbox.click()  # put it back
        w._autosave_now()


def TRANSLATION(language: str, key: str) -> str:
    return ui.TRANSLATIONS[language][key]


class TestFarmButtons(_WindowCase):
    def setUp(self) -> None:
        super().setUp()
        w = self.window
        w.refresh_snapshot = MagicMock()
        w._streamless_heartbeat_tick = MagicMock()
        w.latest_snapshot = None
        if w.timer.isActive():
            w.handle_stop()

    def test_start_and_stop_switch_the_timers_and_the_buttons_in_both_places(self):
        w = self.window

        w.btn_start.click()
        self.assertTrue(w.timer.isActive() and w.streamless_timer.isActive())
        self.assertFalse(w.btn_start.isEnabled())
        self.assertTrue(w.btn_stop.isEnabled())
        self.assertFalse(w.btn_farming_start.isEnabled())
        self.assertTrue(w.btn_farming_pause.isEnabled())
        self.assertTrue(w.btn_farming_next.isEnabled())
        self.assertIn(self.t("farming_started"), self.log_text())

        w.btn_stop.click()
        self.assertFalse(w.timer.isActive() or w.streamless_timer.isActive())
        self.assertTrue(w.btn_start.isEnabled())
        self.assertFalse(w.btn_stop.isEnabled())
        self.assertTrue(w.btn_farming_start.isEnabled())
        self.assertFalse(w.btn_farming_pause.isEnabled())
        self.assertFalse(w.btn_farming_next.isEnabled())

    def test_the_farming_panel_start_and_pause_buttons_do_the_same(self):
        w = self.window

        w.btn_farming_start.click()
        self.assertTrue(w.timer.isActive())
        w.btn_farming_pause.click()
        self.assertFalse(w.timer.isActive())

    def test_next_game_with_nothing_to_switch_to_says_so(self):
        w = self.window
        w.handle_start()
        w.latest_snapshot = FarmSnapshot(campaigns=[], decisions=[], available_games=[], available_channels=[])

        w.btn_farming_next.click()

        self.assertIn(self.t("farming_next_game_unavailable"), self.log_text())

    def test_next_game_moves_to_the_other_campaign(self):
        w = self.window
        a, b = _campaign("Alpha"), _campaign("Beta")
        w.latest_snapshot = FarmSnapshot(campaigns=[a, b], decisions=[_decision(a), _decision(b)],
                                         available_games=[], available_channels=[])
        w.handle_start()
        w._sticky_campaign_id = a.id

        with patch.object(w, "_verify_decision_stream", lambda decision: True):
            w.btn_farming_next.click()

        self.assertEqual(w._forced_farm_campaign_id, b.id)
        self.assertIn("Beta", self.log_text())

    def test_redeem_with_nothing_ready_says_so(self):
        self.window.btn_redeem_drops.click()

        self.assertIn(self.t("redeem_none"), self.log_text())

    def test_redeem_reports_how_many_buttons_were_clicked_and_refreshes(self):
        w = self.window
        with patch.object(tc.TwitchClient, "claim_available_drops", return_value=2):
            w.btn_redeem_drops.click()

        self.assertIn(self.t("redeem_done", count=2), self.log_text())
        w.refresh_snapshot.assert_called_with(force=True)

    def test_open_drops_page_opens_the_inventory_in_the_browser(self):
        self.window.btn_open_drops_page.click()

        url = self.desktop.openUrl.call_args.args[0]
        self.assertEqual(url.toString(), "https://www.twitch.tv/drops/inventory")

    def test_link_account_opens_the_link_of_the_selected_campaign(self):
        w = self.window
        campaign = _campaign("Linkable", link_url="https://example.com/link")
        campaign.linked = False
        with patch.object(w, "_selected_decision", lambda: _decision(campaign)):
            w._refresh_campaign_details()
            self.assertTrue(w.btn_link_account.isEnabled())

            w.btn_link_account.click()

        self.assertEqual(self.desktop.openUrl.call_args.args[0].toString(), "https://example.com/link")

    def test_link_account_is_disabled_for_a_campaign_that_is_already_linked(self):
        w = self.window
        campaign = _campaign("Linked", link_url="https://example.com/link")  # linked=True by default
        with patch.object(w, "_selected_decision", lambda: _decision(campaign)):
            w._refresh_campaign_details()

        self.assertFalse(w.btn_link_account.isEnabled())

    def test_link_account_with_nothing_selected_is_disabled_so_it_never_clicks_into_nothing(self):
        w = self.window
        w.campaign_list.clear()
        w.decision_by_campaign_id = {}

        w._refresh_campaign_details()

        self.assertFalse(w.btn_link_account.isEnabled())


class TestAlertsAreRaised(_WindowCase):
    """Every alert checkbox must control an alert that can actually happen."""

    def setUp(self) -> None:
        super().setUp()
        self.manager = ui.AlertManager(dedupe_window_sec=0)
        patcher = patch.object(ui, "get_alert_manager", return_value=self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _types(self):
        return [alert.alert_type for alert in self.manager.alerts]

    def test_every_alert_type_that_has_a_checkbox_is_raised_somewhere_in_the_code(self):
        source = "".join(path.read_text(encoding="utf-8") for path in (Path(ui.__file__).parent).glob("*.py")
                         if path.name != "alerts.py")
        never_raised = [alert_type.name for alert_type in self.window.alert_checkboxes
                        if f"AlertType.{alert_type.name}" not in source]

        self.assertEqual(never_raised, [], "alert checkboxes that control nothing")

    def test_a_channel_that_went_offline_is_reported_with_where_the_farm_went(self):
        w = self.window
        with patch.object(w, "engine") as engine:
            engine.is_channel_penalized.return_value = False
            engine.is_channel_live.return_value = False

            w._alert_if_channel_went_offline("c1", "MARVEL SNAP", "oldchan", "newchan")

        self.assertEqual(self._types(), [ui.AlertType.STREAM_OFFLINE])
        message = self.manager.alerts[0].message
        self.assertIn("oldchan", message)
        self.assertIn("newchan", message)

    def test_an_offline_channel_with_no_alternative_says_it_is_waiting(self):
        w = self.window
        with patch.object(w, "engine") as engine:
            engine.is_channel_penalized.return_value = False
            engine.is_channel_live.return_value = False

            w._alert_if_channel_went_offline("c1", "MARVEL SNAP", "oldchan", "")

        self.assertEqual(self._types(), [ui.AlertType.STREAM_OFFLINE])
        self.assertIn(self.t("stream_offline_none", game="MARVEL SNAP", channel="oldchan", new=""), self.manager.alerts[0].message)

    def test_no_alert_when_the_channel_is_still_live_or_was_left_on_purpose(self):
        w = self.window
        with patch.object(w, "engine") as engine:
            engine.is_channel_penalized.return_value = False
            engine.is_channel_live.return_value = True  # still live: moved for another reason
            w._alert_if_channel_went_offline("c1", "G", "chan", "other")

            engine.is_channel_live.return_value = False
            engine.is_channel_penalized.return_value = True  # the stall monitor skipped it
            w._alert_if_channel_went_offline("c1", "G", "chan", "other")

            engine.is_channel_penalized.return_value = False
            w._alert_if_channel_went_offline("c1", "G", "", "other")  # there was no previous channel

        self.assertEqual(self._types(), [])

    def test_the_heartbeat_tick_raises_it_when_the_target_channel_changes_because_it_went_offline(self):
        w = self.window
        campaign = _campaign("Alpha")
        decision = _decision(campaign)
        w.latest_snapshot = FarmSnapshot(campaigns=[campaign], decisions=[decision], available_games=[], available_channels=[])
        w._streamless_channel, w._streamless_campaign_id, w._streamless_game = "oldchan", campaign.id, "Alpha"
        w._snap_future = w._heartbeat_future = None
        w.timer.start(60_000)
        self.addCleanup(w.timer.stop)
        with patch.object(w, "engine") as engine, patch.object(w.executor, "submit"):
            engine.is_channel_penalized.return_value = False
            engine.is_channel_live.return_value = False
            w._sticky_campaign_id = campaign.id

            w._streamless_heartbeat_tick()

        self.assertEqual(self._types(), [ui.AlertType.STREAM_OFFLINE])
        self.assertIn(decision.stream.login, self.manager.alerts[0].message)

    def test_the_heartbeat_tick_raises_it_when_there_is_no_channel_left(self):
        w = self.window
        w.latest_snapshot = FarmSnapshot(campaigns=[], decisions=[], available_games=[], available_channels=[])
        w._streamless_channel, w._streamless_campaign_id, w._streamless_game = "oldchan", "c1", "Alpha"
        w._snap_future = w._heartbeat_future = None
        w.timer.start(60_000)
        self.addCleanup(w.timer.stop)
        with patch.object(w, "engine") as engine:
            engine.is_channel_penalized.return_value = False
            engine.is_channel_live.return_value = False

            w._streamless_heartbeat_tick()

        self.assertEqual(self._types(), [ui.AlertType.STREAM_OFFLINE])
        self.assertEqual(w._streamless_channel, "")

    def test_three_failed_heartbeats_in_a_row_are_reported_once_as_an_api_error(self):
        w = self.window
        w._heartbeat_failures, w._api_error_announced = 0, False

        for _ in range(5):
            w._note_heartbeat_result(False, "chan")

        self.assertEqual(self._types(), [ui.AlertType.API_ERROR])
        self.assertIn("chan", self.manager.alerts[0].message)

    def test_a_good_heartbeat_ends_the_streak_so_a_later_one_is_reported_again(self):
        w = self.window
        w._heartbeat_failures, w._api_error_announced = 0, False
        for _ in range(3):
            w._note_heartbeat_result(False, "chan")
        w._note_heartbeat_result(True, "chan")
        for _ in range(2):
            w._note_heartbeat_result(False, "chan")
        self.assertEqual(len(self.manager.alerts), 1, "two failures after a success are not a streak yet")

        w._note_heartbeat_result(False, "chan")

        self.assertEqual(self._types(), [ui.AlertType.API_ERROR, ui.AlertType.API_ERROR])

    def test_a_heartbeat_that_raises_counts_as_a_failure_too(self):
        w = self.window
        w._heartbeat_failures, w._api_error_announced = 0, False
        for _ in range(3):
            future = MagicMock()
            future.done.return_value = True
            future.result.side_effect = RuntimeError("worker died")
            w._heartbeat_future = future
            w._heartbeat_pending_channel = "chan"

            w._poll_heartbeat_future()

        self.assertEqual(self._types(), [ui.AlertType.API_ERROR])


class TestSettingControls(_WindowCase):
    """Check boxes, radio buttons and pickers: each user click changes the config and is saved."""

    def setUp(self) -> None:
        super().setUp()
        self.window.refresh_snapshot = MagicMock()

    def _click_and_expect_autosave(self, widget) -> None:
        self.window._autosave_timer.stop()
        widget.click()
        self.assertTrue(self.window._autosave_timer.isActive(), "the change is scheduled to be saved")
        self.window._autosave_timer.stop()

    def test_the_watchdog_checkbox_switches_the_stall_monitor(self):
        w = self.window
        before = w.config.watchdog_enabled

        self._click_and_expect_autosave(w.watchdog_checkbox)

        self.assertEqual(w.config.watchdog_enabled, not before)
        self.assertEqual(w._farm_health.enabled, not before)
        self.assertEqual(w.watchdog_timeout_spinbox.isEnabled(), not before)
        w.watchdog_checkbox.click()

    def test_the_stall_timeout_box_reaches_the_monitor(self):
        w = self.window

        w.watchdog_timeout_spinbox.setValue(41)

        self.assertEqual(w.config.watchdog_stall_timeout_min, 41)
        self.assertEqual(w._farm_health.timeout_min, 41)

    def test_the_autoupdate_options_are_disabled_because_nothing_installs_updates_by_itself(self):
        """The auto-update checkbox and its delay box used to look active but controlled nothing:
        UpdateManager is never started. They are off, and their help says it is not implemented."""
        w = self.window

        self.assertFalse(w.autoupdate_checkbox.isEnabled())
        self.assertFalse(w.autoupdate_checkbox.isChecked())
        self.assertFalse(w.autoupdate_delay_spinbox.isEnabled())
        self.assertFalse(w.config.auto_update_enabled)
        self.assertIn("implementado", w.autoupdate_help_icon.toolTip().casefold())

    def test_every_alert_checkbox_switches_its_alert(self):
        w = self.window
        self.assertTrue(w.alert_checkboxes)
        for alert_type, checkbox in w.alert_checkboxes.items():
            with self.subTest(alert_type.value):
                before = getattr(w.config, f"alert_{alert_type.value}")

                self._click_and_expect_autosave(checkbox)

                self.assertEqual(getattr(w.config, f"alert_{alert_type.value}"), not before)
                self.assertEqual(ui.get_alert_manager().is_alert_enabled(alert_type), not before)
                checkbox.click()

    def test_every_energy_profile_radio_selects_its_profile(self):
        w = self.window
        for name, button in w.energy_profile_buttons:
            with self.subTest(name):
                w._autosave_timer.stop()
                button.click()
                self.assertEqual(w.config.energy_profile, name)
                self.assertTrue(w._autosave_timer.isActive())

    def test_a_profile_changes_the_engine_the_stall_timeout_and_says_so_in_the_log(self):
        w = self.window
        for profile in ui.AVAILABLE_PROFILES:
            with self.subTest(profile.name):
                w.log_output.clear()
                for name, button in w.energy_profile_buttons:
                    if name == profile.name:
                        button.click()

                self.assertEqual(w.engine.campaign_refresh_sec, profile.campaign_refresh_sec)
                self.assertEqual(w.engine.front_ttl_sec, profile.front_ttl_sec)
                self.assertEqual(w.config.watchdog_stall_timeout_min, profile.watchdog_stall_timeout_min)
                self.assertEqual(w._farm_health.timeout_min, profile.watchdog_stall_timeout_min)
                self.assertIn(profile.name, self.log_text())
                self.assertIn(str(profile.watchdog_stall_timeout_min), self.log_text())

    def test_a_running_farm_follows_the_new_profile_at_once_and_a_started_one_uses_it(self):
        w = self.window
        w._streamless_heartbeat_tick = MagicMock()
        w.latest_snapshot = None
        w.handle_start()
        self.addCleanup(w.handle_stop)
        for profile in ui.AVAILABLE_PROFILES:
            for name, button in w.energy_profile_buttons:
                if name == profile.name:
                    button.click()
            self.assertEqual(w.timer.interval(), profile.poll_interval_sec * 1000, profile.name)

        w.handle_stop()
        w.handle_start()  # a fresh start uses the profile that is selected now
        self.assertEqual(w.timer.interval(), ui.AVAILABLE_PROFILES[-1].poll_interval_sec * 1000)

    def test_showing_the_saved_profile_at_start_up_keeps_the_saved_stall_timeout(self):
        w = self.window
        w.config.watchdog_stall_timeout_min = 33
        w._ui_ready = False
        try:
            w.handle_energy_profile_change("Económico")  # what the radio button does while the window is built
        finally:
            w._ui_ready = True

        self.assertEqual(w.config.watchdog_stall_timeout_min, 33)

    def test_the_tooltip_describes_every_profile_with_its_real_numbers(self):
        w = self.window
        w.language_picker.setCurrentIndex(w.language_picker.findData("pt_PT"))
        w._retranslate_ui()

        tip = w.energy_profile_help_icon.toolTip()

        for profile in ui.AVAILABLE_PROFILES:
            self.assertIn(profile.name, tip)
            self.assertIn(f"{ui._minutes_text(profile.poll_interval_sec)} em {ui._minutes_text(profile.poll_interval_sec)} min", tip)
            self.assertIn(f"{ui._minutes_text(profile.campaign_refresh_sec)} em {ui._minutes_text(profile.campaign_refresh_sec)} min", tip)
            self.assertIn(f"{profile.watchdog_stall_timeout_min} min", tip)

    def test_minutes_text(self):
        self.assertEqual((ui._minutes_text(60), ui._minutes_text(300), ui._minutes_text(90)), ("1", "5", "1.5"))

    def test_the_sort_and_theme_pickers_change_the_config(self):
        w = self.window
        for picker, attr, handler in ((w.sort_picker, "sort_mode", w._current_sort_mode),
                                      (w.theme_picker, "theme", w._current_theme)):
            for index in range(picker.count()):
                with self.subTest(f"{attr} #{index}"):
                    w._autosave_timer.stop()
                    picker.setCurrentIndex(index)
                    picker.activated.emit(index)
                    self.assertEqual(getattr(w.config, attr), picker.itemData(index))
                    self.assertTrue(w._autosave_timer.isActive())

    def test_hide_subscription_games_checkbox_updates_the_config_and_the_dashboard(self):
        w = self.window
        before = w.config.dashboard_hide_subscription_required

        self._click_and_expect_autosave(w.dashboard_hide_sub_only_checkbox)

        self.assertEqual(w.config.dashboard_hide_subscription_required, not before)
        w.dashboard_hide_sub_only_checkbox.click()


class TestDashboardButtons(_WindowCase):
    def setUp(self) -> None:
        super().setUp()
        w = self.window
        a = _campaign("Alpha")
        self.snapshot = FarmSnapshot(campaigns=[a], decisions=[_decision(a)], available_games=["Alpha"], available_channels=[])
        w.engine = MagicMock()
        w.engine.poll.return_value = self.snapshot
        w.engine.client = MagicMock()
        w.client = MagicMock()
        w.client.consume_diagnostics.return_value = []
        w.games_whitelist_list.set_entries([ui.FilterEntry(key="Alpha", label="Alpha")], ["Alpha"], "")
        w.config.whitelist_games = ["Alpha"]
        w._apply_snapshot = MagicMock()

    def test_update_dashboard_runs_one_full_scan_and_re_enables_itself(self):
        w = self.window

        w.btn_dashboard_refresh.click()

        w.engine.poll.assert_called_once_with(allow_browser_fallback=True, full_scan=True)
        self.assertTrue(w.btn_dashboard_refresh.isEnabled())
        w._apply_snapshot.assert_called_once()
        self.assertIn(self.t("dashboard_full_scan_done"), self.log_text())

    def test_update_drops_runs_one_full_scan_poll_and_re_enables_itself(self):
        w = self.window

        w.btn_dashboard_refresh_drops.click()

        w.engine.poll.assert_called_once_with(allow_browser_fallback=True, full_scan=True)
        self.assertTrue(w.btn_dashboard_refresh_drops.isEnabled())
        self.assertIn(self.t("dashboard_drop_refresh_done", count=1), self.log_text())

    def test_clicking_a_game_card_makes_it_the_manual_target(self):
        w = self.window
        w.refresh_snapshot = MagicMock()
        w._streamless_heartbeat_tick = MagicMock()
        w.latest_snapshot = self.snapshot
        w.available_game_entries = [ui.FilterEntry(key="Alpha", label="Alpha")]
        w._refresh_dashboard_games()
        cards = [w.dashboard_games_grid.itemAt(i).widget() for i in range(w.dashboard_games_grid.count())]
        card = next(c for c in cards if getattr(c, "game_label", "") == "Alpha")

        with patch.object(w, "_verify_decision_stream", lambda decision: True):
            QTest.mouseClick(card, Qt.MouseButton.LeftButton)  # a real press on the card

        self.assertEqual(w._forced_farm_game, "Alpha")
        self.assertIn(self.t("dashboard_selected", game="Alpha"), self.log_text())

    def test_the_buttons_come_back_even_when_the_scan_fails(self):
        w = self.window
        w.engine.poll.side_effect = RuntimeError("boom")

        w.btn_dashboard_refresh.click()
        w.btn_dashboard_refresh_drops.click()

        self.assertTrue(w.btn_dashboard_refresh.isEnabled())
        self.assertTrue(w.btn_dashboard_refresh_drops.isEnabled())
        self.assertEqual(self.msgbox.critical.call_count, 2)


class TestLoginButton(_WindowCase):
    """The "Log in" button in the corner of the right tabs and the window it opens."""

    TOKEN = "k" * 30

    def setUp(self) -> None:
        super().setUp()
        w = self.window
        w.client.login_state = tc.LoginState()
        w.config.remember_session = False
        w.client.forget_session_copy()
        w.language_picker.setCurrentIndex(w.language_picker.findData("pt_PT"))
        w._retranslate_ui()
        self._refresh = patch.object(w, "refresh_snapshot")
        self.refresh = self._refresh.start()
        self.addCleanup(self._refresh.stop)
        self.addCleanup(self.close_dialog)

    def close_dialog(self) -> None:
        dialog = self.window._login_dialog
        if dialog is not None:
            dialog.close()
        self.window._login_dialog = None

    def dialog(self):
        dialog = self.window._login_dialog
        self.assertIsNotNone(dialog, "the login window did not open")
        self.assertTrue(dialog.isVisible())
        return dialog

    def twitch_confirms(self, login: str = "someone") -> None:
        def validate():
            state = self.window.client.login_state
            state.token_valid = True
            state.login_name = login
            state.user_id = "42"
            return state

        patcher = patch.object(self.window.client, "validate_oauth_token", side_effect=validate)
        patcher.start()
        self.addCleanup(patcher.stop)

    def twitch_rejects(self) -> None:
        patcher = patch.object(self.window.client, "validate_oauth_token",
                               side_effect=ValueError("The provided auth-token is invalid or expired."))
        patcher.start()
        self.addCleanup(patcher.stop)

    def keep_a_session(self) -> None:
        self.window.client.import_session_json(json.dumps([{"name": "auth-token", "value": self.TOKEN, "domain": ".twitch.tv"}]))
        self.window.client.save_session_copy()
        self.window.client.login_state = tc.LoginState()
        self.window.client.session.cookies.clear()
        self.window.config.remember_session = True

    # ---------------------------------------------------------------- the button itself
    def test_the_button_sits_in_the_free_corner_next_to_the_right_tabs(self):
        self.assertIs(self.window.tabs_right.cornerWidget(Qt.Corner.TopRightCorner), self.window.btn_smart_login)

    def test_the_button_says_log_in_and_then_who_is_signed_in(self):
        w = self.window
        self.assertEqual(w.btn_smart_login.text(), "Iniciar sessão")

        w.client.login_state = tc.LoginState(oauth_token=self.TOKEN, login_name="example_user", token_valid=True)
        w._update_auth_status()
        self.assertEqual(w.btn_smart_login.text(), "Sessão: example_user")
        self.assertIn("example_user", w.btn_smart_login.toolTip())

        w.language_picker.setCurrentIndex(w.language_picker.findData("en"))
        w._retranslate_ui()
        self.assertEqual(w.btn_smart_login.text(), "Signed in: example_user")

    def test_someone_already_signed_in_can_still_open_the_window_from_the_account_tab(self):
        """Without this button the window (and "remember the session") was unreachable once signed in."""
        w = self.window
        w.client.login_state = tc.LoginState(oauth_token=self.TOKEN, login_name="someone", token_valid=True)
        w._update_auth_status()
        w.btn_smart_login.click()  # signed in: this only confirms, it does not open anything
        self.assertIsNone(w._login_dialog)

        w.btn_open_login_window.click()

        dialog = self.dialog()
        self.assertIn("someone", dialog.status_label.text())
        self.assertTrue(dialog.remember_checkbox.isEnabled())

    def test_the_account_tab_button_is_translated(self):
        w = self.window
        self.assertEqual(w.btn_open_login_window.text(), "Abrir janela de sessão")
        w.language_picker.setCurrentIndex(w.language_picker.findData("en"))
        w._retranslate_ui()
        self.assertEqual(w.btn_open_login_window.text(), "Open sign-in window")

    def test_the_language_picker_spells_portugues_with_its_accent(self):
        labels = [self.window.language_picker.itemText(i) for i in range(self.window.language_picker.count())]

        self.assertIn("Português (Portugal)", labels)
        self.assertNotIn("Portugues (Portugal)", labels)

    def test_with_nothing_saved_the_button_opens_the_window_and_asks_nothing_of_twitch(self):
        with patch.object(self.window.client, "validate_oauth_token") as validate:
            self.window.btn_smart_login.click()

        self.dialog()
        validate.assert_not_called()
        self.refresh.assert_not_called()

    def test_with_a_token_the_app_already_has_it_just_validates_it_and_refreshes(self):
        w = self.window
        w.client.login_state.oauth_token = self.TOKEN
        self.twitch_confirms("someone")

        w.btn_smart_login.click()

        self.assertIsNone(w._login_dialog)
        self.assertTrue(w.client.login_state.logged_in)
        self.assertEqual(w.btn_smart_login.text(), "Sessão: someone")
        self.assertIn("someone", w._toast.text())
        self.refresh.assert_called_once_with(force=True)

    def test_when_already_signed_in_it_only_confirms_and_does_not_refresh_again(self):
        w = self.window
        w.client.login_state = tc.LoginState(oauth_token=self.TOKEN, login_name="someone", token_valid=True)
        self.twitch_confirms("someone")

        w.btn_smart_login.click()

        self.assertIsNone(w._login_dialog)
        self.assertIn(self.t("login_confirmed", login="someone"), self.log_text())
        self.refresh.assert_not_called()

    def test_a_token_twitch_rejects_opens_the_window_with_the_reason(self):
        self.window.client.login_state.oauth_token = self.TOKEN
        self.twitch_rejects()

        self.window.btn_smart_login.click()

        self.assertIn("invalid or expired", self.dialog().message_label.text())
        self.refresh.assert_not_called()

    def test_with_no_connection_it_says_so_and_does_not_throw_the_data_away(self):
        w = self.window
        w.client.login_state.oauth_token = self.TOKEN
        with patch.object(w.client, "validate_oauth_token", side_effect=requests.ConnectionError("offline")):
            w.btn_smart_login.click()

        self.assertIsNone(w._login_dialog)
        self.assertIn(self.t("login_network_error"), self.log_text())
        self.assertEqual(w.client.login_state.oauth_token, self.TOKEN)

    def test_a_kept_session_is_restored_in_three_steps_without_opening_anything(self):
        w = self.window
        self.keep_a_session()
        self.twitch_confirms("someone")

        w.btn_smart_login.click()

        self.assertIsNone(w._login_dialog)
        self.assertTrue(w.client.login_state.logged_in)
        log = self.log_text()
        positions = [log.index(self.t("login_progress", n=n, total=3, what=self.t(f"login_progress_{n}"))) for n in (1, 2, 3)]
        self.assertEqual(positions, sorted(positions))
        self.refresh.assert_called_once_with(force=True)

    def test_a_stale_token_falls_back_to_the_kept_session_before_giving_up(self):
        w = self.window
        self.keep_a_session()
        w.client.login_state.oauth_token = "x" * 30  # what the app still had: no longer accepted
        calls: list[str] = []

        def validate():
            calls.append(w.client.login_state.oauth_token)
            if w.client.login_state.oauth_token != self.TOKEN:
                raise ValueError("The provided auth-token is invalid or expired.")
            w.client.login_state.token_valid = True
            w.client.login_state.login_name = "someone"
            return w.client.login_state

        with patch.object(w.client, "validate_oauth_token", side_effect=validate):
            w.btn_smart_login.click()

        self.assertEqual(calls, ["x" * 30, self.TOKEN])
        self.assertIsNone(w._login_dialog)
        self.assertTrue(w.client.login_state.logged_in)

    def test_a_kept_session_that_no_longer_works_opens_the_window_with_the_reason(self):
        self.keep_a_session()
        self.twitch_rejects()

        self.window.btn_smart_login.click()

        self.assertIn("invalid or expired", self.dialog().message_label.text())

    def test_the_kept_session_is_ignored_when_the_user_did_not_agree_to_keep_it(self):
        self.keep_a_session()
        self.window.config.remember_session = False

        self.window.btn_smart_login.click()

        self.dialog()  # nothing usable: it asks

    # ---------------------------------------------------------------- the window: instructions
    def test_the_window_explains_the_steps_in_order_and_where_to_find_the_token(self):
        self.window.btn_smart_login.click()
        dialog = self.dialog()

        session = " ".join(label.text() for label in (dialog.step1_label, dialog.step2_label, dialog.step3_label))
        self.assertLess(session.index("Passo 1"), session.index("Passo 2"))
        self.assertLess(session.index("Passo 2"), session.index("Passo 3"))
        self.assertIn("Importar", dialog.step1_label.text())
        self.assertIn("Validar", dialog.step2_label.text())
        self.assertIn("Exportar", dialog.step3_label.text())
        token_help = dialog.token_intro.text()
        for needle in ("F12", "auth-token", "Cookies", "twitch.tv", "Value"):
            self.assertIn(needle, token_help)
        self.assertEqual(dialog.tabs.tabText(0), self.t("auth_session_export"))
        self.assertEqual(dialog.tabs.tabText(1), self.t("auth_quick_token"))

    def test_the_window_is_in_english_when_the_app_is(self):
        self.window.language_picker.setCurrentIndex(self.window.language_picker.findData("en"))
        self.window._retranslate_ui()

        self.window.btn_smart_login.click()
        dialog = self.dialog()

        self.assertEqual(dialog.windowTitle(), "Log in to Twitch")
        self.assertIn("Step 1", dialog.step1_label.text())
        self.assertIn("Application", dialog.token_intro.text())

    def test_the_open_twitch_button_opens_the_site(self):
        self.window.btn_smart_login.click()

        self.dialog().btn_open_twitch.click()

        self.desktop.openUrl.assert_called_once()
        self.assertIn("twitch.tv", self.desktop.openUrl.call_args.args[0].toString())

    # ---------------------------------------------------------------- the window: session JSON tab
    def test_import_with_nothing_pasted_asks_for_the_json_inside_the_window(self):
        self.window.btn_smart_login.click()
        dialog = self.dialog()

        dialog.btn_import.click()

        self.assertIn(self.t("login_paste_first"), dialog.message_label.text())
        self.msgbox.critical.assert_not_called()

    def test_importing_garbage_shows_the_reason_and_keeps_the_window_open(self):
        self.window.btn_smart_login.click()
        dialog = self.dialog()
        dialog.session_input.setPlainText("this is not json")

        dialog.btn_import.click()

        self.assertIn("Invalid session JSON", dialog.message_label.text())
        self.assertTrue(dialog.isVisible())

    def test_import_then_validate_signs_in_and_closes_the_window(self):
        w = self.window
        w.btn_smart_login.click()
        dialog = self.dialog()
        dialog.session_input.setPlainText(json.dumps([{"name": "auth-token", "value": self.TOKEN, "domain": ".twitch.tv"}]))
        self.twitch_confirms("someone")

        dialog.btn_import.click()
        self.assertIn(self.t("login_import_ok"), dialog.message_label.text())
        self.assertFalse(w.client.login_state.logged_in)  # importing alone does not sign in
        self.assertTrue(dialog.isVisible())
        dialog.btn_validate.click()

        self.assertFalse(dialog.isVisible())
        self.assertTrue(w.client.login_state.logged_in)
        self.refresh.assert_called_once_with(force=True)

    def test_validate_before_importing_says_what_to_do_first(self):
        self.window.btn_smart_login.click()
        dialog = self.dialog()

        dialog.btn_validate.click()

        self.assertIn(self.t("login_nothing_to_validate"), dialog.message_label.text())

    def test_export_puts_the_json_in_the_box_and_on_the_clipboard(self):
        w = self.window
        w.client.login_state = tc.LoginState(oauth_token=self.TOKEN, login_name="someone", token_valid=True)
        w.client._apply_oauth_token(self.TOKEN)
        w.btn_smart_login.click()  # signed in: confirms instead of opening
        self.twitch_confirms()
        dialog = w.open_login_dialog()

        dialog.btn_export.click()

        exported = json.loads(dialog.session_input.toPlainText())
        self.assertIn("auth-token", [cookie["name"] for cookie in exported["cookies"]])
        self.assertEqual(QApplication.clipboard().text(), dialog.session_input.toPlainText())

    def test_export_without_a_session_says_there_is_nothing_to_export(self):
        self.window.btn_smart_login.click()
        dialog = self.dialog()

        dialog.btn_export.click()

        self.assertIn(self.t("login_export_needs_session"), dialog.message_label.text())

    # ---------------------------------------------------------------- the window: quick token tab
    def test_a_good_token_signs_in_and_closes_the_window(self):
        w = self.window
        w.btn_smart_login.click()
        dialog = self.dialog()
        dialog.tabs.setCurrentIndex(1)
        dialog.token_input.setText(self.TOKEN)
        self.twitch_confirms("someone")

        dialog.btn_token.click()  # the real set_oauth_token runs; only Twitch's answer is simulated

        self.assertFalse(dialog.isVisible())
        self.assertEqual(w.client.login_state.oauth_token, self.TOKEN)
        self.assertTrue(w.client.login_state.logged_in)
        self.assertEqual(dialog.token_input.text(), "")  # the token is not left lying in the window

    def test_a_rejected_token_stays_in_the_window_with_the_reason(self):
        w = self.window
        w.btn_smart_login.click()
        dialog = self.dialog()
        dialog.token_input.setText("nope")

        with patch.object(w.client, "set_oauth_token", side_effect=ValueError("The provided auth-token is invalid or expired.")):
            dialog.btn_token.click()

        self.assertTrue(dialog.isVisible())
        self.assertIn("invalid or expired", dialog.message_label.text())

    def test_an_empty_token_asks_for_it(self):
        self.window.btn_smart_login.click()
        dialog = self.dialog()

        dialog.btn_token.click()

        self.assertIn(self.t("token_required"), dialog.message_label.text())

    def test_the_token_is_hidden_until_the_user_asks_to_see_it(self):
        self.window.btn_smart_login.click()
        dialog = self.dialog()
        self.assertEqual(dialog.token_input.echoMode(), QLineEdit.EchoMode.Password)

        dialog.token_show.setChecked(True)

        self.assertEqual(dialog.token_input.echoMode(), QLineEdit.EchoMode.Normal)

    # ---------------------------------------------------------------- keeping the session (needs a yes)
    def test_keeping_the_session_asks_first_and_a_no_keeps_nothing(self):
        w = self.window
        w.client.login_state = tc.LoginState(oauth_token=self.TOKEN, login_name="someone", token_valid=True)
        w.btn_smart_login.click()
        self.twitch_confirms()
        dialog = w.open_login_dialog()
        self.msgbox.question.return_value = self.msgbox.StandardButton.No

        dialog.remember_checkbox.setChecked(True)

        self.msgbox.question.assert_called_once()
        self.assertIn(str(w.client.session_copy_path()), self.msgbox.question.call_args.args[2])
        self.assertFalse(dialog.remember_checkbox.isChecked())
        self.assertFalse(w.config.remember_session)
        self.assertFalse(w.client.has_session_copy())

    def test_a_yes_keeps_the_session_now_and_remembers_the_choice(self):
        w = self.window
        w.client.login_state = tc.LoginState(oauth_token=self.TOKEN, login_name="someone", token_valid=True)
        w.client._apply_oauth_token(self.TOKEN)
        dialog = w.open_login_dialog()
        self.msgbox.question.return_value = self.msgbox.StandardButton.Yes

        dialog.remember_checkbox.setChecked(True)

        self.assertTrue(dialog.remember_checkbox.isChecked())
        self.assertTrue(w.config.remember_session)
        self.assertTrue(w.client.has_session_copy())
        self.assertTrue(json.loads(config_module.CONFIG_FILE.read_text(encoding="utf-8"))["remember_session"])

    def test_turning_it_off_deletes_the_kept_session(self):
        w = self.window
        self.keep_a_session()
        dialog = w.open_login_dialog()
        self.assertTrue(dialog.remember_checkbox.isChecked())

        dialog.remember_checkbox.setChecked(False)

        self.assertFalse(w.config.remember_session)
        self.assertFalse(w.client.has_session_copy())
        self.msgbox.question.assert_not_called()  # taking it back needs no confirmation

    def test_a_successful_login_refreshes_the_kept_copy_only_if_the_user_agreed(self):
        w = self.window
        w.client.login_state.oauth_token = self.TOKEN
        self.twitch_confirms()

        w.btn_smart_login.click()
        self.assertFalse(w.client.has_session_copy())

        w.config.remember_session = True
        w.client.login_state.token_valid = False
        w.btn_smart_login.click()
        self.assertTrue(w.client.has_session_copy())

    def test_the_token_never_reaches_the_log_during_any_of_this(self):
        w = self.window
        self.keep_a_session()
        self.twitch_confirms()
        w.btn_smart_login.click()
        w.client.login_state.token_valid = False
        w.btn_smart_login.click()

        self.assertNotIn(self.TOKEN, self.log_text())
        self.assertNotIn(self.TOKEN, w.btn_smart_login.text() + w.btn_smart_login.toolTip())


class TestResumeLastGame(_WindowCase):
    """Continue with the game the farm was last on, not with the one the sort order puts first (The Quinfall)."""

    def setUp(self) -> None:
        super().setUp()
        w = self.window
        w.timer.stop()
        w.config.last_farm_game = ""
        w.config.farming_when_closed = False
        w.config.resume_farming_on_start = True
        w.engine.set_preferred_game("")
        for name in ("_sticky_campaign_id", "_forced_farm_game", "_forced_farm_campaign_id", "_forced_farm_channel",
                     "_streamless_campaign_id", "_streamless_game"):
            setattr(w, name, "")
        self.quinfall, self.elden = _campaign("The Quinfall"), _campaign("ELDEN RING")
        self.decisions = [_decision(self.quinfall), _decision(self.elden)]  # the sort order puts The Quinfall first
        w.latest_snapshot = FarmSnapshot(campaigns=[self.quinfall, self.elden], decisions=self.decisions,
                                         available_games=[], available_channels=[])
        self.addCleanup(self.remove_files)

    def remove_files(self) -> None:
        for path in (config_module.CONFIG_FILE, tc.COOKIE_FILE):
            Path(path).unlink(missing_ok=True)

    def saved_config(self) -> dict:
        return json.loads(Path(config_module.CONFIG_FILE).read_text(encoding="utf-8"))

    def picked(self) -> str:
        return self.window._pick_farm_decision().campaign.game_name

    # ---------------------------------------------------------------- which game is chosen
    def test_with_nothing_remembered_the_first_in_the_sort_order_is_chosen(self):
        self.assertEqual(self.picked(), "The Quinfall")

    def test_the_remembered_game_is_chosen_instead(self):
        self.window.config.last_farm_game = "ELDEN RING"

        self.assertEqual(self.picked(), "ELDEN RING")

    def test_the_match_ignores_case_accents_and_punctuation(self):
        self.window.config.last_farm_game = "elden-ring"

        self.assertEqual(self.picked(), "ELDEN RING")

    def test_a_remembered_game_with_nothing_farmable_falls_back_to_the_normal_choice(self):
        self.window.config.last_farm_game = "A Game That Ended"

        self.assertEqual(self.picked(), "The Quinfall")

    def test_a_remembered_game_that_is_not_farmable_now_is_skipped(self):
        self.window.config.last_farm_game = "ELDEN RING"
        self.decisions[1].stream = None  # no live channel for it right now

        self.assertEqual(self.picked(), "The Quinfall")

    def test_a_game_that_is_already_being_farmed_is_not_swapped_for_the_remembered_one(self):
        self.window.config.last_farm_game = "ELDEN RING"
        self.window._sticky_campaign_id = self.quinfall.id

        self.assertEqual(self.picked(), "The Quinfall")

    def test_a_manual_pick_still_wins_over_the_remembered_game(self):
        self.window.config.last_farm_game = "ELDEN RING"
        self.window._forced_farm_game = "The Quinfall"

        self.assertEqual(self.picked(), "The Quinfall")

    # ---------------------------------------------------------------- what gets remembered
    def test_picking_a_game_remembers_it_tells_the_engine_and_writes_the_config(self):
        w = self.window

        w._select_dashboard_game("Albion Online")

        self.assertEqual(w.config.last_farm_game, "Albion Online")
        self.assertEqual(w.engine.preferred_game, "Albion Online")
        self.assertEqual(self.saved_config()["last_farm_game"], "Albion Online")

    def test_when_the_farm_moves_on_what_is_remembered_is_where_it_really_is(self):
        """Picked Sea of Thieves, it finished, the farm went to Albion Online: remember Albion Online."""
        w = self.window
        sea, albion = _campaign("Sea of Thieves"), _campaign("Albion Online")
        w._select_dashboard_game("Sea of Thieves")
        w._note_target_switch(_decision(sea))
        self.assertEqual(w.config.last_farm_game, "Sea of Thieves")

        w._note_target_switch(_decision(albion))  # the running farm picked another campaign by itself

        self.assertEqual(w.config.last_farm_game, "Albion Online")
        self.assertEqual(self.saved_config()["last_farm_game"], "Albion Online")

    def test_just_displaying_the_default_does_not_overwrite_what_is_remembered(self):
        """At start-up the window shows the default pick before any farming: that must not be remembered."""
        w = self.window
        w.config.last_farm_game = "A Game That Ended"

        shown = w._current_farm_decision()

        self.assertEqual(shown.campaign.game_name, "The Quinfall")
        self.assertEqual(w.config.last_farm_game, "A Game That Ended")

    def test_nothing_is_written_when_the_game_did_not_change(self):
        w = self.window
        w._remember_farm_game("ELDEN RING")
        Path(config_module.CONFIG_FILE).unlink()

        w._remember_farm_game("ELDEN RING")

        self.assertFalse(Path(config_module.CONFIG_FILE).exists())

    def test_a_failure_to_save_does_not_crash_the_farm(self):
        with patch.object(ui, "save_config", side_effect=OSError("disk full")):
            self.window._remember_farm_game("ELDEN RING")

        self.assertEqual(self.window.config.last_farm_game, "ELDEN RING")  # still kept for this session

    # ---------------------------------------------------------------- "it was farming when I closed it"
    def test_starting_the_farm_notes_it_and_stopping_it_clears_it(self):
        w = self.window
        w._streamless_heartbeat_tick = MagicMock()
        self.addCleanup(w.handle_stop)

        w.handle_start()
        self.assertTrue(w.config.farming_when_closed)
        self.assertTrue(self.saved_config()["farming_when_closed"])

        w.handle_stop()
        self.assertFalse(w.config.farming_when_closed)
        self.assertFalse(self.saved_config()["farming_when_closed"])

    def test_closing_the_window_does_not_count_as_stopping_the_farm(self):
        """If it did, the app would never remember that it was farming when it was closed."""
        import inspect

        self.assertNotIn("handle_stop", inspect.getsource(ui.MainWindow.closeEvent))

    # ---------------------------------------------------------------- resuming at launch
    def resume(self, *, token: str = "k" * 30, running: bool = False, **config) -> MagicMock:
        w = self.window
        defaults = dict(resume_farming_on_start=True, farming_when_closed=True, last_farm_game="ELDEN RING")
        for key, value in {**defaults, **config}.items():
            setattr(w.config, key, value)
        w.client.login_state = tc.LoginState(oauth_token=token)
        with patch.object(w.timer, "isActive", return_value=running), patch.object(w, "handle_start") as start:
            w._maybe_resume_farming()
        return start

    def test_it_resumes_when_it_was_farming_when_closed(self):
        start = self.resume()

        start.assert_called_once()
        self.assertIn("ELDEN RING", self.log_text())

    def test_it_does_not_resume_when_the_option_is_off(self):
        self.resume(resume_farming_on_start=False).assert_not_called()

    def test_it_does_not_resume_when_the_farm_was_stopped_before_closing(self):
        self.resume(farming_when_closed=False).assert_not_called()

    def test_it_does_not_resume_without_a_remembered_game(self):
        self.resume(last_farm_game="").assert_not_called()

    def test_it_does_not_resume_without_a_session_to_farm_with(self):
        self.resume(token="").assert_not_called()

    def test_it_does_not_start_a_farm_that_is_already_running(self):
        self.resume(running=True).assert_not_called()

    def test_the_option_is_a_checkbox_that_is_saved(self):
        w = self.window
        before = w.config.resume_farming_on_start
        w._autosave_timer.stop()

        w.resume_checkbox.click()
        self.assertTrue(w._autosave_timer.isActive())
        w._autosave_timer.stop()
        w._apply_widgets_to_config()

        self.assertEqual(w.config.resume_farming_on_start, not before)
        w.resume_checkbox.click()  # put it back

    def test_the_option_is_translated(self):
        w = self.window
        self.assertEqual(w.resume_checkbox.text(), "Retomar a farm ao abrir a app")
        w.language_picker.setCurrentIndex(w.language_picker.findData("en"))
        w._retranslate_ui()
        self.assertEqual(w.resume_checkbox.text(), "Resume farming when the app opens")
        w.language_picker.setCurrentIndex(w.language_picker.findData("pt_PT"))
        w._retranslate_ui()

    # ---------------------------------------------------------------- a real start-up
    def new_window(self, *, token: str) -> tuple["ui.MainWindow", MagicMock]:
        Path(config_module.CONFIG_FILE).parent.mkdir(parents=True, exist_ok=True)
        config_module.save_config(config_module.AppConfig(last_farm_game="ELDEN RING", farming_when_closed=True))
        if token:
            Path(tc.COOKIE_FILE).write_text(json.dumps({"cookies": [], "oauth_token": token, "session_id": "s"}), encoding="utf-8")
        with patch.object(ui.MainWindow, "handle_start") as start:
            window = ui.MainWindow()
            for _ in range(3):
                self.app.processEvents()

        def close() -> None:
            window.client.segment_watcher.stop()
            for timer in (window.timer, window.streamless_timer, window._autosave_timer):
                timer.stop()
            window.executor.shutdown(wait=False)

        self.addCleanup(close)
        return window, start

    def test_a_new_start_up_tells_the_engine_and_resumes_the_farm(self):
        window, start = self.new_window(token="k" * 30)

        self.assertEqual(window.engine.preferred_game, "ELDEN RING")
        self.assertEqual(window.client._priority_game_name, "elden ring")
        start.assert_called_once()

    def test_a_new_start_up_without_a_session_does_not_start_the_farm(self):
        window, start = self.new_window(token="")

        self.assertEqual(window.engine.preferred_game, "ELDEN RING")
        start.assert_not_called()


class TestSubscriptionOnlyGames(_WindowCase):
    """What the dashboard shows once the registry has said which games need a subscription."""

    def registry_campaign(self, name: str, slug: str) -> DropCampaign:
        campaign = _campaign(name)
        campaign.source = "external_registry"
        campaign.link_url = f"https://twitchdrops.app/game/{slug}"
        campaign.required_minutes = 0
        campaign.progress_minutes = 0
        campaign.drops = []
        campaign.has_watchable_drops = False
        return campaign

    def show(self, campaigns: list[DropCampaign]) -> None:
        from twitch_drop_farmer.registry_rewards import RewardSummary

        w = self.window
        w.client._registry_rewards.store("elden-ring", "s", RewardSummary(subscription=1))
        w.client._registry_rewards.store("cyberpunk-2077", "s", RewardSummary(watchable=1, subscription=1))
        w.client.apply_registry_rewards(campaigns)
        names = [campaign.game_name for campaign in campaigns]
        w.config.whitelist_games = list(names)
        w.available_game_entries = w._compose_game_entries(names)
        w.latest_snapshot = FarmSnapshot(campaigns=campaigns, decisions=[], available_games=names, available_channels=[])
        w._refresh_filter_lists()
        w._refresh_dashboard_hide_sub_only_label()

    def test_the_counter_counts_the_subscription_only_games_and_not_the_mixed_ones(self):
        elden = self.registry_campaign("ELDEN RING", "elden-ring")
        cyberpunk = self.registry_campaign("Cyberpunk 2077", "cyberpunk-2077")

        self.show([elden, cyberpunk])

        self.assertTrue(elden.requires_subscription)
        self.assertFalse(cyberpunk.requires_subscription)
        self.assertTrue(self.window.dashboard_hide_sub_only_checkbox.text().endswith("(1)"),
                        self.window.dashboard_hide_sub_only_checkbox.text())

    def test_a_game_the_registry_has_not_been_read_for_is_not_counted(self):
        unknown = self.registry_campaign("Mystery Game", "mystery-game")

        self.show([unknown])

        self.assertTrue(self.window.dashboard_hide_sub_only_checkbox.text().endswith("(0)"))


class TestButtonsAreNotClipped(_WindowCase):
    """The bottom of letters such as "g" was cut off on "Save log" and on the "Signed in" button."""

    def setUp(self) -> None:
        super().setUp()
        w = self.window
        w.client.login_state = tc.LoginState(oauth_token="k" * 30, login_name="example_user", token_valid=True)
        w._update_auth_status()
        w.resize(1500, 800)
        w.show()
        self.app.processEvents()

    def clipped_buttons(self) -> list[str]:
        """Every button that is on screen in any tab and is shorter than its text needs."""
        w = self.window
        clipped: list[str] = []
        for left in range(w.tabs_left.count()):
            for right in range(w.tabs_right.count()):
                w.tabs_left.setCurrentIndex(left)
                w.tabs_right.setCurrentIndex(right)
                self.app.processEvents()
                for button in w.findChildren(QPushButton):
                    if button.isVisible() and button.height() < button.sizeHint().height():
                        clipped.append(f"{button.text()!r}: {button.height()}px < {button.sizeHint().height()}px")
        return sorted(set(clipped))

    def test_no_visible_button_is_shorter_than_its_text_needs(self):
        self.assertEqual(self.clipped_buttons(), [])

    def test_the_save_log_button_has_no_height_limit(self):
        self.assertGreaterEqual(self.window.btn_save_log.maximumHeight(), self.window.btn_save_log.sizeHint().height())

    def test_the_signed_in_button_gets_the_height_it_needs_not_the_tab_bars(self):
        w = self.window

        self.assertGreaterEqual(w.btn_smart_login.height(), w.btn_smart_login.sizeHint().height())

    def test_it_still_holds_with_a_bigger_font_as_on_another_machine(self):
        """The height a button needs depends on the font of the machine; a fixed number would clip it there.

        (Changing the application font does nothing to these buttons, so the font is set on the widgets.)
        """
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QWidget

        w = self.window
        widgets = [w] + w.findChildren(QWidget)
        originals = {widget: widget.font() for widget in widgets}

        def restore() -> None:
            for widget, font in originals.items():
                widget.setFont(font)
            w._update_auth_status()
            self.app.processEvents()

        self.addCleanup(restore)
        needed_before = w.btn_smart_login.sizeHint().height()
        for widget in widgets:
            font = QFont(widget.font())
            font.setPointSize(font.pointSize() + 4)
            widget.setFont(font)
        self.app.processEvents()
        self.assertGreater(w.btn_smart_login.sizeHint().height(), needed_before, "the simulated font changed nothing")
        w._update_auth_status()  # the app does this on every refresh
        self.app.processEvents()

        self.assertEqual(self.clipped_buttons(), [])

    def test_it_holds_in_english_and_in_every_theme(self):
        w = self.window
        for language in ("en", "pt_PT"):
            w.language_picker.setCurrentIndex(w.language_picker.findData(language))
            w._retranslate_ui()
            for theme in ui.THEMES:
                with self.subTest(language=language, theme=theme):
                    w._apply_theme(theme)
                    self.app.processEvents()
                    self.assertEqual(self.clipped_buttons(), [])
        w._apply_theme(w.config.theme)


class TestNoButtonIsLeftOut(_WindowCase):
    def test_every_button_has_something_connected_to_it(self):
        dead = []
        for button in self.window.findChildren(QPushButton):
            if button.receivers("2clicked()") + button.receivers("2clicked(bool)") == 0:
                dead.append(button.text() or button.objectName() or repr(button))

        self.assertEqual(dead, [], "buttons that do nothing when clicked")

    def test_every_button_is_exercised_by_this_file(self):
        """A new button must get a test here: list the ones the tests above do not mention."""
        source = Path(__file__).read_text(encoding="utf-8")
        names = {
            attr for attr, value in vars(self.window).items()
            if isinstance(value, QPushButton) and (attr.startswith("btn_") or attr.endswith("_btn"))
        }

        missing = sorted(name for name in names if name not in source)

        self.assertEqual(missing, [], "buttons without a test in test_buttons.py")


if __name__ == "__main__":
    unittest.main()
