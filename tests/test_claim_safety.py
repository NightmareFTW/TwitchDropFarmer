"""The auto-claim must not flood Twitch with failing claim requests."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twitch_drop_farmer.models import DropCampaign  # noqa: E402
from twitch_drop_farmer.twitch_client import _CLAIM_BUTTONS_JS, TwitchClient  # noqa: E402
from twitch_drop_farmer.ui import (  # noqa: E402
    AUTO_CLAIM_MAX_ATTEMPTS,
    AUTO_CLAIM_RETRY_SEC,
    TRANSLATIONS,
    MainWindow,
)

UTC = timezone.utc

# A fake page: Twitch re-creates a button whose claim failed (new element, same label),
# and a button whose claim succeeded disappears. Run with Node so the real script executes.
_NODE_HARNESS = r"""
const vm = require("vm");
const scenario = JSON.parse(process.argv[1]);
const script = process.argv[2];
let nextId = 1;
const clicked = [];
function makeButton(text, extra) {
  const id = nextId++;
  return Object.assign({id, innerText: text, disabled: false,
    getAttribute: (name) => (name === "aria-disabled" && extra && extra.ariaDisabled ? "true" : null),
    click() { clicked.push(id); this.onClick && this.onClick(this); }}, extra && extra.props || {});
}
// page state: a list of button specs; "fail" buttons are re-created on click, "ok" ones disappear
let page = scenario.buttons.map((b) => Object.assign({}, b));
function render() {
  return page.map((spec) => {
    const button = makeButton(spec.text, {ariaDisabled: spec.ariaDisabled, props: {disabled: !!spec.disabled}});
    button.onClick = () => {
      if (spec.result === "ok") page = page.filter((s) => s !== spec);
      // "fail": the page keeps the same spec, so the next render gives a brand-new element
    };
    return button;
  });
}
const windowObject = {};
let totalClicks = 0;
for (let scan = 0; scan < scenario.scans; scan++) {
  if (scenario.appearAt && scenario.appearAt.scan === scan) page.push(Object.assign({}, scenario.appearAt.button));
  const elements = render();
  const document = {querySelectorAll: () => elements};
  const out = JSON.parse(vm.runInNewContext(script, {document, window: windowObject}));
  totalClicks += out.clicked;
}
process.stdout.write(JSON.stringify({totalClicks, clickedElements: clicked.length}));
"""


def _run(scenario: dict, script: str = _CLAIM_BUTTONS_JS) -> int:
    result = subprocess.run(
        ["node", "-e", _NODE_HARNESS, json.dumps(scenario), script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)["totalClicks"]


def _btn(text="Claim Now", result="fail", **extra) -> dict:
    return {"text": text, "result": result, **extra}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the claim script")
class TestClaimScript(unittest.TestCase):
    def test_a_button_that_keeps_failing_is_clicked_once_not_on_every_scan(self):
        """Regression: Twitch re-creates the button after a failed claim, so the per-element
        flag never held: 255 claim requests in 3 hours, 13-33 per attempt."""
        clicks = _run({"buttons": [_btn()], "scans": 25})

        self.assertEqual(clicks, 1)

    def test_every_ready_drop_is_clicked_once(self):
        clicks = _run({"buttons": [_btn(), _btn("Claim Now"), _btn("Reivindicar")], "scans": 25})

        self.assertEqual(clicks, 3)

    def test_a_button_that_succeeds_disappears_and_nothing_more_is_clicked(self):
        clicks = _run({"buttons": [_btn(result="ok"), _btn(result="ok")], "scans": 25})

        self.assertEqual(clicks, 2)

    def test_a_button_that_appears_later_is_still_clicked(self):
        scenario = {"buttons": [_btn(result="ok")], "scans": 25, "appearAt": {"scan": 6, "button": _btn(result="fail")}}

        self.assertEqual(_run(scenario), 2)

    def test_there_is_a_hard_cap_per_page_load(self):
        clicks = _run({"buttons": [_btn() for _ in range(12)], "scans": 25})

        self.assertEqual(clicks, 5)

    def test_other_buttons_are_never_clicked(self):
        buttons = [_btn("Claimed"), _btn("Redeem"), _btn("Collect"), _btn("Claim Now", disabled=True),
                   _btn("Claim Now", ariaDisabled=True), _btn("Connect")]

        self.assertEqual(_run({"buttons": buttons, "scans": 10}), 0)

    def test_the_old_script_did_flood_which_is_what_this_harness_reproduces(self):
        old = """(() => {
            const claimVerb = /^(claim|reivindicar|resgatar)\\b/;
            const labels = [];
            for (const button of Array.from(document.querySelectorAll("button"))) {
                if (!button || button.disabled || button.getAttribute("aria-disabled") === "true") continue;
                if (button.dataset && button.dataset.tdfClicked === "1") continue;
                const text = (button.innerText || button.textContent || "").trim().toLowerCase().replace(/\\s+/g, " ");
                if (!text || !claimVerb.test(text)) continue;
                if (button.dataset) button.dataset.tdfClicked = "1";
                button.click();
                labels.push(text.slice(0, 40));
            }
            return JSON.stringify({clicked: labels.length, labels: labels});
        })();"""

        self.assertEqual(_run({"buttons": [_btn()], "scans": 25}, old), 25)


def _campaign(*drops: dict) -> DropCampaign:
    return DropCampaign(
        id="cid", game_name="MARVEL SNAP", title="Knights of Avalon Drops!",
        starts_at=datetime.now(UTC) - timedelta(days=1), ends_at=datetime.now(UTC) + timedelta(days=2),
        status="ACTIVE", drops=list(drops),
    )


def _drop(name: str, current: int, required: int, claimed: bool = False) -> dict:
    return {"id": name.lower(), "name": name, "required_minutes": required,
            "current_minutes": current, "claimed": claimed}


def _window(*campaigns: DropCampaign) -> MagicMock:
    fake = MagicMock()
    fake.config.auto_claim_drops = True
    fake.latest_snapshot = MagicMock(campaigns=list(campaigns))
    fake._auto_claim_tried = {}
    fake._auto_claim_gave_up = set()
    fake._do_redeem_drops.return_value = 1
    fake._t = lambda key, **kw: TRANSLATIONS["pt_PT"][key].format(**kw)
    return fake


class TestAutoClaimBackoff(unittest.TestCase):
    def test_the_retries_back_off_and_then_stop(self):
        fake = _window(_campaign(_drop("Premium Mystery Border", 240, 240)))
        t0 = datetime(2026, 11, 10, 19, 40, 0)
        # attempt 1 at t0, 2 after 15 min, 3 after a further hour; then no more.
        waits = [0, AUTO_CLAIM_RETRY_SEC, AUTO_CLAIM_RETRY_SEC * 4]
        now = t0
        for wait in waits:
            now += timedelta(seconds=wait)
            MainWindow._maybe_auto_claim(fake, now)
        self.assertEqual(fake._do_redeem_drops.call_count, 3)

        for extra in (AUTO_CLAIM_RETRY_SEC * 16, 10 * 24 * 3600):
            MainWindow._maybe_auto_claim(fake, now + timedelta(seconds=extra))

        self.assertEqual(fake._do_redeem_drops.call_count, AUTO_CLAIM_MAX_ATTEMPTS)

    def test_a_retry_before_the_backed_off_wait_is_not_made(self):
        fake = _window(_campaign(_drop("Reward", 60, 60)))
        t0 = datetime(2026, 11, 10, 19, 40, 0)
        MainWindow._maybe_auto_claim(fake, t0)
        MainWindow._maybe_auto_claim(fake, t0 + timedelta(seconds=AUTO_CLAIM_RETRY_SEC))  # 2nd attempt

        MainWindow._maybe_auto_claim(fake, t0 + timedelta(seconds=AUTO_CLAIM_RETRY_SEC + 3599))  # needs 3600

        self.assertEqual(fake._do_redeem_drops.call_count, 2)

    def test_giving_up_is_announced_once_with_the_drop_and_how_to_claim_it(self):
        fake = _window(_campaign(_drop("Premium Mystery Border", 240, 240)))
        now = datetime(2026, 11, 10, 19, 40, 0)
        for _ in range(3):
            MainWindow._maybe_auto_claim(fake, now)
            now += timedelta(days=1)

        for _ in range(4):
            MainWindow._maybe_auto_claim(fake, now)
            now += timedelta(days=1)

        messages = [call.args[0] for call in fake._log.call_args_list]
        self.assertEqual(len(messages), 1)
        self.assertIn("Premium Mystery Border", messages[0])
        self.assertIn("twitch.tv/drops/inventory", messages[0])

    def test_a_claimed_drop_is_forgotten_and_a_new_one_starts_fresh(self):
        fake = _window(_campaign(_drop("Reward", 60, 60)))
        now = datetime(2026, 11, 10, 19, 40, 0)
        for _ in range(3):
            MainWindow._maybe_auto_claim(fake, now)
            now += timedelta(days=1)
        fake.latest_snapshot = MagicMock(campaigns=[_campaign(_drop("Reward", 60, 60, claimed=True))])
        MainWindow._maybe_auto_claim(fake, now)
        self.assertEqual((fake._auto_claim_tried, fake._auto_claim_gave_up), ({}, set()))

        fake.latest_snapshot = MagicMock(campaigns=[_campaign(_drop("Other", 90, 90))])
        MainWindow._maybe_auto_claim(fake, now)

        self.assertEqual(fake._do_redeem_drops.call_count, 4)

    def test_the_setting_explains_the_risk_in_both_languages(self):
        for language in ("pt_PT", "en"):
            for key in ("auto_claim_tooltip", "auto_claim_gave_up"):
                self.assertIn(key, TRANSLATIONS[language])


class TestDropsPageFallback(unittest.TestCase):
    def test_it_is_not_asked_when_the_dashboard_is_integrity_blocked(self):
        """Regression: it cost a 20 s wait (a reset connection) on 12 of 25 refreshes and its
        IDs were never used, because the detail queries are skipped in that case."""
        client = TwitchClient()
        inventory = {"data": {"currentUser": {"inventory": {"dropCampaignsInProgress": []}}}}
        dashboard = {"errors": [{"message": "failed integrity check"}], "data": {"currentUser": {"dropCampaigns": []}}}
        client.login_state.oauth_token = "token"
        with patch.object(client, "validate_oauth_token", return_value=None), \
                patch.object(client, "_post_gql", side_effect=[inventory, dashboard]), \
                patch.object(client, "_campaigns_from_drops_page", return_value={}) as drops_page, \
                patch.object(client, "_campaigns_from_browser_page", return_value=[]), \
                patch.object(client, "_campaigns_from_external_registry", return_value=[]):
            client.fetch_campaigns(allow_browser_fallback=False)

        drops_page.assert_not_called()

    def test_when_it_is_asked_it_gives_up_quickly(self):
        client = TwitchClient()
        client.session.get = MagicMock(side_effect=requests.ConnectionError("reset"))

        self.assertEqual(client._campaigns_from_drops_page(), {})

        self.assertEqual(client.session.get.call_args.kwargs["timeout"], (5, 10))


if __name__ == "__main__":
    unittest.main()
