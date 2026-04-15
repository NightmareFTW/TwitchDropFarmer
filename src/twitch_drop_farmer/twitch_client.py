from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
from typing import Any

try:
    import requests
except ModuleNotFoundError as exc:
    if exc.name == "requests":
        raise SystemExit(
            "Falta a dependência 'requests'. "
            "Instala tudo com `python -m pip install -r requirements.txt` "
            "e arranca a app com `$env:PYTHONPATH='src'; python -m twitch_drop_farmer` "
            "na raiz do repositório."
        ) from exc
    raise

if __package__ in {None, ""}:
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from twitch_drop_farmer.config import COOKIE_FILE, CONFIG_DIR
    from twitch_drop_farmer.models import DropCampaign, StreamCandidate
else:
    from .config import COOKIE_FILE, CONFIG_DIR
    from .models import DropCampaign, StreamCandidate


GQL_URL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
ANDROID_APP_CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"
ANDROID_APP_USER_AGENT = (
    "Dalvik/2.1.0 (Linux; U; Android 16; SM-S911B Build/TP1A.220624.014) "
    "tv.twitch.android.app/25.3.0/2503006"
)
TWITCH_URL = "https://www.twitch.tv"

INVENTORY_QUERY = {
    "operationName": "Inventory",
    "variables": {"fetchRewardCampaigns": False},
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "d86775d0ef16a63a33ad52e80eaff963b2d5b72fada7c991504a57496e1d8e4b",
        }
    },
}
CAMPAIGNS_QUERY = {
    "operationName": "ViewerDropsDashboard",
    "variables": {"fetchRewardCampaigns": False},
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "5a4da2ab3d5b47c9f9ce864e727b2cb346af1e3ea8b897fe8f704a97ff017619",
        }
    },
}
CAMPAIGN_DETAILS_QUERY = {
    "operationName": "DropCampaignDetails",
    "variables": {"channelLogin": "", "dropID": ""},
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "039277bf98f3130929262cc7c6efd9c141ca3749cb6dca442fc8ead9a53f77c1",
        }
    },
}
GAME_REDIRECT_QUERY = {
    "operationName": "DirectoryGameRedirect",
    "variables": {"name": ""},
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "1f0300090caceec51f33c5e20647aceff9017f740f223c3c532ba6fa59f6b6cc",
        }
    },
}
GAME_DIRECTORY_QUERY = {
    "operationName": "DirectoryPage_Game",
    "variables": {
        "limit": 30,
        "slug": "",
        "imageWidth": 50,
        "includeCostreaming": False,
        "options": {
            "broadcasterLanguages": [],
            "freeformTags": None,
            "includeRestricted": ["SUB_ONLY_LIVE"],
            "recommendationsContext": {"platform": "web"},
            "sort": "RELEVANCE",
            "systemFilters": ["DROPS_ENABLED"],
            "tags": [],
            "requestID": "JIRA-VXP-2397",
        },
        "sortTypeIsRecency": False,
    },
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "76cb069d835b8a02914c08dc42c421d0dafda8af5b113a3f19141824b901402f",
        }
    },
}


@dataclass(slots=True)
class LoginState:
    oauth_token: str = ""
    user_id: str = ""
    login_name: str = ""
    token_valid: bool = False

    @property
    def logged_in(self) -> bool:
        return bool(self.oauth_token and self.token_valid)


class TwitchClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Client-Id": WEB_CLIENT_ID,
                "User-Agent": WEB_USER_AGENT,
                "Origin": TWITCH_URL,
                "Referer": f"{TWITCH_URL}/",
            }
        )
        self.login_state = LoginState()
        self._diagnostics: list[str] = []
        self._slug_cache: dict[str, str] = {}
        self.device_id = ""
        self.session_id = secrets.token_hex(16)
        self._load_cookies()

    def _note(self, message: str) -> None:
        self._diagnostics.append(message)

    def _clone_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(payload))

    def consume_diagnostics(self) -> list[str]:
        messages = self._diagnostics[:]
        self._diagnostics.clear()
        return messages

    def _load_cookies(self) -> None:
        if not COOKIE_FILE.exists():
            return
        payload = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        for cookie in payload.get("cookies", []):
            self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))
        self.login_state.oauth_token = payload.get("oauth_token", "")
        self.login_state.user_id = payload.get("user_id", "")
        self.login_state.login_name = payload.get("login_name", "")
        self.device_id = payload.get("device_id", "")
        self.session_id = payload.get("session_id", self.session_id)
        if self.login_state.oauth_token:
            self._apply_oauth_token(self.login_state.oauth_token)

    def save_cookies(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        serialized = [
            {"name": cookie.name, "value": cookie.value, "domain": cookie.domain}
            for cookie in self.session.cookies
        ]
        COOKIE_FILE.write_text(
            json.dumps(
                {
                    "cookies": serialized,
                    "oauth_token": self.login_state.oauth_token,
                    "user_id": self.login_state.user_id,
                    "login_name": self.login_state.login_name,
                    "device_id": self.device_id,
                    "session_id": self.session_id,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _apply_oauth_token(self, token: str) -> None:
        self.session.headers["Authorization"] = f"OAuth {token}"
        self.session.cookies.set("auth-token", token, domain="www.twitch.tv")
        self.session.cookies.set("auth-token", token, domain=".twitch.tv")

    def _ensure_device_id(self) -> str:
        if self.device_id:
            return self.device_id
        cookie_value = self.session.cookies.get("unique_id", domain=".twitch.tv") or self.session.cookies.get(
            "unique_id",
            domain="www.twitch.tv",
        )
        if cookie_value:
            self.device_id = cookie_value
            return self.device_id

        try:
            response = self.session.get(
                TWITCH_URL,
                headers={"User-Agent": WEB_USER_AGENT},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException:
            self.device_id = secrets.token_hex(16)
            self._note("Falling back to a generated X-Device-Id for Twitch GraphQL.")
            return self.device_id

        cookie_value = self.session.cookies.get("unique_id", domain=".twitch.tv") or self.session.cookies.get(
            "unique_id",
            domain="www.twitch.tv",
        )
        self.device_id = cookie_value or secrets.token_hex(16)
        return self.device_id

    def _gql_headers(self, client_profile: str) -> dict[str, str]:
        device_id = self._ensure_device_id()
        if client_profile == "android":
            client_id = ANDROID_APP_CLIENT_ID
            user_agent = ANDROID_APP_USER_AGENT
        else:
            client_id = WEB_CLIENT_ID
            user_agent = WEB_USER_AGENT

        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
            "Cache-Control": "no-cache",
            "Client-Id": client_id,
            "Client-Session-Id": self.session_id,
            "Origin": TWITCH_URL,
            "Pragma": "no-cache",
            "Referer": f"{TWITCH_URL}/",
            "User-Agent": user_agent,
            "X-Device-Id": device_id,
        }
        if self.login_state.oauth_token:
            headers["Authorization"] = f"OAuth {self.login_state.oauth_token}"
        return headers

    def set_oauth_token(self, token: str) -> None:
        token = token.replace("OAuth ", "").strip()
        self.login_state.oauth_token = token
        self.login_state.token_valid = False
        self._apply_oauth_token(token)
        self.validate_oauth_token()
        self.save_cookies()

    def validate_oauth_token(self) -> LoginState:
        if not self.login_state.oauth_token:
            self.login_state.token_valid = False
            self.login_state.user_id = ""
            self.login_state.login_name = ""
            raise ValueError("No OAuth token was provided.")

        response = self.session.get(
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {self.login_state.oauth_token}"},
            timeout=20,
        )
        if response.status_code != 200:
            self.login_state.token_valid = False
            self.login_state.user_id = ""
            self.login_state.login_name = ""
            raise ValueError("The provided auth-token is invalid or expired.")

        payload = response.json()
        self.login_state.user_id = str(payload.get("user_id", ""))
        self.login_state.login_name = payload.get("login", "")
        self.login_state.token_valid = True
        self._note(
            f"Authenticated as {self.login_state.login_name or 'unknown'} "
            f"(user {self.login_state.user_id or '?'})"
        )
        return self.login_state

    def _post_gql(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        client_profile: str = "web",
    ) -> dict[str, Any] | list[dict[str, Any]]:
        retryable_errors = {
            "service error",
            "service timeout",
            "service unavailable",
            "context deadline exceeded",
            "PersistedQueryNotFound",
            "failed integrity check",
        }
        profiles_to_try = [client_profile]
        if client_profile == "web":
            profiles_to_try.append("android")
        else:
            profiles_to_try.append("web")

        last_data: dict[str, Any] | list[dict[str, Any]] = {}
        for profile in profiles_to_try:
            response = self.session.post(
                GQL_URL,
                json=payload,
                headers=self._gql_headers(profile),
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            last_data = data
            self._note_graphql_errors(payload, data)

            messages = self._graphql_error_messages(data)
            if not messages:
                return data
            if any(any(marker in message for marker in retryable_errors) for message in messages):
                self._note(f"Retrying GraphQL request using {profile} headers after error: {messages[0]}")
                continue
            return data
        return last_data

    def _graphql_error_messages(
        self,
        response_data: dict[str, Any] | list[dict[str, Any]],
    ) -> list[str]:
        output: list[str] = []
        responses = response_data if isinstance(response_data, list) else [response_data]
        for item in responses:
            if not isinstance(item, dict):
                continue
            for error in item.get("errors", []) or []:
                message = str(error.get("message", "")).strip()
                if message:
                    output.append(message)
        return output

    def _note_graphql_errors(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        response_data: dict[str, Any] | list[dict[str, Any]],
    ) -> None:
        payloads = payload if isinstance(payload, list) else [payload]
        responses = response_data if isinstance(response_data, list) else [response_data]
        for index, item in enumerate(responses):
            if not isinstance(item, dict):
                continue
            errors = item.get("errors", []) or []
            if not errors:
                continue
            request_item = payloads[min(index, len(payloads) - 1)] if payloads else {}
            operation = request_item.get("operationName", "UnknownOperation")
            drop_id = request_item.get("variables", {}).get("dropID", "")
            suffix = f" ({drop_id})" if drop_id else ""
            for error in errors:
                message = error.get("message", "Unknown GraphQL error")
                self._note(f"{operation}{suffix}: {message}")

    def _is_empty_value(self, value: Any) -> bool:
        if value is None:
            return True
        if value == "":
            return True
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) == 0
        return False

    def _merge_data(self, primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key in set(primary) | set(secondary):
            if key in primary and key in secondary:
                first = primary[key]
                second = secondary[key]
                if isinstance(first, dict) and isinstance(second, dict):
                    merged[key] = self._merge_data(first, second)
                else:
                    merged[key] = first if self._is_empty_value(second) else second
            elif key in primary:
                merged[key] = primary[key]
            else:
                merged[key] = secondary[key]
        return merged

    def _parse_timestamp(self, raw: str | None) -> datetime:
        if not raw:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    def _drop_totals(self, drops: list[dict[str, Any]]) -> tuple[int, int]:
        by_id = {
            drop.get("id", ""): drop
            for drop in drops
            if drop.get("id")
        }

        def totals(drop_id: str) -> tuple[int, int]:
            drop = by_id.get(drop_id, {})
            required = int(drop.get("requiredMinutesWatched", 0) or 0)
            current = int(drop.get("self", {}).get("currentMinutesWatched", 0) or 0)
            remaining = max(0, required - current)
            pre_ids = [
                item.get("id", "")
                for item in drop.get("preconditionDrops", []) or []
                if item.get("id")
            ]
            pre_required = 0
            pre_remaining = 0
            for pre_id in pre_ids:
                req, rem = totals(pre_id)
                pre_required = max(pre_required, req)
                pre_remaining = max(pre_remaining, rem)
            return required + pre_required, remaining + pre_remaining

        total_required = 0
        total_remaining = 0
        for drop_id in by_id:
            req, rem = totals(drop_id)
            total_required = max(total_required, req)
            total_remaining = max(total_remaining, rem)
        return total_required, total_remaining

    def _campaign_has_badge_or_emote(self, drops: list[dict[str, Any]]) -> bool:
        for drop in drops:
            for edge in drop.get("benefitEdges", []) or []:
                kind = edge.get("benefit", {}).get("distributionType", "")
                if kind in {"BADGE", "EMOTE"}:
                    return True
        return False

    def _game_box_art_url(self, game: dict[str, Any]) -> str:
        raw = (game.get("boxArtURL") or game.get("boxArtUrl") or "").strip()
        if not raw:
            return ""
        return raw.replace("{width}", "144").replace("{height}", "192")

    def _next_drop_info(self, drops: list[dict[str, Any]]) -> tuple[str, int, int]:
        by_id = {drop.get("id", ""): drop for drop in drops if drop.get("id")}
        memo: dict[str, int] = {}

        def remaining_with_preconditions(drop_id: str) -> int:
            if drop_id in memo:
                return memo[drop_id]
            drop = by_id.get(drop_id, {})
            required = int(drop.get("requiredMinutesWatched", 0) or 0)
            current = int(drop.get("self", {}).get("currentMinutesWatched", 0) or 0)
            own_remaining = max(0, required - current)
            chained_remaining = 0
            for item in drop.get("preconditionDrops", []) or []:
                pre_id = item.get("id", "")
                if not pre_id:
                    continue
                chained_remaining = max(chained_remaining, remaining_with_preconditions(pre_id))
            memo[drop_id] = own_remaining + chained_remaining
            return memo[drop_id]

        candidates: list[tuple[int, int, str]] = []
        for drop in drops:
            drop_id = drop.get("id", "")
            if not drop_id:
                continue
            if bool(drop.get("self", {}).get("isClaimed", False)):
                continue
            remaining = remaining_with_preconditions(drop_id)
            required = int(drop.get("requiredMinutesWatched", 0) or 0)
            if remaining <= 0 and required <= 0:
                continue
            name = str(drop.get("name", "")).strip() or "Drop"
            candidates.append((remaining, required, name))

        if not candidates:
            return "", 0, 0
        candidates.sort(key=lambda item: (item[0], item[1], item[2].casefold()))
        remaining, required, name = candidates[0]
        return name, remaining, required

    def _channel_login_from_acl(self, channel: dict[str, Any]) -> str:
        return (
            channel.get("login")
            or channel.get("name")
            or channel.get("slug")
            or channel.get("channelLogin")
            or ""
        )

    def _campaigns_from_drops_page(self) -> dict[str, dict[str, Any]]:
        try:
            response = self.session.get(
                f"{TWITCH_URL}/drops/campaigns",
                headers={"User-Agent": WEB_USER_AGENT},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            self._note(f"Drops page fallback failed: {exc}")
            return {}

        html = response.text
        patterns = (
            r'"id":"([0-9a-fA-F-]{36})".{0,600}?"status":"(ACTIVE|UPCOMING)"',
            r'\\"id\\":\\"([0-9a-fA-F-]{36})\\".{0,600}?\\"status\\":\\"(ACTIVE|UPCOMING)\\"',
        )
        found: dict[str, dict[str, Any]] = {}
        for pattern in patterns:
            for match in re.finditer(pattern, html, flags=re.DOTALL):
                campaign_id, status = match.groups()
                found[campaign_id] = {"id": campaign_id, "status": status}

        if found:
            self._note(f"Drops page fallback discovered {len(found)} active/upcoming campaign(s).")
        else:
            self._note("Drops page fallback could not discover campaigns in the HTML payload.")
        return found

    def _browser_campaign_id(self, title: str, starts_at: datetime, ends_at: datetime) -> str:
        digest = hashlib.sha1(
            f"{title}|{starts_at.isoformat()}|{ends_at.isoformat()}".encode("utf-8")
        ).hexdigest()
        return f"browser-{digest[:16]}"

    def _parse_browser_campaign_datetime(self, raw: str, utc_offset_hours: int) -> datetime | None:
        text = re.sub(r"\s+", " ", raw).strip()
        try:
            naive = datetime.strptime(text, "%a, %b %d, %I:%M %p")
        except ValueError:
            return None
        now = datetime.now()
        local_tz = timezone(timedelta(hours=utc_offset_hours))
        candidate = naive.replace(year=now.year, tzinfo=local_tz)
        if candidate < now.astimezone(local_tz) - timedelta(days=370):
            candidate = candidate.replace(year=candidate.year + 1)
        elif candidate > now.astimezone(local_tz) + timedelta(days=370):
            candidate = candidate.replace(year=candidate.year - 1)
        return candidate.astimezone(timezone.utc)

    def _campaign_from_browser_text(self, text: str) -> DropCampaign | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 3:
            return None
        schedule = lines[-1]
        match = re.search(r"(.+?)\s+-\s+(.+?)\s+GMT([+-]\d+)", schedule)
        if match is None:
            return None
        start_raw, end_raw, offset_raw = match.groups()
        try:
            utc_offset_hours = int(offset_raw)
        except ValueError:
            return None
        starts_at = self._parse_browser_campaign_datetime(start_raw, utc_offset_hours)
        ends_at = self._parse_browser_campaign_datetime(end_raw, utc_offset_hours)
        if starts_at is None or ends_at is None:
            return None
        title = lines[0]
        if not title:
            return None
        if ends_at <= starts_at:
            return None
        now = datetime.now(timezone.utc)
        if now >= ends_at:
            status = "EXPIRED"
        elif now < starts_at:
            status = "UPCOMING"
        else:
            status = "ACTIVE"
        return DropCampaign(
            id=self._browser_campaign_id(title, starts_at, ends_at),
            game_name=title,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            linked=True,
            link_url=f"{TWITCH_URL}/drops/campaigns",
            status=status,
        )

    def _campaigns_from_browser_page(self) -> list[DropCampaign]:
        try:
            from PySide6.QtCore import QEventLoop, QTimer, QUrl
            from PySide6.QtNetwork import QNetworkCookie
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        except Exception as exc:
            self._note(f"Browser fallback unavailable: {exc}")
            return []

        app = QApplication.instance()
        owned_app = False
        if app is None:
            app = QApplication([])
            owned_app = True

        class SilentWebEnginePage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level: Any, message: str, line_number: int, source_id: str) -> None:
                return

        profile = QWebEngineProfile(app)
        page = SilentWebEnginePage(profile, app)
        cookie_store = profile.cookieStore()

        def push_cookie(name: str, value: str, *, domain: str = ".twitch.tv") -> None:
            if not value:
                return
            cookie = QNetworkCookie()
            cookie.setName(name.encode("utf-8"))
            cookie.setValue(value.encode("utf-8"))
            cookie.setDomain(domain)
            cookie.setPath("/")
            cookie.setSecure(True)
            cookie_store.setCookie(cookie, QUrl(f"{TWITCH_URL}/"))

        auth_token = self.login_state.oauth_token
        persistent_id = self.login_state.user_id
        unique_id = (
            self.device_id
            or self.session.cookies.get("unique_id", domain=".twitch.tv")
            or self.session.cookies.get("unique_id", domain="www.twitch.tv")
            or ""
        )
        push_cookie("auth-token", auth_token)
        push_cookie("auth-token", auth_token, domain="www.twitch.tv")
        push_cookie("persistent", persistent_id)
        push_cookie("unique_id", unique_id)

        loop = QEventLoop()
        payload: dict[str, Any] = {"raw": ""}
        timed_out = {"value": False}
        poll_timer = QTimer()
        poll_timer.setInterval(2_000)
        poll_timer.setSingleShot(False)

        def finish() -> None:
            if loop.isRunning():
                loop.quit()

        def collect_cards() -> None:
            script = """
                JSON.stringify(
                    Array.from(document.querySelectorAll("button"))
                        .map((button) => (button.innerText || "").trim())
                        .filter(
                            (text) =>
                                /GMT[+-]\\d+/.test(text) &&
                                text.split(/\\n+/).filter(Boolean).length >= 3
                        )
                        .slice(0, 250)
                );
            """

            def on_result(raw: Any) -> None:
                text = raw if isinstance(raw, str) else ""
                if text and text != "[]":
                    payload["raw"] = text
                    finish()

            page.runJavaScript(script, on_result)

        def on_loaded(ok: bool) -> None:
            if not ok:
                self._note("Browser fallback failed to load the rendered Drops page.")
                finish()
                return
            collect_cards()
            poll_timer.start()

        timeout = QTimer()
        timeout.setSingleShot(True)

        def on_timeout() -> None:
            timed_out["value"] = True
            finish()

        timeout.timeout.connect(on_timeout)
        poll_timer.timeout.connect(collect_cards)
        page.loadFinished.connect(on_loaded)
        timeout.start(60_000)
        page.load(QUrl(f"{TWITCH_URL}/drops/campaigns"))
        loop.exec()

        poll_timer.stop()
        timeout.stop()
        page.deleteLater()
        profile.deleteLater()
        if owned_app:
            app.quit()

        if timed_out["value"]:
            self._note("Browser fallback timed out while loading the rendered Drops page.")
            return []

        raw_cards = payload["raw"]
        if not raw_cards:
            self._note("Browser fallback did not capture any rendered campaign cards.")
            return []

        try:
            card_texts = json.loads(raw_cards)
        except json.JSONDecodeError:
            self._note("Browser fallback returned an unreadable payload.")
            return []

        campaigns: list[DropCampaign] = []
        seen: set[str] = set()
        for card_text in card_texts:
            if not isinstance(card_text, str):
                continue
            campaign = self._campaign_from_browser_text(card_text)
            if campaign is None or campaign.status == "EXPIRED":
                continue
            fingerprint = f"{campaign.game_name}|{campaign.starts_at.isoformat()}|{campaign.ends_at.isoformat()}"
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            campaigns.append(campaign)

        if campaigns:
            self._note(
                f"Browser fallback discovered {len(campaigns)} visible active/upcoming campaign(s)."
            )
        else:
            self._note("Browser fallback found the Drops page, but no usable campaign cards were parsed.")
        return campaigns

    def _parse_campaign(self, data: dict[str, Any]) -> DropCampaign | None:
        game = data.get("game") or {}
        if not game:
            return None

        drops = data.get("timeBasedDrops", []) or []
        total_required, total_remaining = self._drop_totals(drops)
        next_drop_name, next_drop_remaining, next_drop_required = self._next_drop_info(drops)
        allowed = data.get("allow") or {}
        allowed_channels = []
        if allowed.get("isEnabled", True):
            allowed_channels = [
                login
                for login in (self._channel_login_from_acl(item) for item in allowed.get("channels", []) or [])
                if login
            ]

        campaign = DropCampaign(
            id=data.get("id", ""),
            game_name=game.get("displayName", "Unknown"),
            game_slug=game.get("slug", ""),
            game_box_art_url=self._game_box_art_url(game),
            title=data.get("name", "Campaign"),
            starts_at=self._parse_timestamp(data.get("startAt")),
            ends_at=self._parse_timestamp(data.get("endAt")),
            progress_minutes=max(0, total_required - total_remaining),
            required_minutes=total_required,
            linked=bool(data.get("self", {}).get("isAccountConnected", False)),
            link_url=data.get("accountLinkURL", "") or "",
            status=data.get("status", "") or "",
            allowed_channels=allowed_channels,
            has_badge_or_emote=self._campaign_has_badge_or_emote(drops),
            next_drop_name=next_drop_name,
            next_drop_remaining_minutes=next_drop_remaining,
            next_drop_required_minutes=next_drop_required,
        )
        return campaign

    def fetch_campaigns(self) -> list[DropCampaign]:
        self._diagnostics.clear()
        if not self.login_state.oauth_token:
            self._note("No auth-token cookie value saved yet.")
            return []

        try:
            self.validate_oauth_token()
        except ValueError as exc:
            self._note(str(exc))
            return []

        try:
            inventory_response = self._post_gql(INVENTORY_QUERY, client_profile="android")
        except requests.RequestException as exc:
            self._note(f"Inventory query failed: {exc}")
            return []
        current_user = inventory_response.get("data", {}).get("currentUser")
        if current_user is None:
            self._note("Inventory query returned currentUser=null. Check the auth-token value.")
            return []

        inventory = current_user.get("inventory", {}) or {}
        ongoing_campaigns = inventory.get("dropCampaignsInProgress", []) or []
        inventory_data = {
            campaign.get("id", ""): campaign
            for campaign in ongoing_campaigns
            if campaign.get("id")
        }
        self._note(f"Inventory returned {len(ongoing_campaigns)} in-progress campaign(s).")

        campaigns_response: dict[str, Any] = {}
        campaign_profiles = ("android", "web")
        for campaign_profile in campaign_profiles:
            try:
                attempted_response = self._post_gql(CAMPAIGNS_QUERY, client_profile=campaign_profile)
            except requests.RequestException as exc:
                self._note(f"ViewerDropsDashboard query failed with {campaign_profile}: {exc}")
                continue
            if isinstance(attempted_response, dict):
                campaigns_response = attempted_response
            dashboard_user = campaigns_response.get("data", {}).get("currentUser")
            available_list = dashboard_user.get("dropCampaigns", []) or [] if dashboard_user else []
            if available_list:
                self._note(f"ViewerDropsDashboard returned campaigns with {campaign_profile} headers.")
                break
        if not campaigns_response:
            return []
        dashboard_user = campaigns_response.get("data", {}).get("currentUser")
        if dashboard_user is None:
            self._note("ViewerDropsDashboard returned currentUser=null.")
            return []

        available_list = dashboard_user.get("dropCampaigns", []) or []
        valid_statuses = {"ACTIVE", "UPCOMING"}
        available_campaigns = {
            campaign.get("id", ""): campaign
            for campaign in available_list
            if campaign.get("id") and campaign.get("status") in valid_statuses
        }
        if not available_campaigns:
            available_campaigns = self._campaigns_from_drops_page()
        self._note(f"Dashboard returned {len(available_campaigns)} active/upcoming campaign(s).")

        detailed_campaigns: dict[str, dict[str, Any]] = {}
        identity_candidates = [
            candidate
            for candidate in (self.login_state.user_id, self.login_state.login_name)
            if candidate
        ]
        for identity in identity_candidates:
            details_payload: list[dict[str, Any]] = []
            for campaign_id in available_campaigns:
                operation = self._clone_query(CAMPAIGN_DETAILS_QUERY)
                operation["variables"]["channelLogin"] = identity
                operation["variables"]["dropID"] = campaign_id
                details_payload.append(operation)

            attempted_details: dict[str, dict[str, Any]] = {}
            for start in range(0, len(details_payload), 20):
                chunk = details_payload[start:start + 20]
                if not chunk:
                    continue
                try:
                    responses = self._post_gql(chunk, client_profile="android")
                except requests.RequestException as exc:
                    self._note(f"DropCampaignDetails query failed: {exc}")
                    continue
                if not isinstance(responses, list):
                    responses = [responses]
                for response in responses:
                    campaign_data = response.get("data", {}).get("user", {}).get("dropCampaign")
                    if campaign_data and campaign_data.get("id"):
                        attempted_details[campaign_data["id"]] = campaign_data
            if attempted_details:
                detailed_campaigns = attempted_details
                self._note(
                    f"DropCampaignDetails worked with identity '{identity}' "
                    f"for {len(detailed_campaigns)} campaign(s)."
                )
                break
        self._note(f"Fetched detailed info for {len(detailed_campaigns)} campaign(s).")

        merged_campaigns: dict[str, dict[str, Any]] = {}
        for campaign_id in set(inventory_data) | set(available_campaigns) | set(detailed_campaigns):
            merged = inventory_data.get(campaign_id, {})
            if campaign_id in available_campaigns:
                merged = self._merge_data(merged, available_campaigns[campaign_id]) if merged else available_campaigns[campaign_id]
            if campaign_id in detailed_campaigns:
                merged = self._merge_data(merged, detailed_campaigns[campaign_id]) if merged else detailed_campaigns[campaign_id]
            merged_campaigns[campaign_id] = merged

        campaigns: list[DropCampaign] = []
        for payload in merged_campaigns.values():
            campaign = self._parse_campaign(payload)
            if campaign is not None:
                campaigns.append(campaign)

        campaigns.sort(key=lambda item: item.starts_at)
        campaigns.sort(key=lambda item: item.active, reverse=True)
        if not campaigns:
            self._note("ViewerDropsDashboard is empty or integrity-protected. Trying browser fallback.")
            campaigns = self._campaigns_from_browser_page()
            campaigns.sort(key=lambda item: item.starts_at)
            campaigns.sort(key=lambda item: item.active, reverse=True)
        self._note(
            f"Parsed {len(campaigns)} campaign(s), {sum(campaign.eligible for campaign in campaigns)} eligible for farming."
        )
        if not campaigns:
            self._note("No campaigns were available for this account at the moment.")
        return campaigns

    def resolve_game_slug(self, game_name: str) -> str:
        cached = self._slug_cache.get(game_name.casefold())
        if cached is not None:
            return cached

        payload = self._clone_query(GAME_REDIRECT_QUERY)
        payload["variables"]["name"] = game_name
        response = self._post_gql(payload)
        slug = response.get("data", {}).get("game", {}).get("slug", "") or ""
        self._slug_cache[game_name.casefold()] = slug
        if not slug:
            self._note(f"Could not resolve a Twitch directory slug for {game_name}.")
        return slug

    def fetch_streams(self, campaign: DropCampaign) -> list[StreamCandidate]:
        slug = campaign.game_slug or self.resolve_game_slug(campaign.game_name)
        if not slug:
            return []

        payload = self._clone_query(GAME_DIRECTORY_QUERY)
        payload["variables"]["slug"] = slug
        response = self._post_gql(payload)
        edges = response.get("data", {}).get("game", {}).get("streams", {}).get("edges", []) or []
        output: list[StreamCandidate] = []
        for edge in edges:
            node = edge.get("node", {}) or {}
            broadcaster = node.get("broadcaster", {}) or {}
            login = broadcaster.get("login", "") or ""
            if not login:
                continue
            output.append(
                StreamCandidate(
                    login=login,
                    display_name=broadcaster.get("displayName", "") or login,
                    game_name=campaign.game_name,
                    viewer_count=int(node.get("viewersCount", 0) or 0),
                    drops_enabled=True,
                )
            )
        self._note(f"Found {len(output)} drops-enabled stream(s) for {campaign.game_name}.")
        return output


if __name__ == "__main__":
    raise SystemExit(
        "Este ficheiro e um modulo interno. "
        "Arranca a aplicacao com `$env:PYTHONPATH='src'; python -m twitch_drop_farmer` "
        "depois de instalares as dependências com `python -m pip install -r requirements.txt`."
    )
