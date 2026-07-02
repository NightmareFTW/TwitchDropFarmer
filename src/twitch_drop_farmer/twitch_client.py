from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace as dataclass_replace
from datetime import datetime, timedelta, timezone
import base64
import gzip
import hashlib
import html as html_module
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import quote, urljoin

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
    from twitch_drop_farmer.config import CAMPAIGN_CACHE_FILE, COOKIE_FILE, CONFIG_DIR
    from twitch_drop_farmer.models import DropCampaign, StreamCandidate
else:
    from .config import CAMPAIGN_CACHE_FILE, COOKIE_FILE, CONFIG_DIR
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
CAMPAIGN_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Jogos "especiais" cujas campanhas podem ser farmadas em qualquer stream com drops activos.
# IRL (509672) e Special Events (509663) — correspondem ao mesmo critério do DevilXD/TwitchDropsMiner.
SPECIAL_GAME_SLUGS: frozenset[str] = frozenset({"irl", "special-events"})

# Injected before any page script runs in the invisible browser fallback profile.
# Patches window.fetch/XMLHttpRequest to (1) capture GQL /gql campaign responses and
# (2) harvest the Client-Integrity header Twitch's own JS attaches to its /gql
# requests, so it can be reused for our direct HTTP requests afterwards instead of
# needing the browser again for every single call.
_GQL_INTERCEPT_JS = """(function() {
    if (window.__tdfGqlInterceptInstalled) return;
    window.__tdfGqlInterceptInstalled = true;
    window.__tdfGqlStore = {};
    window.__tdfIntegrityToken = null;
    window.__tdfIntegrityTokenAt = 0;

    function _store(c) {
        if (!c || !c.id) return;
        var ex = window.__tdfGqlStore[c.id];
        if (!ex) { window.__tdfGqlStore[c.id] = c; return; }
        var hasNew = c.timeBasedDrops && c.timeBasedDrops.length > 0;
        var hasEx  = ex.timeBasedDrops  && ex.timeBasedDrops.length  > 0;
        if (hasNew && !hasEx) {
            window.__tdfGqlStore[c.id] = Object.assign({}, ex, c);
        } else {
            window.__tdfGqlStore[c.id] = Object.assign({}, c, ex);
        }
    }

    function _process(data) {
        try {
            var items = Array.isArray(data) ? data : [data];
            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                if (!item || !item.data) continue;
                var d = item.data;
                var cu = d.currentUser;
                if (cu) {
                    if (Array.isArray(cu.dropCampaigns))
                        cu.dropCampaigns.forEach(_store);
                    if (cu.inventory && Array.isArray(cu.inventory.dropCampaignsInProgress))
                        cu.inventory.dropCampaignsInProgress.forEach(_store);
                }
                if (d.user && d.user.dropCampaign) _store(d.user.dropCampaign);
                if (d.dropCampaign) _store(d.dropCampaign);
            }
        } catch(e) {}
    }

    function _extractIntegrity(headers) {
        try {
            if (!headers) return null;
            if (typeof headers.get === 'function') {
                return headers.get('Client-Integrity') || headers.get('client-integrity') || null;
            }
            for (var k in headers) {
                if (Object.prototype.hasOwnProperty.call(headers, k) && k.toLowerCase() === 'client-integrity') {
                    return headers[k];
                }
            }
        } catch(e) {}
        return null;
    }

    function _captureIntegrity(token) {
        if (token) {
            window.__tdfIntegrityToken = token;
            window.__tdfIntegrityTokenAt = Date.now();
        }
    }

    var _oFetch = window.fetch;
    window.fetch = function(input, init) {
        try {
            var url = typeof input === 'string' ? input : (input && input.url) || '';
            if (url.indexOf('/gql') !== -1) {
                var hdrs = (init && init.headers) || (input && input.headers);
                _captureIntegrity(_extractIntegrity(hdrs));
            }
        } catch(e) {}
        return _oFetch.call(this, input, init).then(function(r) {
            try {
                var url = typeof input === 'string' ? input : (input && input.url) || '';
                if (url.indexOf('/gql') !== -1)
                    r.clone().json().then(_process)['catch'](function() {});
            } catch(e) {}
            return r;
        });
    };

    var _oOpen = XMLHttpRequest.prototype.open;
    var _oSend = XMLHttpRequest.prototype.send;
    var _oSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function(m, url) {
        this.__tdfU = String(url || '');
        return _oOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        try {
            if (this.__tdfU && this.__tdfU.indexOf('/gql') !== -1 && name && name.toLowerCase() === 'client-integrity') {
                _captureIntegrity(value);
            }
        } catch(e) {}
        return _oSetHeader.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        if (this.__tdfU && this.__tdfU.indexOf('/gql') !== -1) {
            var x = this;
            this.addEventListener('load', function() {
                try { _process(JSON.parse(x.responseText)); } catch(e) {}
            });
        }
        return _oSend.apply(this, arguments);
    };
})();"""

# Reads back what _GQL_INTERCEPT_JS has captured so far. Returns a JSON object
# (not a bare array) so the harvested integrity token travels alongside the
# captured campaign payloads.
_RETRIEVE_GQL_STORE_JS = """(() => {
    try {
        return JSON.stringify({
            campaigns: Object.values(window.__tdfGqlStore || {}),
            integrityToken: window.__tdfIntegrityToken || null,
            integrityTokenAt: window.__tdfIntegrityTokenAt || 0
        });
    } catch(e) { return '{}'; }
})();"""

# How long a harvested Client-Integrity token is trusted for direct HTTP requests
# before we stop offering it and fall back to the browser to mint a fresh one.
# Twitch doesn't publish a real TTL; this is a conservative guess -- a request
# that still fails with the token attached clears it immediately regardless.
_INTEGRITY_TOKEN_TTL_SECONDS = 240.0

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
            "sort": "VIEWER_COUNT",
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
PLAYBACK_ACCESS_TOKEN_QUERY = {
    "operationName": "PlaybackAccessToken_Template",
    "query": (
        "query PlaybackAccessToken_Template(" \
        "$login: String!, $playerType: String!, $platform: String!, $playerBackend: String!" \
        ") { " \
        "streamPlaybackAccessToken(channelName: $login, " \
        "params: {platform: $platform, playerBackend: $playerBackend, playerType: $playerType}) { " \
        "value signature __typename" \
        " } }"
    ),
    "variables": {
        "login": "",
        "playerType": "site",
        "platform": "web",
        "playerBackend": "mediaplayer",
    },
}
STREAM_INFO_QUERY = {
    "operationName": "VideoPlayerStreamInfoOverlayChannel",
    "variables": {"channel": ""},
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "198492e0857f6aedead9665c81c5a06d67b25b58034649687124083ff288597d",
        }
    },
}
CURRENT_DROP_QUERY = {
    "operationName": "CurrentDrop",
    "query": (
        "query CurrentDrop($channelID: String!) { "
        "currentUser { "
        "dropCurrentSession(channelID: $channelID) { "
        "dropID currentMinutesWatched "
        "} "
        "} "
        "}"
    ),
    "variables": {"channelID": ""},
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
        self._game_box_art_cache: dict[str, str] = {}
        self._external_box_art_cache: dict[str, str] = {}
        self._streamless_media_playlist_cache: dict[str, str] = {}
        # Cache for _stream_info results: {login_lower: (channel_id, broadcast_id, game_id, timestamp)}
        self._streamless_stream_info_cache: dict[str, tuple[str, str, str, float]] = {}
        # Campaigns known from any past fetch_campaigns() call, keyed by campaign ID.
        # A single call rarely sees the whole catalog (background-thread calls can't
        # use the browser fallback, so most cycles only return the 1-2 in-progress
        # campaigns from Inventory). Merging into this cache instead of replacing it
        # lets whitelisted games outside the one being actively farmed stay visible
        # and slowly accumulate real data as richer fetches happen over time.
        # It is also persisted to disk (see _load/_save_campaign_cache) so the full
        # game catalog survives app restarts instead of being empty (only inventory
        # games) until the first browser-fallback fetch succeeds again.
        self._campaign_cache: dict[str, DropCampaign] = {}
        self._campaign_cache_lock = threading.Lock()
        self._load_campaign_cache()
        # Game the UI currently wants real per-drop detail for (the selected or
        # auto-picked farm target), set via set_priority_game(). Only 8 campaigns
        # get a detail-page visit per browser cycle out of a whitelist that can
        # have 100+, so without this the game actually being farmed can go many
        # cycles with next_drop_name/required_minutes still empty.
        self._priority_game_name: str = ""
        # Persistent QWebEngineProfile shared by every browser-fallback call, so
        # cookies/local storage survive across calls instead of a brand-new
        # anonymous profile being fingerprinted every single time. Created lazily
        # by _get_browser_profile() since it needs a live QApplication.
        self._browser_profile: Any = None
        # Client-Integrity token harvested from the invisible browser's own GQL
        # requests (see _GQL_INTERCEPT_JS), reused on direct HTTP requests until
        # it expires or a request rejects it. See _current_integrity_token().
        self._harvested_integrity_token: str = ""
        self._harvested_integrity_token_captured_mono: float = 0.0
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

    def clear_box_art_caches(self) -> None:
        self._game_box_art_cache.clear()
        self._external_box_art_cache.clear()

    def resolve_external_box_art_url(self, game_name: str) -> str:
        return self._resolve_external_game_box_art_url(game_name)

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
        tmp = COOKIE_FILE.with_suffix(".tmp")
        tmp.write_text(
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
        os.replace(tmp, COOKIE_FILE)

    def export_session_json(self) -> str:
        """Exporta a sessão completa como JSON para importar depois (modo duradouro)."""
        serialized = [
            {"name": cookie.name, "value": cookie.value, "domain": cookie.domain}
            for cookie in self.session.cookies
        ]
        export_data = {
            "cookies": serialized,
            "user_id": self.login_state.user_id,
            "login_name": self.login_state.login_name,
            "device_id": self.device_id,
            "session_id": self.session_id,
        }
        return json.dumps(export_data, indent=2)

    def import_session_json(self, session_json: str) -> None:
        """Importa uma sessão completa de JSON (modo duradouro)."""
        try:
            data = json.loads(session_json)
            for cookie in data.get("cookies", []):
                self.session.cookies.set(
                    cookie["name"], 
                    cookie["value"], 
                    domain=cookie.get("domain")
                )
            self.login_state.user_id = data.get("user_id", "")
            self.login_state.login_name = data.get("login_name", "")
            self.device_id = data.get("device_id", "")
            self.session_id = data.get("session_id", self.session_id)
            
            # Se houver auth-token nos cookies, usá-lo como fallback
            auth_token = self.session.cookies.get("auth-token", domain=".twitch.tv")
            if auth_token and not self.login_state.oauth_token:
                self.login_state.oauth_token = auth_token
                self._apply_oauth_token(auth_token)
            
            self._note("Session imported successfully from browser export.")
            self.save_cookies()
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid session JSON format: {e}")

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
        integrity_token = self._current_integrity_token()
        if integrity_token:
            headers["Client-Integrity"] = integrity_token
        return headers

    def _current_integrity_token(self) -> str:
        """Return the harvested Client-Integrity token if it's still within its
        trust window, else "" (never expire it destructively here -- callers that
        get rejected even with a token call _clear_integrity_token())."""
        if not self._harvested_integrity_token:
            return ""
        age = time.monotonic() - self._harvested_integrity_token_captured_mono
        if age > _INTEGRITY_TOKEN_TTL_SECONDS:
            return ""
        return self._harvested_integrity_token

    def _clear_integrity_token(self) -> None:
        self._harvested_integrity_token = ""
        self._harvested_integrity_token_captured_mono = 0.0

    def _capture_integrity_from_retrieved(self, parsed: dict[str, Any]) -> None:
        """Pull an integrityToken out of a decoded _RETRIEVE_GQL_STORE_JS payload
        and remember it for reuse on direct HTTP requests (see _gql_headers)."""
        token = parsed.get("integrityToken")
        if isinstance(token, str) and token and token != self._harvested_integrity_token:
            self._harvested_integrity_token = token
            self._harvested_integrity_token_captured_mono = time.monotonic()
            self._note("Token de integridade capturado do browser invisível para pedidos directos.")

    def _stream_headers(self, channel_login: str) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "Accept-Language": "en-US",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": f"{TWITCH_URL}/{channel_login}",
            "User-Agent": WEB_USER_AGENT,
        }

    def _post_gql_web(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            GQL_URL,
            json=payload,
            headers=self._gql_headers("web"),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        self._note_graphql_errors(payload, data)
        return data

    def _streamless_media_playlist(self, channel_login: str) -> str:
        cached = self._streamless_media_playlist_cache.get(channel_login.casefold(), "")
        if cached:
            return cached

        payload = self._clone_query(PLAYBACK_ACCESS_TOKEN_QUERY)
        payload["variables"]["login"] = channel_login
        token_response = self._post_gql_web(payload)
        token_data = token_response.get("data", {}).get("streamPlaybackAccessToken", {}) or {}
        signature = str(token_data.get("signature", "")).strip()
        token = str(token_data.get("value", "")).strip()
        if not signature or not token:
            raise ValueError("PlaybackAccessToken returned an empty signature/token.")

        hls_url = (
            f"https://usher.ttvnw.net/api/channel/hls/{channel_login}.m3u8"
            f"?allow_source=true"
            f"&allow_audio_only=true"
            f"&fast_bread=true"
            f"&player_backend=mediaplayer"
            f"&playlist_include_framerate=true"
            f"&reassignments_supported=true"
            f"&sig={quote(signature, safe='')}"
            f"&token={quote(token, safe='')}"
            f"&type=any"
            f"&p={secrets.randbelow(1_000_000)}"
        )
        response = self.session.get(
            hls_url,
            headers=self._stream_headers(channel_login),
            timeout=20,
        )
        response.raise_for_status()

        media_playlist = ""
        for line in response.text.splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            media_playlist = urljoin(response.url, candidate)
            break

        if not media_playlist:
            raise ValueError("Could not resolve media playlist from HLS master manifest.")

        self._streamless_media_playlist_cache[channel_login.casefold()] = media_playlist
        return media_playlist

    def _stream_info(self, channel_login: str) -> dict[str, str]:
        payload = self._clone_query(STREAM_INFO_QUERY)
        payload["variables"]["channel"] = channel_login
        response = self._post_gql(payload, client_profile="web")
        user = (response.get("data") or {}).get("user") or {}
        stream = user.get("stream") or {}
        settings = user.get("broadcastSettings") or {}
        game = settings.get("game") or {}
        channel_id = str(user.get("id", "") or "").strip()
        broadcast_id = str(stream.get("id", "") or "").strip()
        game_id = str(game.get("id", "") or "").strip()
        return {
            "channel_id": channel_id,
            "broadcast_id": broadcast_id,
            "game_id": game_id,
        }

    def _streamless_gql_payload(
        self,
        *,
        channel_login: str,
        channel_id: str,
        broadcast_id: str,
        game_name: str = "",
        game_id: str = "",
    ) -> dict[str, Any]:
        """Build a sendSpadeEvents GQL mutation payload for the minute-watched event.

        Twitch now routes watch-time attribution through the GQL endpoint
        (mutation SendEvents / sendSpadeEvents) rather than the deprecated
        external spade.twitch.tv analytics endpoint.  The event data is
        gzip-compressed, base64-encoded, and sent as the `input` variable.
        """
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        properties: dict[str, object] = {
            # Twitch expects these fields as strings in the minute-watched event payload.
            "broadcast_id": str(broadcast_id),
            "channel_id": str(channel_id),
            "channel": channel_login,
            "client_time": now_iso,
            "game": game_name,
            "game_id": game_id,
            "hidden": False,
            "is_live": True,
            "live": True,
            "logged_in": True,
            "minutes_logged": 1,
            "muted": False,
            "user_id": str(self.login_state.user_id),
        }
        payload = [{"event": "minute-watched", "properties": properties}]
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        encoded = base64.b64encode(gzip.compress(raw.encode("utf-8"))).decode("ascii")
        return {
            "query": (
                "\n mutation SendEvents($input: SendSpadeEventsInput!) "
                "{\n sendSpadeEvents(input: $input) {\n statusCode\n}\n}\n"
            ),
            "variables": {
                "input": {
                    "data": encoded,
                    "repository": "twilight",
                    "encoding": "GZIP_B64",
                }
            },
        }

    def _streamless_watch_hls_head(self, channel_login: str) -> bool:
        try:
            playlist_url = self._streamless_media_playlist(channel_login)
            playlist_response = self.session.get(
                playlist_url,
                headers=self._stream_headers(channel_login),
                timeout=20,
            )
            playlist_response.raise_for_status()
        except Exception as exc:
            self._streamless_media_playlist_cache.pop(channel_login.casefold(), None)
            self._note(f"Streamless HLS fallback failed for {channel_login}: {exc}")
            return False

        segment_url = ""
        chunks = [line.strip() for line in playlist_response.text.splitlines() if line.strip()]
        for candidate in reversed(chunks):
            if candidate.startswith("#"):
                continue
            segment_url = urljoin(playlist_response.url, candidate)
            break
        if not segment_url:
            self._note(f"Streamless HLS fallback did not find media segments for {channel_login}.")
            return False

        try:
            segment_response = self.session.head(
                segment_url,
                headers=self._stream_headers(channel_login),
                timeout=20,
            )
            segment_response.raise_for_status()
        except Exception as exc:
            self._note(f"Streamless HLS HEAD request failed for {channel_login}: {exc}")
            return False
        return True

    def _streamless_watch_hls_range_get(self, channel_login: str) -> bool:
        """Perform a small ranged GET on a media segment to emulate real viewing traffic."""
        try:
            playlist_url = self._streamless_media_playlist(channel_login)
            playlist_response = self.session.get(
                playlist_url,
                headers=self._stream_headers(channel_login),
                timeout=20,
            )
            playlist_response.raise_for_status()
        except Exception as exc:
            self._streamless_media_playlist_cache.pop(channel_login.casefold(), None)
            self._note(f"Streamless HLS range-get fallback failed for {channel_login}: {exc}")
            return False

        segment_url = ""
        chunks = [line.strip() for line in playlist_response.text.splitlines() if line.strip()]
        for candidate in reversed(chunks):
            if candidate.startswith("#"):
                continue
            segment_url = urljoin(playlist_response.url, candidate)
            break
        if not segment_url:
            self._note(f"Streamless HLS range-get did not find media segments for {channel_login}.")
            return False

        try:
            headers = self._stream_headers(channel_login)
            headers["Range"] = "bytes=0-4095"
            headers["Connection"] = "close"
            segment_response = self.session.get(
                segment_url,
                headers=headers,
                timeout=20,
                stream=True,
            )
            segment_response.raise_for_status()
            # Read a tiny amount to ensure the request is actually consumed.
            for _chunk in segment_response.iter_content(chunk_size=1024):
                break
        except Exception as exc:
            self._note(f"Streamless HLS range-get request failed for {channel_login}: {exc}")
            return False
        finally:
            try:
                segment_response.close()
            except Exception:
                pass
        return True

    def _stream_info_cached(self, channel_login: str) -> dict[str, str]:
        """Return stream info with a 90-second TTL cache to minimise GQL chatter."""
        cache_key = channel_login.casefold()
        cached = self._streamless_stream_info_cache.get(cache_key)
        if cached:
            channel_id, broadcast_id, game_id, ts = cached
            if time.monotonic() - ts < 90:
                return {"channel_id": channel_id, "broadcast_id": broadcast_id, "game_id": game_id}
        ids = self._stream_info(channel_login)
        self._streamless_stream_info_cache[cache_key] = (
            ids.get("channel_id", ""),
            ids.get("broadcast_id", ""),
            ids.get("game_id", ""),
            time.monotonic(),
        )
        return ids

    def streamless_watch_heartbeat(
        self,
        channel_login: str,
        *,
        channel_id: str = "",
        broadcast_id: str = "",
        game_name: str = "",
    ) -> bool:
        """Send a minute-watched event via the GQL sendSpadeEvents mutation.

        Twitch deprecated the external spade.twitch.tv analytics endpoint.
        Watch-time attribution now goes through the GQL API directly.
        Falls back to HLS HEAD request if the GQL mutation fails.
        """
        login = channel_login.strip()
        if not login:
            return False
        if not self.login_state.oauth_token:
            self._note("Streamless heartbeat skipped: sem auth-token.")
            return False
        if not self.login_state.user_id:
            self._note("Streamless heartbeat skipped: user_id não resolvido — aguardar validação do token.")
            return False

        try:
            # Always refresh stream IDs via a TTL-cached GQL call so stale broadcast_ids
            # (from a snapshot that pre-dates a stream restart) never silently break
            # watch-time attribution on Twitch's side.
            ids = self._stream_info_cached(login)
            # If the cache returned empty IDs, fall back to the caller-supplied values.
            if not ids.get("channel_id") or not ids.get("broadcast_id"):
                ids = {
                    "channel_id": channel_id.strip(),
                    "broadcast_id": broadcast_id.strip(),
                    "game_id": "",
                }
            if not ids["channel_id"] or not ids["broadcast_id"]:
                self._note(f"Streamless heartbeat could not resolve stream IDs for {login}.")
                return self._streamless_watch_hls_head(login)

            mutation = self._streamless_gql_payload(
                channel_login=login,
                channel_id=ids["channel_id"],
                broadcast_id=ids["broadcast_id"],
                game_name=game_name,
                game_id=ids.get("game_id", ""),
            )
            response = self._post_gql_web(mutation)
            status_code = (
                (response.get("data") or {})
                .get("sendSpadeEvents", {})
                .get("statusCode")
            )
            if status_code == 204:
                uid = self.login_state.user_id or "?"
                bcast = ids.get("broadcast_id", "?")
                self._note(
                    f"sendSpadeEvents OK | canal={login} | uid={uid}"
                    f" | broadcast={bcast} | canal_id={ids.get('channel_id', '?')}"
                )
                # Reinforce watch attribution with a lightweight media segment touch.
                # Some sessions acknowledge sendSpadeEvents (204) but only advance
                # drop minutes once HLS media endpoints are touched periodically.
                if not self._streamless_watch_hls_range_get(login):
                    if not self._streamless_watch_hls_head(login):
                        self._note(f"HLS reinforcement ping falhou para {login} (GQL já OK).")
                return True
            self._note(f"sendSpadeEvents devolveu status {status_code} para {login}.")
            return self._streamless_watch_hls_head(login)
        except Exception as exc:
            self._note(f"Streamless heartbeat falhou para {login}: {exc}")
            self._streamless_stream_info_cache.pop(login.casefold(), None)
            return self._streamless_watch_hls_head(login)

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

        total_timeout_seconds = 35.0
        started_at = time.monotonic()
        last_data: dict[str, Any] | list[dict[str, Any]] = {}
        last_exception: requests.RequestException | None = None
        for profile in profiles_to_try:
            elapsed = time.monotonic() - started_at
            remaining = total_timeout_seconds - elapsed
            if remaining <= 0:
                self._note("GraphQL request aborted after exceeding total retry timeout.")
                break

            request_timeout = max(5.0, min(20.0, remaining))
            try:
                response = self.session.post(
                    GQL_URL,
                    json=payload,
                    headers=self._gql_headers(profile),
                    timeout=request_timeout,
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as exc:
                last_exception = exc
                self._note(f"GraphQL request failed with {profile} profile: {exc}")
                continue
            except ValueError as exc:
                self._note(f"GraphQL response was not valid JSON ({profile} profile): {exc}")
                return last_data

            last_data = data
            self._note_graphql_errors(payload, data)

            messages = self._graphql_error_messages(data)
            if not messages:
                return data
            if any("failed integrity check" in message for message in messages) and self._harvested_integrity_token:
                # The token we offered got rejected -- stop sending it until the
                # browser fallback harvests a fresh one.
                self._clear_integrity_token()
            if any(any(marker in message for marker in retryable_errors) for message in messages):
                self._note(f"Retrying GraphQL request using {profile} headers after error: {messages[0]}")
                continue
            return data

        if last_exception is not None:
            raise last_exception
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
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                # Backward compatibility with cache files that stored naive timestamps.
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            self._note(f"Invalid timestamp received from Twitch: {raw!r}")
            return datetime.now(timezone.utc)

    def _drop_totals(self, drops: list[dict[str, Any]]) -> tuple[int, int]:
        by_id = {
            drop.get("id", ""): drop
            for drop in drops
            if drop.get("id")
        }

        def totals(drop_id: str) -> tuple[int, int]:
            drop = by_id.get(drop_id, {})
            required = int(drop.get("requiredMinutesWatched", 0) or 0)
            drop_self = drop.get("self") or {}
            # Claimed drops need 0 additional time regardless of currentMinutesWatched
            is_claimed = bool(drop_self.get("isClaimed", False))
            if is_claimed:
                remaining = 0
            else:
                current = int(drop_self.get("currentMinutesWatched", 0) or 0)
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

    def _all_drops_claimed(self, drops: list[dict[str, Any]]) -> bool:
        if not drops:
            return False
        for drop in drops:
            if not bool((drop.get("self") or {}).get("isClaimed", False)):
                return False
        return True

    def _campaign_claimed_from_payload(self, payload: dict[str, Any]) -> bool:
        claim_flag_keys = {
            "allrewardsclaimed",
            "allclaimed",
            "alldropsclaimed",
            "allbenefitsclaimed",
        }
        claim_state_keys = {
            "campaignclaimstate",
            "campaignrewardclaimstate",
        }
        claim_state_values = {
            "all_claimed",
            "completed",
        }
        candidate_nodes = [payload]
        payload_self = payload.get("self")
        if isinstance(payload_self, dict):
            candidate_nodes.append(payload_self)
        campaign_node = payload.get("campaign")
        if isinstance(campaign_node, dict):
            candidate_nodes.append(campaign_node)
            campaign_self = campaign_node.get("self")
            if isinstance(campaign_self, dict):
                candidate_nodes.append(campaign_self)

        for node in candidate_nodes:
            for key, value in node.items():
                key_norm = str(key).strip().replace("_", "").casefold()
                if key_norm in claim_flag_keys and bool(value):
                    return True
                if key_norm in claim_state_keys and isinstance(value, str):
                    value_norm = value.strip().replace("_", "").casefold()
                    if value_norm in claim_state_values:
                        return True
        return False

    def _campaign_requires_subscription(self, payload: dict[str, Any], drops: list[dict[str, Any]]) -> bool:
        subscription_flag_keys = {
            "issubscriberonly",
            "requiresubscription",
            "subscriptionrequired",
            "requires_subscription",
            "is_subscriber_only",
            "issubscriptionrequired",
            "issubonly",
            "subscribersonly",
            "subscriberonly",
        }

        subscription_value_keys = {
            "requiredaction",
            "actiontype",
            "unlockmethod",
            "accesstype",
            "requirementtype",
            "redemptiontype",
            "redeemtype",
            "eligibilitytype",
        }

        def walk_struct(node: Any) -> bool:
            if isinstance(node, dict):
                for key, value in node.items():
                    key_norm = str(key).strip().replace("_", "").casefold()
                    # Only match explicit boolean-flag keys known to mean "subscription required".
                    # Avoid broad matching on any key that contains "subscription" because
                    # Twitch returns many non-requirement fields (e.g. subscriptionBenefit) that
                    # are legitimately present on open campaigns and would cause false positives.
                    if key_norm in subscription_flag_keys and bool(value):
                        return True
                    if key_norm in subscription_value_keys and isinstance(value, str):
                        value_norm = value.strip().casefold()
                        if "sub" in value_norm and "watch" not in value_norm:
                            return True
                    if walk_struct(value):
                        return True
                return False
            if isinstance(node, list):
                for item in node:
                    if walk_struct(item):
                        return True
                return False
            return False

        def required_minutes_from_drop(drop: dict[str, Any]) -> int | None:
            # Some fallback payloads omit requiredMinutesWatched entirely; treat that as
            # unknown (None), not as 0, to avoid classifying normal campaigns as sub-only.
            for key in ("requiredMinutesWatched", "required_minutes"):
                if key not in drop:
                    continue
                value = drop.get(key)
                if value is None:
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
            return None

        payload_requires_subscription = walk_struct(payload)

        has_drops = False
        has_watchable_drop = False
        has_drop_struct_subscription = False
        has_known_required_minutes = False
        all_known_required_are_zero = True
        for drop in drops:
            if not isinstance(drop, dict):
                continue
            has_drops = True
            drop_requires_subscription = walk_struct(drop)
            if drop_requires_subscription:
                has_drop_struct_subscription = True

            required_minutes = required_minutes_from_drop(drop)
            if required_minutes is None:
                all_known_required_are_zero = False
                continue

            has_known_required_minutes = True
            if required_minutes > 0 and not drop_requires_subscription:
                has_watchable_drop = True
                all_known_required_are_zero = False

        # Mixed campaigns (watchable + sub-related benefits) are not subscription-locked.
        if has_watchable_drop:
            return False

        # If campaign-level flags explicitly require a subscription and there are no
        # watchable drops, classify as subscription-locked.
        if payload_requires_subscription:
            return True

        # Explicit per-drop subscription flags with no watchable drops.
        if has_drop_struct_subscription:
            return True

        # Only infer sub-only when ALL known drop requirements are explicit zeros.
        # If requirement minutes are missing/unknown, do not infer subscription lock.
        if has_drops and has_known_required_minutes and all_known_required_are_zero:
            return True

        return False

    def _compute_has_watchable_drops(self, drops: list[dict[str, Any]]) -> bool:
        """Return True if at least one drop can be earned by watching (no subscription required)."""
        for drop in drops:
            required = int(drop.get("requiredMinutesWatched", 0) or 0)
            if required <= 0:
                continue
            # Re-use subscription check scoped to this single drop (empty campaign payload)
            if not self._campaign_requires_subscription({}, [drop]):
                return True
        return False

    def _drop_progress_items(self, drops: list[dict[str, Any]]) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for drop in drops:
            drop_id = str(drop.get("id", "") or "").strip()
            required = int(drop.get("requiredMinutesWatched", 0) or 0)
            current = int((drop.get("self") or {}).get("currentMinutesWatched", 0) or 0)
            claimed = bool((drop.get("self") or {}).get("isClaimed", False))
            name = str(drop.get("name", "") or "").strip()
            image_url = ""

            def pick_image(candidate: Any) -> str:
                if not isinstance(candidate, str):
                    return ""
                text = candidate.strip().replace("\\/", "/")
                if text.startswith("http://") or text.startswith("https://"):
                    return text
                return ""

            image_url = pick_image(drop.get("imageAssetURL") or drop.get("imageAssetUrl"))
            if not image_url:
                image_url = pick_image(drop.get("boxArtURL") or drop.get("boxArtUrl"))
            for edge in drop.get("benefitEdges", []) or []:
                benefit = edge.get("benefit", {}) or {}
                if not name:
                    candidate = str(benefit.get("name", "") or "").strip()
                    if candidate:
                        name = candidate
                if not image_url:
                    image_url = pick_image(
                        benefit.get("imageAssetURL")
                        or benefit.get("imageAssetUrl")
                        or benefit.get("imageURL")
                        or benefit.get("imageUrl")
                    )
                if name and image_url:
                    break
            if not name:
                name = "Drop"
            remaining = max(0, required - current)
            items.append(
                {
                    "id": drop_id,
                    "name": name,
                    "image_url": image_url,
                    "required_minutes": required,
                    "current_minutes": min(current, required) if required > 0 else current,
                    "remaining_minutes": remaining,
                    "claimed": claimed,
                }
            )

        items.sort(
            key=lambda item: (
                bool(item.get("claimed", False)),
                int(item.get("remaining_minutes", 0)),
                str(item.get("name", "")).casefold(),
            )
        )
        return items

    def fetch_current_drop_progress(self, channel_id: str) -> dict[str, object] | None:
        """Fetch current drop session progress for a channel.

        Used as a lightweight reconciliation signal when inventory progress lags
        behind acknowledged streamless heartbeats.
        """
        channel_key = str(channel_id or "").strip()
        if not channel_key:
            return None
        if not self.login_state.oauth_token:
            return None

        payload = self._clone_query(CURRENT_DROP_QUERY)
        payload["variables"]["channelID"] = channel_key
        try:
            response = self._post_gql(payload, client_profile="web")
        except requests.RequestException as exc:
            self._note(f"CurrentDrop query failed for channel {channel_key}: {exc}")
            return None

        current_user = (response.get("data") or {}).get("currentUser") or {}
        session = current_user.get("dropCurrentSession")
        if not isinstance(session, dict):
            return None

        drop_id = str(session.get("dropID", "") or "").strip()
        if not drop_id:
            return None
        try:
            current_minutes = int(session.get("currentMinutesWatched", 0) or 0)
        except (TypeError, ValueError):
            current_minutes = 0

        return {
            "drop_id": drop_id,
            "current_minutes": max(0, current_minutes),
            "channel_id": channel_key,
        }

    def _extract_drop_like_entries(self, payload: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                looks_like_drop = (
                    "requiredMinutesWatched" in node
                    and ("self" in node or "benefitEdges" in node or "preconditionDrops" in node)
                )
                if looks_like_drop:
                    raw_id = str(node.get("id", "")).strip()
                    fingerprint = raw_id or str(id(node))
                    if fingerprint not in seen:
                        seen.add(fingerprint)
                        output.append(node)
                for value in node.values():
                    walk(value)
                return
            if isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return output

    def _extract_campaign_progress_data(self, campaign_data: dict[str, Any]) -> tuple[int, int]:
        """Extract progress data from campaign, trying multiple paths."""
        # Try to get drops array first
        drops = campaign_data.get("timeBasedDrops", []) or []
        if not drops:
            drops = self._extract_drop_like_entries(campaign_data)
        
        if drops:
            total_required, total_remaining = self._drop_totals(drops)
            if total_required > 0:
                return total_required, total_remaining
        
        # Try campaign-level progress fields (inventory format)
        required = int(campaign_data.get("requiredMinutesWatched", 0) or 0)
        if required > 0:
            current = int((campaign_data.get("self", {}) or {}).get("currentMinutesWatched", 0) or 0)
            remaining = max(0, required - current)
            return required, remaining
        
        # Try nested campaign structure
        campaign_obj = campaign_data.get("campaign", {}) or {}
        if isinstance(campaign_obj, dict):
            required = int(campaign_obj.get("requiredMinutesWatched", 0) or 0)
            if required > 0:
                current = int((campaign_obj.get("self", {}) or {}).get("currentMinutesWatched", 0) or 0)
                remaining = max(0, required - current)
                return required, remaining
        
        return 0, 0

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
            drop_self = drop.get("self") or {}
            # Claimed drops contribute 0 remaining time regardless of currentMinutesWatched.
            # Without this check, a precondition drop with isClaimed=True but stale
            # currentMinutesWatched=0 would inflate the ETA of dependent drops.
            if bool(drop_self.get("isClaimed", False)):
                memo[drop_id] = 0
                return 0
            required = int(drop.get("requiredMinutesWatched", 0) or 0)
            current = int(drop_self.get("currentMinutesWatched", 0) or 0)
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
        candidates: list[str] = []
        for key in ("login", "name", "slug", "channelLogin"):
            value = channel.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        nested_channel = channel.get("channel")
        if isinstance(nested_channel, dict):
            for key in ("login", "name", "slug"):
                value = nested_channel.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())

        for token in candidates:
            normalized = token.lstrip("@").strip().casefold()
            if re.fullmatch(r"[a-z0-9_]{2,25}", normalized):
                return normalized
        return ""

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

        page_html = response.text
        found: dict[str, dict[str, Any]] = {}

        def _normalize_status(status: str) -> str:
            normalized_status = str(status or "").strip().upper()
            if normalized_status not in {"ACTIVE", "UPCOMING", "EXPIRED"}:
                return ""
            return normalized_status

        def _merge_found(payload: dict[str, Any]) -> None:
            cid = str(payload.get("id", "") or "").strip()
            if not CAMPAIGN_UUID_PATTERN.fullmatch(cid):
                return

            current = found.get(cid)
            if current is None:
                current = {"id": cid}
                found[cid] = current

            incoming_status = _normalize_status(str(payload.get("status", "") or ""))
            current_status = _normalize_status(str(current.get("status", "") or ""))
            if incoming_status and current_status != "ACTIVE":
                current["status"] = incoming_status

            for key in (
                "name",
                "title",
                "startAt",
                "startsAt",
                "endAt",
                "endsAt",
                "accountLinkURL",
            ):
                value = payload.get(key)
                if isinstance(value, str) and value.strip() and not current.get(key):
                    current[key] = value

            for key in ("allow", "self", "game"):
                value = payload.get(key)
                existing = current.get(key)
                if isinstance(value, dict) and value:
                    if isinstance(existing, dict) and existing:
                        current[key] = self._merge_data(existing, value)
                    else:
                        current[key] = value

            drops_value = payload.get("timeBasedDrops")
            existing_drops = current.get("timeBasedDrops")
            if isinstance(drops_value, list) and drops_value:
                if not isinstance(existing_drops, list) or len(drops_value) > len(existing_drops):
                    current["timeBasedDrops"] = drops_value

        def _normalize_game_payload(node: dict[str, Any]) -> dict[str, Any]:
            game_raw = node.get("game")
            if isinstance(game_raw, dict):
                game: dict[str, Any] = dict(game_raw)
            elif isinstance(game_raw, str) and game_raw.strip():
                game = {"displayName": game_raw.strip()}
            else:
                game = {}

            for source_key, target_key in (
                ("gameName", "displayName"),
                ("displayName", "displayName"),
                ("name", "name"),
                ("slug", "slug"),
                ("boxArtURL", "boxArtURL"),
            ):
                value = node.get(source_key)
                if isinstance(value, str) and value.strip() and not game.get(target_key):
                    game[target_key] = value.strip()
            return game

        def _campaign_payload_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
            if "dropInstanceID" in node:
                return None

            campaign_like = (
                "timeBasedDrops" in node
                or "allow" in node
                or "game" in node
                or "gameName" in node
            )
            if not campaign_like:
                return None

            cid = str(node.get("id", "") or "").strip()
            if not CAMPAIGN_UUID_PATTERN.fullmatch(cid):
                return None

            payload: dict[str, Any] = {
                "id": cid,
                "status": _normalize_status(str(node.get("status", "") or "")),
            }
            name = node.get("name") or node.get("title")
            if isinstance(name, str) and name.strip():
                payload["name"] = name.strip()

            for key in ("startAt", "startsAt", "endAt", "endsAt", "accountLinkURL"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    payload[key] = value.strip()

            for key in ("allow", "self"):
                value = node.get(key)
                if isinstance(value, dict) and value:
                    payload[key] = value

            drops_value = node.get("timeBasedDrops")
            if isinstance(drops_value, list) and drops_value:
                payload["timeBasedDrops"] = drops_value

            game_payload = _normalize_game_payload(node)
            if game_payload:
                payload["game"] = game_payload

            return payload

        def _extract_campaigns_from_json_blob(blob: str) -> None:
            text = html_module.unescape(str(blob or "").strip())
            if not text:
                return
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                return

            stack: list[Any] = [parsed]
            nodes_seen = 0
            while stack and nodes_seen < 20000:
                nodes_seen += 1
                current = stack.pop()
                if isinstance(current, dict):
                    payload = _campaign_payload_from_node(current)
                    if payload is not None:
                        _merge_found(payload)
                    stack.extend(current.values())
                elif isinstance(current, list):
                    stack.extend(current)

        # Extract structured JSON payloads first to maximize data available when
        # DropCampaignDetails is blocked by integrity checks.
        json_blob_patterns = (
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;\s*</script>',
        )
        for pattern in json_blob_patterns:
            for match in re.finditer(pattern, page_html, flags=re.DOTALL | re.IGNORECASE):
                _extract_campaigns_from_json_blob(match.group(1))

        def _add_found(campaign_id: str, status: str = "") -> None:
            cid = str(campaign_id or "").strip()
            if not CAMPAIGN_UUID_PATTERN.fullmatch(cid):
                return
            _merge_found({"id": cid, "status": _normalize_status(status)})

        patterns = (
            # Standard JSON blocks.
            r'"id"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})".{0,2000}?"status"\s*:\s*"(ACTIVE|UPCOMING)"',
            r'"status"\s*:\s*"(ACTIVE|UPCOMING)".{0,2000}?"id"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"',
            # Escaped JSON inside script payloads.
            r'\\"id\\"\s*:\s*\\"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\\".{0,2000}?\\"status\\"\s*:\s*\\"(ACTIVE|UPCOMING)\\"',
            r'\\"status\\"\s*:\s*\\"(ACTIVE|UPCOMING)\\".{0,2000}?\\"id\\"\s*:\s*\\"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\\"',
            # Alternative id key names used by some Twitch payloads.
            r'"(?:dropID|campaignId|dropCampaignId)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})".{0,2000}?"status"\s*:\s*"(ACTIVE|UPCOMING)"',
            r'\\"(?:dropID|campaignId|dropCampaignId)\\"\s*:\s*\\"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\\".{0,2000}?\\"status\\"\s*:\s*\\"(ACTIVE|UPCOMING)\\"',
        )
        for pattern in patterns:
            for match in re.finditer(pattern, page_html, flags=re.DOTALL):
                first, second = match.groups()
                if first in {"ACTIVE", "UPCOMING"}:
                    _add_found(second, first)
                else:
                    _add_found(first, second)

        # If Twitch changes payload shape, still extract candidate campaign IDs from
        # URL/query patterns and JSON keys, then let DropCampaignDetails validate them.
        id_only_patterns = (
            r'(?:dropID|campaignId|dropCampaignId)=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
            r'"(?:dropID|campaignId|dropCampaignId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"',
            r'\\"(?:dropID|campaignId|dropCampaignId|id)\\"\s*:\s*\\"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\\"',
        )
        for pattern in id_only_patterns:
            for match in re.finditer(pattern, page_html, flags=re.DOTALL):
                _add_found(match.group(1))

        # Last-resort scan: pair UUID-like IDs with nearby ACTIVE/UPCOMING markers.
        for match in re.finditer(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", page_html):
            campaign_id = match.group(0)
            start = max(0, match.start() - 400)
            end = min(len(page_html), match.end() + 400)
            context = page_html[start:end]
            status = ""
            if re.search(r"ACTIVE", context):
                status = "ACTIVE"
            elif re.search(r"UPCOMING", context):
                status = "UPCOMING"
            _add_found(campaign_id, status)

        with_status = sum(1 for item in found.values() if item.get("status") in {"ACTIVE", "UPCOMING"})
        if found:
            self._note(
                "Drops page fallback discovered "
                f"{len(found)} campaign ID(s) ({with_status} with ACTIVE/UPCOMING status)."
            )
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
        naive: datetime | None = None
        formats = (
            "%a, %b %d, %I:%M %p",
            "%A, %b %d, %I:%M %p",
            "%a, %b %d, %H:%M",
            "%A, %b %d, %H:%M",
        )
        for fmt in formats:
            try:
                naive = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if naive is None:
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
        lowered = "\n".join(lines).casefold()
        requires_subscription = (
            "subscribe to redeem" in lowered
            or "subscription required" in lowered
            or "subscriber only" in lowered
            or "subscribers only" in lowered
            or "subscrição necessária" in lowered
            or "subscricao necessaria" in lowered
            or "subscrição obrigatória" in lowered
            or "subscricao obrigatoria" in lowered
            or "subscrição para resgatar" in lowered
            or "subscricao para resgatar" in lowered
            or "apenas subs" in lowered
            or "apenas para subs" in lowered
            or "só para subs" in lowered
        )
        schedule = lines[-1]
        match = re.search(r"(.+?)\s+-\s+(.+?)\s+(GMT|UTC)([+-]\d+)?", schedule)
        if match is None:
            return None
        start_raw, end_raw, _tz_name, offset_raw = match.groups()
        utc_offset_hours = 0
        if offset_raw:
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
            requires_subscription=requires_subscription,
        )

    def _campaign_from_browser_row(
        self,
        *,
        campaign_id: str = "",
        title: str,
        schedule: str,
        requires_subscription: bool,
    ) -> DropCampaign | None:
        title_clean = str(title or "").strip()
        schedule_clean = re.sub(r"\s+", " ", str(schedule or "").strip())
        if not title_clean:
            return None

        now = datetime.now(timezone.utc)
        starts_at: datetime
        ends_at: datetime
        status: str

        match = re.search(r"(.+?)\s+-\s+(.+?)\s+(GMT|UTC)([+-]\d+)?", schedule_clean)
        if match is not None:
            start_raw, end_raw, _tz_name, offset_raw = match.groups()
            utc_offset_hours = 0
            if offset_raw:
                try:
                    utc_offset_hours = int(offset_raw)
                except ValueError:
                    return None

            starts_at = self._parse_browser_campaign_datetime(start_raw, utc_offset_hours)
            ends_at = self._parse_browser_campaign_datetime(end_raw, utc_offset_hours)
            if starts_at is None or ends_at is None or ends_at <= starts_at:
                return None

            if now >= ends_at:
                status = "EXPIRED"
            elif now < starts_at:
                status = "UPCOMING"
            else:
                status = "ACTIVE"
        else:
            # Some locales/layouts omit GMT/UTC schedules in card text.
            # Use a conservative synthetic active window so the campaign remains visible.
            starts_at = now - timedelta(hours=1)
            ends_at = now + timedelta(days=21)
            lowered = f"{title_clean}\n{schedule_clean}".casefold()
            if "ended" in lowered or "terminada" in lowered or "expirada" in lowered:
                status = "EXPIRED"
            elif "upcoming" in lowered or "starts" in lowered or "comeca" in lowered:
                status = "UPCOMING"
            else:
                status = "ACTIVE"

        if status == "EXPIRED":
            return None

        explicit_id = str(campaign_id or "").strip()
        if not CAMPAIGN_UUID_PATTERN.fullmatch(explicit_id):
            explicit_id = self._browser_campaign_id(title_clean, starts_at, ends_at)

        return DropCampaign(
            id=explicit_id,
            game_name=title_clean,
            title=title_clean,
            starts_at=starts_at,
            ends_at=ends_at,
            linked=True,
            link_url=f"{TWITCH_URL}/drops/campaigns",
            status=status,
            requires_subscription=bool(requires_subscription),
            timestamps_are_synthetic=(match is None),
            timestamp_source=("synthetic" if match is None else "campaign"),
        )

    def _campaigns_from_browser_body_text(self, body_text: str) -> list[DropCampaign]:
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        if not lines:
            return []

        start_markers = (
            "Open Drop Campaigns",
            "All Campaigns",
            "Drops & Rewards",
            "Campanhas",
            "Campanhas abertas",
            "Campanhas de drops abertas",
        )
        start_index = 0
        for marker in start_markers:
            if marker in lines:
                start_index = lines.index(marker) + 1
                break

        campaigns: list[DropCampaign] = []
        seen: set[str] = set()
        noise_prefixes = (
            "Some Drops campaigns may not be available",
            "To include Drops in your streams",
            "Learn more about Drops",
            "Use the Right Arrow Key",
            "Cookies and Advertising Choices",
            "Accept",
            "Customize",
            "Reject",
            "Skip to",
            "Alt",
        )
        stop_markers = {
            "Enable account linking",
            "Frequently Asked Questions",
            "Closed Drop Campaigns",
            "Back to top",
        }
        index = start_index
        while index < len(lines):
            title = lines[index]
            if title in stop_markers:
                break
            if title.startswith(noise_prefixes):
                index += 1
                continue

            schedule_index: int | None = None
            for candidate in range(index + 2, min(len(lines), index + 10)):
                schedule_line = lines[candidate]
                if " - " in schedule_line and ("GMT" in schedule_line or "UTC" in schedule_line):
                    schedule_index = candidate
                    break
                if schedule_line in stop_markers:
                    break
            if schedule_index is None:
                index += 1
                continue

            block_lines = lines[index : schedule_index + 1]
            if len(block_lines) < 3:
                index = schedule_index + 1
                continue

            campaign = self._campaign_from_browser_text("\n".join(block_lines))
            if campaign is None or campaign.status == "EXPIRED":
                index = schedule_index + 1
                continue

            fingerprint = f"{campaign.game_name}|{campaign.starts_at.isoformat()}|{campaign.ends_at.isoformat()}"
            if fingerprint in seen:
                index = schedule_index + 1
                continue
            seen.add(fingerprint)
            campaigns.append(campaign)
            index = schedule_index + 1
        return campaigns

    def _get_browser_profile(self, app: Any) -> Any:
        """Return the shared QWebEngineProfile used by every browser fallback
        path (GQL intercept, DOM scrape, drop claim), creating it once per app
        run instead of a fresh profile every single call.

        This is deliberately off-the-record (in-memory), NOT persisted to disk
        across app restarts: an on-disk named profile was tried in 2.2.34 and
        regressed to capturing zero campaigns after accumulating cookies/cache
        across many restarts over one test session -- plausibly stale/conflicting
        Twitch session state confusing its own JS. Reusing the same in-memory
        profile within a single run still avoids the "brand-new anonymous
        session every poll cycle" cost without that cross-restart staleness risk.
        It also carries the GQL-intercept script (see _GQL_INTERCEPT_JS), so any
        page loaded through it -- not just the drops dashboard -- can harvest a
        fresh Client-Integrity token."""
        if self._browser_profile is not None:
            return self._browser_profile

        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript

        profile = QWebEngineProfile(app)

        script = QWebEngineScript()
        script.setName("tdf_gql_intercept")
        script.setSourceCode(_GQL_INTERCEPT_JS)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        profile.scripts().insert(script)

        self._browser_profile = profile
        return profile

    def _campaigns_via_browser_gql_intercept(self, *, full_scan: bool = False) -> list[DropCampaign]:
        """Intercept the GQL calls the Twitch web app makes when it loads in QWebEngine.
        The web app generates integrity tokens client-side, so its GQL requests succeed
        where our direct Python requests are blocked.

        `full_scan=True` lifts the per-cycle detail-fetch cap so every campaign
        missing real per-drop data gets a detail-page visit, not just a handful.
        This is meant for an explicit, user-requested "scan the whole whitelist"
        action (slow -- can take minutes with 100+ campaigns), not the normal
        automatic poll cycle."""
        try:
            from PySide6.QtCore import QEventLoop, QTimer, QUrl
            from PySide6.QtNetwork import QNetworkCookie
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineCore import QWebEnginePage
            from shiboken6 import delete as shiboken_delete
        except Exception as exc:
            self._note(f"Browser GQL intercept unavailable: {exc}")
            return []

        app = QApplication.instance()
        owned_app = False
        if app is None:
            app = QApplication([])
            owned_app = True

        class SilentWebEnginePage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level: Any, message: str, line_number: int, source_id: str) -> None:
                return

        profile = self._get_browser_profile(app)
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

        for session_cookie in self.session.cookies:
            push_cookie(
                session_cookie.name,
                session_cookie.value,
                domain=session_cookie.domain or ".twitch.tv",
            )

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

        # The GQL-intercept script (window.fetch/XHR patching) is already
        # installed on the shared, persistent profile by _get_browser_profile().

        loop = QEventLoop()
        captured: dict[str, Any] = {"data": {}, "last_count": -1, "stable": 0}
        timed_out = {"value": False}
        poll_timer = QTimer()
        poll_timer.setInterval(1_500)
        poll_timer.setSingleShot(False)

        CLICK_TAB_JS = """(() => {
    var labels = ['All Campaigns', 'Todas as campanhas', 'Todas as Campanhas'];
    Array.from(document.querySelectorAll('a, button, [role="tab"]')).forEach(function(n) {
        var t = (n.innerText || n.textContent || '').trim();
        if (labels.indexOf(t) !== -1 && n.getAttribute('aria-selected') !== 'true') {
            n.click();
        }
    });
})();"""

        try:
            def finish() -> None:
                poll_timer.stop()
                if loop.isRunning():
                    loop.quit()

            def poll() -> None:
                page.runJavaScript(CLICK_TAB_JS)

                def on_data(raw: Any) -> None:
                    if not isinstance(raw, str):
                        return
                    try:
                        parsed = json.loads(raw)
                        if not isinstance(parsed, dict):
                            return
                        self._capture_integrity_from_retrieved(parsed)
                        items = parsed.get("campaigns")
                        if not isinstance(items, list):
                            return
                        for c in items:
                            cid = str(c.get("id", "") or "").strip() if isinstance(c, dict) else ""
                            if cid and CAMPAIGN_UUID_PATTERN.fullmatch(cid):
                                captured["data"][cid] = c
                        current = len(captured["data"])
                        if current == captured["last_count"]:
                            captured["stable"] += 1
                        else:
                            captured["stable"] = 0
                            captured["last_count"] = current
                        if current > 0 and captured["stable"] >= 5:
                            finish()
                        elif captured["stable"] >= 25:
                            finish()
                    except Exception:
                        pass

                page.runJavaScript(_RETRIEVE_GQL_STORE_JS, on_data)

            def on_loaded(ok: bool) -> None:
                if not ok:
                    self._note("Browser GQL intercept: page load failed.")
                    finish()
                    return
                poll_timer.start()

            def on_timeout() -> None:
                timed_out["value"] = True
                finish()

            timeout_timer = QTimer()
            timeout_timer.setSingleShot(True)
            timeout_timer.timeout.connect(on_timeout)
            poll_timer.timeout.connect(poll)
            page.loadFinished.connect(on_loaded)
            timeout_timer.start(55_000)
            page.load(QUrl(f"{TWITCH_URL}/drops/campaigns"))
            loop.exec()
            poll_timer.stop()
            timeout_timer.stop()
            page.loadFinished.disconnect(on_loaded)

            # Second phase: the listing page above only yields summary campaign
            # objects (no timeBasedDrops). Visit each active campaign's own detail
            # URL, still on the same invisible page/profile, so Twitch's own JS
            # fires a DropCampaignDetails GQL call that the intercept script above
            # also captures — giving real per-drop progress without ever showing
            # a window.
            detail_limit = len(captured["data"]) if full_scan else None
            detail_ids = self._select_browser_detail_candidate_ids(captured["data"], limit=detail_limit)
            if detail_ids:
                self._note(
                    f"Browser GQL intercept: a obter detalhe de {len(detail_ids)} "
                    "campanha(s) activa(s) sem timeBasedDrops"
                    + (" (scan completo)..." if full_scan else "...")
                )
                detail_hits = 0
                for campaign_id in detail_ids:
                    if self._fetch_browser_campaign_detail(page, campaign_id, captured["data"]):
                        detail_hits += 1
                self._note(
                    f"Browser GQL intercept: detalhe obtido para {detail_hits}/"
                    f"{len(detail_ids)} campanha(s)."
                )
        finally:
            # profile is shared/persistent (see _get_browser_profile) -- only the
            # page itself is per-call and gets torn down.
            shiboken_delete(page)
            if owned_app:
                app.quit()

        if timed_out["value"]:
            self._note("Browser GQL intercept timed out.")

        raw_payloads = list(captured["data"].values())
        if not raw_payloads:
            self._note("Browser GQL intercept: sem dados de campanhas capturados.")
            return []

        self._note(f"Browser GQL intercept capturou {len(raw_payloads)} payload(s) de campanha.")
        now = datetime.now(timezone.utc)
        campaigns: list[DropCampaign] = []
        seen: set[str] = set()
        for payload in raw_payloads:
            if not isinstance(payload, dict):
                continue
            campaign = self._parse_campaign(payload)
            if campaign is None or campaign.id in seen:
                continue
            if campaign.status == "EXPIRED" and campaign.ends_at <= now:
                continue
            seen.add(campaign.id)
            campaigns.append(campaign)

        if campaigns:
            campaigns.sort(key=lambda c: c.starts_at)
            campaigns.sort(key=lambda c: c.active, reverse=True)
            self._note(f"Browser GQL intercept extraiu {len(campaigns)} campanha(s) utilizáveis.")
        return campaigns

    # Upper bound on how many campaign detail pages the invisible browser will
    # visit per refresh cycle. Each visit is a real (headless) page navigation,
    # so this trades refresh speed for per-drop progress accuracy. Kept small
    # because a slow campaign refresh delays the streamless heartbeat that
    # actually accrues watch-time (observed: "Heartbeat streamless adiado").
    _BROWSER_DETAIL_FETCH_LIMIT = 8

    def set_priority_game(self, game_name: str) -> None:
        """Tell the client which game the UI currently wants real per-drop detail
        for (the selected or auto-picked farm target), so the limited per-cycle
        detail-fetch budget goes to it first instead of waiting its turn behind
        whatever else happens to end soonest."""
        self._priority_game_name = (game_name or "").strip().casefold()

    def _select_browser_detail_candidate_ids(
        self, captured: dict[str, Any], *, limit: int | None = None
    ) -> list[str]:
        """Pick which campaigns from the summary listing are worth an extra detail
        page visit: not expired, and missing real timeBasedDrops data. The game
        set via set_priority_game() goes first; the rest are ordered by soonest-
        ending so limited time is spent where it matters. `limit` overrides the
        usual per-cycle cap (pass a large number for an explicit full-whitelist
        scan); None keeps the default per-cycle budget."""
        effective_limit = self._BROWSER_DETAIL_FETCH_LIMIT if limit is None else limit
        now = datetime.now(timezone.utc)
        priority_ids: list[tuple[datetime, str]] = []
        other_ids: list[tuple[datetime, str]] = []
        for cid, payload in captured.items():
            if not isinstance(payload, dict):
                continue
            drops = payload.get("timeBasedDrops")
            if isinstance(drops, list) and drops:
                continue
            status = str(payload.get("status", "") or "").strip().upper()
            if status == "EXPIRED":
                continue
            end_raw = payload.get("endAt") or payload.get("endsAt")
            end_at = datetime.max.replace(tzinfo=timezone.utc)
            if end_raw:
                try:
                    end_at = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    end_at = datetime.max.replace(tzinfo=timezone.utc)
                else:
                    if end_at <= now:
                        continue
            game_obj = payload.get("game")
            game_name = str((game_obj or {}).get("name", "") or "").strip().casefold()
            bucket = priority_ids if (self._priority_game_name and game_name == self._priority_game_name) else other_ids
            bucket.append((end_at, cid))
        priority_ids.sort(key=lambda item: item[0])
        other_ids.sort(key=lambda item: item[0])
        ordered = priority_ids + other_ids
        return [cid for _end_at, cid in ordered[:effective_limit]]

    def _fetch_browser_campaign_detail(
        self,
        page: Any,
        campaign_id: str,
        captured: dict[str, Any],
    ) -> bool:
        """Navigate the already-open invisible page to a single campaign's detail
        URL so Twitch's own JS issues a DropCampaignDetails GQL call (captured by
        the intercept script installed on the profile). Merges any campaign
        payloads found into `captured`, preferring ones that carry timeBasedDrops.
        Returns True if real per-drop detail was captured for `campaign_id`."""
        from PySide6.QtCore import QEventLoop, QTimer, QUrl

        detail_loop = QEventLoop()
        got_detail = {"value": False}

        def finish() -> None:
            poll_timer.stop()
            if detail_loop.isRunning():
                detail_loop.quit()

        def merge(raw: Any) -> None:
            if not isinstance(raw, str):
                return
            try:
                parsed = json.loads(raw)
            except Exception:
                return
            if not isinstance(parsed, dict):
                return
            self._capture_integrity_from_retrieved(parsed)
            items = parsed.get("campaigns")
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("id", "") or "").strip()
                if not cid or not CAMPAIGN_UUID_PATTERN.fullmatch(cid):
                    continue
                existing = captured.get(cid)
                new_has_drops = bool(item.get("timeBasedDrops"))
                existing_has_drops = bool(isinstance(existing, dict) and existing.get("timeBasedDrops"))
                if new_has_drops or not existing_has_drops:
                    captured[cid] = item
                if cid == campaign_id and new_has_drops:
                    got_detail["value"] = True
            if got_detail["value"]:
                finish()

        def poll() -> None:
            page.runJavaScript(_RETRIEVE_GQL_STORE_JS, merge)

        def on_loaded(ok: bool) -> None:
            if not ok:
                finish()
                return
            poll_timer.start()

        poll_timer = QTimer()
        poll_timer.setInterval(1_200)
        poll_timer.setSingleShot(False)
        poll_timer.timeout.connect(poll)

        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(finish)

        page.loadFinished.connect(on_loaded)
        try:
            timeout_timer.start(6_000)
            page.load(QUrl(f"{TWITCH_URL}/drops/campaigns?dropID={campaign_id}"))
            detail_loop.exec()
        finally:
            poll_timer.stop()
            timeout_timer.stop()
            page.loadFinished.disconnect(on_loaded)

        return got_detail["value"]

    def _campaigns_from_browser_page(self, *, full_scan: bool = False) -> list[DropCampaign]:
        # Primary path: intercept the GQL calls the Twitch web app makes in QWebEngine.
        # The web app generates integrity tokens client-side, bypassing the integrity check.
        gql_campaigns = self._campaigns_via_browser_gql_intercept(full_scan=full_scan)
        if gql_campaigns:
            return gql_campaigns
        self._note("Browser GQL intercept sem resultados — a tentar análise de HTML renderizado.")

        try:
            from PySide6.QtCore import QEventLoop, QTimer, QUrl
            from PySide6.QtNetwork import QNetworkCookie
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineCore import QWebEnginePage
            from shiboken6 import delete as shiboken_delete
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

        profile = self._get_browser_profile(app)
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

        for session_cookie in self.session.cookies:
            push_cookie(
                session_cookie.name,
                session_cookie.value,
                domain=session_cookie.domain or ".twitch.tv",
            )

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
        payload: dict[str, Any] = {"raw": "", "best_len": 0, "rows": [], "best_row_count": 0, "best_uuid_hits": 0}
        timed_out = {"value": False}
        empty_rounds = {"value": 0}
        stable_rounds = {"value": 0}
        near_bottom_rounds = {"value": 0}
        finished = {"value": False}
        poll_timer = QTimer()
        poll_timer.setInterval(1_200)
        poll_timer.setSingleShot(False)

        try:
            def finish() -> None:
                # runJavaScript callbacks are async and can overlap poll_timer ticks
                # when the renderer is busy; without this guard every overlapping
                # callback that observes the same stop condition re-logs and re-quits.
                if finished["value"]:
                    return
                finished["value"] = True
                poll_timer.stop()
                if loop.isRunning():
                    loop.quit()

            def collect_cards() -> None:
                script = """
                    (() => {
                        const consentLabels = ["Accept", "Aceitar", "I agree", "Concordo"];
                        const buttons = Array.from(document.querySelectorAll("button"));
                        for (const button of buttons) {
                            const text = (button.innerText || button.textContent || "").trim();
                            if (consentLabels.includes(text)) {
                                button.click();
                                break;
                            }
                        }

                        const allCampaignLabels = [
                            "All Campaigns",
                            "Todas as campanhas",
                            "Todas as Campanhas",
                        ];
                        const tabCandidates = Array.from(document.querySelectorAll('a, button, [role="tab"]'));
                        for (const node of tabCandidates) {
                            const text = (node.innerText || node.textContent || "").trim();
                            if (!text) {
                                continue;
                            }
                            if (!allCampaignLabels.includes(text)) {
                                continue;
                            }
                            const selected = (node.getAttribute && node.getAttribute('aria-selected') === 'true');
                            if (!selected && typeof node.click === 'function') {
                                node.click();
                            }
                            break;
                        }

                        const explicitContainers = [
                            document.querySelector('[data-a-target="tw-core-scrollable-area"]'),
                            document.querySelector('[data-test-selector="drops-campaigns-page"]'),
                            document.querySelector('main[role="main"]'),
                            document.scrollingElement,
                            document.body,
                        ].filter(Boolean);
                        const dynamicContainers = Array.from(document.querySelectorAll('main, section, div')).filter((el) => {
                            try {
                                return el && el.scrollHeight > (el.clientHeight + 200);
                            } catch (_err) {
                                return false;
                            }
                        });
                        const containers = [...explicitContainers, ...dynamicContainers];
                        let scroller = document.scrollingElement || document.body;
                        let bestScore = -1;
                        for (const el of containers) {
                            const score = Number((el.scrollHeight || 0) - (el.clientHeight || 0));
                            if (score > bestScore) {
                                bestScore = score;
                                scroller = el;
                            }
                        }
                        if (scroller && typeof scroller.scrollBy === 'function') {
                            scroller.scrollBy(0, Math.max(500, Math.floor((scroller.clientHeight || window.innerHeight || 800) * 0.9)));
                        }

                        const bodyText = (document.body && document.body.innerText ? document.body.innerText : "").trim();

                        const rowMap = new Map();
                        const scheduleRegex = /(?:GMT|UTC)(?:[+-]\\d+)?/;
                        const uuidRegex = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;
                        const noised = new Set([
                            'Inventory',
                            'All Campaigns',
                            'Social Media Badge',
                            'Drops & Rewards',
                            'Open',
                            'Details',
                            'Expand',
                            'Collapse',
                        ]);
                        const scheduleNodes = Array.from(document.querySelectorAll('div, li, article, section, tr, p, span'));
                        for (const node of scheduleNodes) {
                            const scheduleText = (node.innerText || node.textContent || '').trim();
                            if (!scheduleText || scheduleText.length > 200) {
                                continue;
                            }
                            if (!scheduleRegex.test(scheduleText) || !scheduleText.includes(' - ')) {
                                continue;
                            }

                            let row = node;
                            for (let i = 0; i < 6 && row && row.parentElement; i += 1) {
                                const t = (row.innerText || '').trim();
                                if (t.includes(scheduleText) && t.length >= scheduleText.length + 4) {
                                    const lines = t.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
                                    if (lines.length >= 2) {
                                        break;
                                    }
                                }
                                row = row.parentElement;
                            }
                            if (!row) {
                                continue;
                            }

                            const rowText = (row.innerText || '').trim();
                            if (!rowText) {
                                continue;
                            }
                            const lines = rowText.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
                            if (!lines.length) {
                                continue;
                            }
                            let title = '';
                            for (const line of lines) {
                                if (line === scheduleText) {
                                    continue;
                                }
                                if (line.length > 120) {
                                    continue;
                                }
                                if (scheduleRegex.test(line)) {
                                    continue;
                                }
                                if (noised.has(line)) {
                                    continue;
                                }
                                title = line;
                                break;
                            }
                            if (!title) {
                                continue;
                            }

                            const lowered = rowText.toLowerCase();
                            const requiresSubscription = (
                                lowered.includes('subscribe to redeem') ||
                                lowered.includes('subscription required') ||
                                lowered.includes('subscriber only') ||
                                lowered.includes('subscribers only') ||
                                lowered.includes('subscrição necessária') ||
                                lowered.includes('subscricao necessaria') ||
                                lowered.includes('subscrição obrigatória') ||
                                lowered.includes('subscricao obrigatoria') ||
                                lowered.includes('subscrição para resgatar') ||
                                lowered.includes('subscricao para resgatar') ||
                                lowered.includes('apenas subs') ||
                                lowered.includes('apenas para subs') ||
                                lowered.includes('só para subs')
                            );

                            let campaignId = '';
                            try {
                                const hrefNode = row.querySelector('a[href*="drops/campaign"], a[href*="dropID"], a[href*="campaignId"]');
                                if (hrefNode && hrefNode.href) {
                                    const m = hrefNode.href.match(uuidRegex);
                                    if (m) {
                                        campaignId = m[0];
                                    }
                                }
                            } catch (_err) {}

                            const key = `${campaignId}|||${title}|||${scheduleText}`;
                            rowMap.set(key, {
                                campaign_id: campaignId,
                                title,
                                schedule: scheduleText,
                                requires_subscription: requiresSubscription,
                            });
                        }

                        // Secondary extraction for layouts without explicit GMT/UTC schedule lines.
                        const linkNodes = Array.from(document.querySelectorAll('a[href*="drops/campaign"], a[href*="dropID"], a[href*="campaignId"]'));
                        for (const link of linkNodes) {
                            const href = (link && link.href ? link.href : '').trim();
                            const match = href.match(uuidRegex);
                            if (!match) {
                                continue;
                            }
                            const campaignId = match[0];
                            let row = link;
                            for (let i = 0; i < 6 && row && row.parentElement; i += 1) {
                                const text = (row.innerText || row.textContent || '').trim();
                                if (text.length >= 8) {
                                    break;
                                }
                                row = row.parentElement;
                            }
                            if (!row) {
                                continue;
                            }
                            const rowText = (row.innerText || row.textContent || '').trim();
                            if (!rowText) {
                                continue;
                            }
                            const lines = rowText.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
                            if (!lines.length) {
                                continue;
                            }
                            let title = '';
                            let schedule = '';
                            for (const line of lines) {
                                if (!title && !noised.has(line) && line.length >= 2 && line.length <= 120 && !uuidRegex.test(line)) {
                                    title = line;
                                }
                                if (!schedule && scheduleRegex.test(line)) {
                                    schedule = line;
                                }
                            }
                            if (!title) {
                                continue;
                            }

                            const lowered = rowText.toLowerCase();
                            const requiresSubscription = (
                                lowered.includes('subscribe to redeem') ||
                                lowered.includes('subscription required') ||
                                lowered.includes('subscriber only') ||
                                lowered.includes('subscribers only') ||
                                lowered.includes('subscrição necessária') ||
                                lowered.includes('subscricao necessaria') ||
                                lowered.includes('subscrição obrigatória') ||
                                lowered.includes('subscricao obrigatoria') ||
                                lowered.includes('subscrição para resgatar') ||
                                lowered.includes('subscricao para resgatar') ||
                                lowered.includes('apenas subs') ||
                                lowered.includes('apenas para subs') ||
                                lowered.includes('só para subs')
                            );

                            const key = `${campaignId}|||${title}|||${schedule}`;
                            if (!rowMap.has(key)) {
                                rowMap.set(key, {
                                    campaign_id: campaignId,
                                    title,
                                    schedule,
                                    requires_subscription: requiresSubscription,
                                });
                            }
                        }

                        const cardSelectors = [
                            'article',
                            '[data-a-target="drops-campaign-card"]',
                            '[data-test-selector*="campaign"]',
                            '[class*="drops"] [class*="card"]',
                        ];
                        const cardTextParts = [];
                        for (const selector of cardSelectors) {
                            const nodes = Array.from(document.querySelectorAll(selector));
                            for (const node of nodes) {
                                const text = (node && node.innerText ? node.innerText : "").trim();
                                if (text) {
                                    cardTextParts.push(text);
                                }
                            }
                        }

                        return {
                            bodyText,
                            cardText: cardTextParts.join("\n\n"),
                            structuredRows: Array.from(rowMap.values()),
                            scheduleHits: (bodyText.match(/(?:GMT|UTC)(?:[+-]\\d+)?/g) || []).length,
                            uuidHits: (bodyText.match(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g) || []).length,
                            scrollTop: Number(scroller && scroller.scrollTop ? scroller.scrollTop : 0),
                            scrollHeight: Number(scroller && scroller.scrollHeight ? scroller.scrollHeight : 0),
                            clientHeight: Number(scroller && scroller.clientHeight ? scroller.clientHeight : 0),
                        };
                    })();
                """

                def on_result(raw: Any) -> None:
                    if finished["value"]:
                        # A previous overlapping runJavaScript call already stopped
                        # this poll; ignore any late callbacks still in flight.
                        return
                    if isinstance(raw, dict):
                        body_text = str(raw.get("bodyText", "") or "")
                        card_text = str(raw.get("cardText", "") or "")
                        rows_raw = raw.get("structuredRows") or []
                        text = (card_text + "\n" + body_text).strip()
                        schedule_hits = int(raw.get("scheduleHits", 0) or 0)
                        uuid_hits = int(raw.get("uuidHits", 0) or 0)
                        scroll_top = int(raw.get("scrollTop", 0) or 0)
                        scroll_height = int(raw.get("scrollHeight", 0) or 0)
                        client_height = int(raw.get("clientHeight", 0) or 0)
                        near_bottom = scroll_height > 0 and (scroll_top + client_height) >= (scroll_height - 120)
                    else:
                        rows_raw = []
                        text = raw if isinstance(raw, str) else ""
                        schedule_hits = 0
                        uuid_hits = 0
                        near_bottom = False

                    if isinstance(rows_raw, list):
                        normalized_rows: list[dict[str, Any]] = []
                        for item in rows_raw:
                            if not isinstance(item, dict):
                                continue
                            title = str(item.get("title", "") or "").strip()
                            schedule = str(item.get("schedule", "") or "").strip()
                            if not title:
                                continue
                            normalized_rows.append(
                                {
                                    "campaign_id": str(item.get("campaign_id", "") or "").strip(),
                                    "title": title,
                                    "schedule": schedule,
                                    "requires_subscription": bool(item.get("requires_subscription", False)),
                                }
                            )
                        if len(normalized_rows) > int(payload.get("best_row_count", 0) or 0):
                            payload["rows"] = normalized_rows
                            payload["best_row_count"] = len(normalized_rows)

                    has_campaign_like_schedule = bool(re.search(r"(?:GMT|UTC)(?:[+-]\\d+)?", text))
                    has_structured_rows = bool(isinstance(rows_raw, list) and len(rows_raw) > 0)
                    has_campaign_identifiers = uuid_hits > 0 or bool(re.search(r"drops?\s+campaign", text, flags=re.IGNORECASE))
                    text_len = len(text)

                    if text and (has_campaign_like_schedule or has_structured_rows or has_campaign_identifiers):
                        previous_best = int(payload.get("best_len", 0) or 0)
                        previous_hits = int(payload.get("best_hits", 0) or 0)
                        previous_uuid_hits = int(payload.get("best_uuid_hits", 0) or 0)
                        if text_len > previous_best:
                            payload["raw"] = text
                            payload["best_len"] = text_len
                            payload["best_hits"] = max(previous_hits, schedule_hits)
                            payload["best_uuid_hits"] = max(previous_uuid_hits, uuid_hits)
                            stable_rounds["value"] = 0
                        elif schedule_hits > previous_hits:
                            payload["raw"] = text
                            payload["best_len"] = text_len
                            payload["best_hits"] = schedule_hits
                            payload["best_uuid_hits"] = max(previous_uuid_hits, uuid_hits)
                            stable_rounds["value"] = 0
                        elif uuid_hits > previous_uuid_hits:
                            payload["raw"] = text
                            payload["best_len"] = text_len
                            payload["best_hits"] = max(previous_hits, schedule_hits)
                            payload["best_uuid_hits"] = uuid_hits
                            stable_rounds["value"] = 0
                        else:
                            stable_rounds["value"] += 1
                        empty_rounds["value"] = 0

                        if near_bottom:
                            near_bottom_rounds["value"] += 1
                        else:
                            near_bottom_rounds["value"] = 0

                        # Stop when content stopped growing and we've likely scanned the full page.
                        if stable_rounds["value"] >= 8 and near_bottom_rounds["value"] >= 4:
                            finish()
                        return

                    empty_rounds["value"] += 1
                    if empty_rounds["value"] >= 20:
                        self._note("Browser fallback stopped after repeated empty campaign extraction polls.")
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
            timeout.start(65_000)
            page.load(QUrl(f"{TWITCH_URL}/drops/campaigns"))
            loop.exec()

            poll_timer.stop()
            timeout.stop()
        finally:
            # profile is shared/persistent (see _get_browser_profile) -- only the
            # page itself is per-call and gets torn down.
            shiboken_delete(page)
            if owned_app:
                app.quit()

        if timed_out["value"]:
            self._note("Browser fallback timed out while loading the rendered Drops page.")
            return []

        raw_cards = payload["raw"]
        campaigns: list[DropCampaign] = []
        rows = payload.get("rows") or []
        if isinstance(rows, list) and rows:
            seen_fp: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                campaign = self._campaign_from_browser_row(
                    campaign_id=str(row.get("campaign_id", "") or "").strip(),
                    title=str(row.get("title", "") or ""),
                    schedule=str(row.get("schedule", "") or ""),
                    requires_subscription=bool(row.get("requires_subscription", False)),
                )
                if campaign is None:
                    continue
                fp = f"{campaign.title}|{campaign.starts_at.isoformat()}|{campaign.ends_at.isoformat()}"
                if fp in seen_fp:
                    continue
                seen_fp.add(fp)
                campaigns.append(campaign)

        if not campaigns:
            if not raw_cards:
                self._note("Browser fallback did not capture any rendered campaign cards.")
                return []
            campaigns = self._campaigns_from_browser_body_text(raw_cards)

        if campaigns:
            self._note(
                f"Browser fallback discovered {len(campaigns)} visible active/upcoming campaign(s)."
            )
        else:
            self._note("Browser fallback found the Drops page, but no usable campaign cards were parsed.")
        return campaigns

    def claim_available_drops(self) -> int:
        try:
            from PySide6.QtCore import QEventLoop, QTimer, QUrl
            from PySide6.QtNetwork import QNetworkCookie
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineCore import QWebEnginePage
            from shiboken6 import delete as shiboken_delete
        except Exception as exc:
            self._note(f"Drop claim is unavailable: {exc}")
            return 0

        app = QApplication.instance()
        owned_app = False
        if app is None:
            app = QApplication([])
            owned_app = True

        class SilentWebEnginePage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level: Any, message: str, line_number: int, source_id: str) -> None:
                return

        profile = self._get_browser_profile(app)
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

        for session_cookie in self.session.cookies:
            push_cookie(
                session_cookie.name,
                session_cookie.value,
                domain=session_cookie.domain or ".twitch.tv",
            )

        loop = QEventLoop()
        poll_timer = QTimer()
        poll_timer.setInterval(1_500)
        poll_timer.setSingleShot(False)
        timeout = QTimer()
        timeout.setSingleShot(True)

        state = {
            "clicked_total": 0,
            "empty_rounds": 0,
            "timed_out": False,
            "loaded": False,
        }

        def finish() -> None:
            if loop.isRunning():
                loop.quit()

        def scan_and_claim() -> None:
            script = """
                (() => {
                    const labels = ["claim", "redeem", "resgatar", "reivindicar", "collect"];
                    const buttons = Array.from(document.querySelectorAll("button"));
                    let clicked = 0;
                    for (const button of buttons) {
                        if (!button || button.disabled) {
                            continue;
                        }
                        const text = (button.innerText || button.textContent || "").trim().toLowerCase();
                        if (!text) {
                            continue;
                        }
                        if (!labels.some((label) => text.includes(label))) {
                            continue;
                        }
                        button.click();
                        clicked += 1;
                    }
                    return clicked;
                })();
            """

            def on_result(raw: Any) -> None:
                clicked = 0
                if isinstance(raw, int):
                    clicked = raw
                elif isinstance(raw, float):
                    clicked = int(raw)
                if clicked > 0:
                    state["clicked_total"] += clicked
                    state["empty_rounds"] = 0
                    return
                state["empty_rounds"] += 1
                if state["loaded"] and state["empty_rounds"] >= 3:
                    finish()

            page.runJavaScript(script, on_result)

        def on_loaded(ok: bool) -> None:
            state["loaded"] = True
            if not ok:
                self._note("Drop claim page failed to load.")
                finish()
                return
            scan_and_claim()
            poll_timer.start()

        def on_timeout() -> None:
            state["timed_out"] = True
            finish()

        page.loadFinished.connect(on_loaded)
        poll_timer.timeout.connect(scan_and_claim)
        timeout.timeout.connect(on_timeout)

        timeout.start(35_000)
        page.load(QUrl(f"{TWITCH_URL}/drops/inventory"))
        loop.exec()

        poll_timer.stop()
        timeout.stop()
        # profile is shared/persistent (see _get_browser_profile) -- only the
        # page itself is per-call and gets torn down.
        shiboken_delete(page)
        if owned_app:
            app.quit()

        if state["timed_out"]:
            self._note("Drop claim timed out while waiting for the inventory page.")

        clicked_total = int(state["clicked_total"])
        if clicked_total > 0:
            self._note(f"Claimed {clicked_total} drop reward button(s) from inventory page.")
        return clicked_total

    def _parse_campaign(self, data: dict[str, Any]) -> DropCampaign | None:
        raw_game = data.get("game")
        game: dict[str, Any]
        if isinstance(raw_game, dict):
            game = raw_game
        elif isinstance(raw_game, str):
            game = {"displayName": raw_game}
        else:
            game = {}

        game_name = (
            game.get("displayName")
            or game.get("name")
            or data.get("gameName")
            or data.get("name")
            or ""
        )
        if not isinstance(game_name, str) or not game_name.strip():
            return None
        game_name = game_name.strip()

        starts_at_raw = data.get("startAt") or data.get("startsAt")
        ends_at_raw = data.get("endAt") or data.get("endsAt")
        status = str(data.get("status", "") or "").strip().upper()
        now = datetime.now(timezone.utc)

        timestamp_source = ""
        timestamps_are_synthetic = False

        if starts_at_raw and ends_at_raw:
            timestamp_source = "campaign"
            starts_at = self._parse_timestamp(starts_at_raw)
            ends_at = self._parse_timestamp(ends_at_raw)
            if ends_at <= starts_at:
                self._note(
                    f"Skipping campaign '{data.get('name') or game_name}' due to invalid schedule "
                    f"({starts_at.isoformat()} -> {ends_at.isoformat()})."
                )
                return None
        else:
            # No campaign-level timestamps — look for drop-level endAt.
            drops_raw_ts = data.get("timeBasedDrops", []) or []
            drop_end_datetimes: list[datetime] = []
            for drop in drops_raw_ts:
                if isinstance(drop, dict) and drop.get("endAt"):
                    try:
                        drop_end_datetimes.append(
                            datetime.fromisoformat(str(drop["endAt"]).replace("Z", "+00:00"))
                        )
                    except (ValueError, TypeError):
                        pass
            if drop_end_datetimes:
                ends_at = max(drop_end_datetimes)
                starts_at = ends_at - timedelta(days=7)
                timestamp_source = "drop"
            else:
                # No timestamps anywhere — fabricate a safe window.
                starts_at = now - timedelta(hours=1)
                ends_at = now + timedelta(days=30)
                timestamp_source = "synthetic"
                timestamps_are_synthetic = True

        if ends_at <= now:
            status = "EXPIRED"

        drops = data.get("timeBasedDrops", []) or []
        if not drops:
            drops = self._extract_drop_like_entries(data)
        total_required, total_remaining = self._drop_totals(drops)
        next_drop_name, next_drop_remaining, next_drop_required = self._next_drop_info(drops)
        all_drops_claimed = self._all_drops_claimed(drops)
        requires_subscription = self._campaign_requires_subscription(data, drops)
        has_watchable_drops = self._compute_has_watchable_drops(drops)

        # Guard against stale per-drop progress: DropCampaignDetails may return
        # timeBasedDrops with currentMinutesWatched=0 while the Inventory query
        # stores the real campaign-level progress in data["self"]["currentMinutesWatched"].
        # This fires whenever inventory shows MORE progress than the per-drop computation
        # (not only when computed progress is exactly 0) to handle partial-stale scenarios.
        campaign_self = data.get("self") or {}
        if isinstance(campaign_self, dict) and total_required > 0:
            inv_current = int(campaign_self.get("currentMinutesWatched", 0) or 0)
            computed_progress = total_required - total_remaining
            if inv_current > computed_progress:
                total_remaining = max(0, total_required - inv_current)
                # Re-estimate next_drop_remaining: how much of inv_current applies to
                # drops before the current one (prev_required), then the rest is
                # progress already accumulated on the next drop.
                if next_drop_required > 0:
                    prev_required = total_required - next_drop_required
                    next_drop_progress = max(0, inv_current - prev_required)
                    next_drop_remaining = max(0, next_drop_required - next_drop_progress)

        # If no drops found in standard locations, try alternative extraction
        if total_required <= 0:
            total_required, total_remaining = self._extract_campaign_progress_data(data)
            if total_required > 0 and not next_drop_name:
                next_drop_name = str(data.get("name", "")).strip() or "Drop"
                next_drop_remaining = total_remaining
                next_drop_required = total_required

        # Inventory-backed campaigns can arrive with ambiguous/incorrect status values
        # when dashboard/detail queries are integrity-limited. If they still have
        # watch-time progress and are not expired by schedule, treat them as active.
        if status in {"", "INACTIVE"} and ends_at > now:
            inv_self = data.get("self") or {}
            inv_minutes = int(inv_self.get("currentMinutesWatched", 0) or 0) if isinstance(inv_self, dict) else 0
            if total_required > 0 or inv_minutes > 0:
                status = "ACTIVE"
        # Some campaign payloads omit/lag per-drop claim flags while total remaining is already 0.
        if not all_drops_claimed and total_required > 0 and total_remaining <= 0:
            all_drops_claimed = True
        if not all_drops_claimed and self._campaign_claimed_from_payload(data):
            all_drops_claimed = True
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
            game_name=game_name,
            game_slug=game.get("slug", ""),
            game_box_art_url=self._game_box_art_url(game),
            title=(data.get("name") or game_name or "Campaign"),
            starts_at=starts_at,
            ends_at=ends_at,
            progress_minutes=max(0, total_required - total_remaining),
            required_minutes=total_required,
            linked=bool((data.get("self") or {}).get("isAccountConnected", True)),
            link_url=data.get("accountLinkURL", "") or "",
            status=status,
            allowed_channels=allowed_channels,
            has_badge_or_emote=self._campaign_has_badge_or_emote(drops),
            all_drops_claimed=all_drops_claimed,
            requires_subscription=requires_subscription,
            has_watchable_drops=has_watchable_drops,
            next_drop_name=next_drop_name,
            next_drop_remaining_minutes=next_drop_remaining,
            next_drop_required_minutes=next_drop_required,
            drops=self._drop_progress_items(drops),
            timestamps_are_synthetic=timestamps_are_synthetic,
            timestamp_source=timestamp_source,
        )
        return campaign

    def fetch_inventory_progress(self) -> dict[str, DropCampaign]:
        """Fetch only in-progress inventory campaigns for fast progress reconciliation."""
        progress_by_campaign: dict[str, DropCampaign] = {}
        if not self.login_state.oauth_token:
            self._note("Inventory progress refresh skipped: sem auth-token.")
            return progress_by_campaign

        try:
            inventory_response = self._post_gql(INVENTORY_QUERY, client_profile="android")
        except requests.RequestException as exc:
            self._note(f"Inventory progress refresh failed: {exc}")
            return progress_by_campaign

        current_user = (inventory_response.get("data") or {}).get("currentUser")
        if current_user is None:
            self._note("Inventory progress refresh returned currentUser=null.")
            return progress_by_campaign

        inventory = current_user.get("inventory", {}) or {}
        ongoing_campaigns = inventory.get("dropCampaignsInProgress", []) or []
        for payload in ongoing_campaigns:
            if not isinstance(payload, dict):
                continue
            campaign = self._parse_campaign(payload)
            if campaign is None or not campaign.id:
                continue
            progress_by_campaign[campaign.id] = campaign

        self._note(
            f"Inventory progress refresh: {len(progress_by_campaign)} campanha(s) em progresso."
        )
        return progress_by_campaign

    @staticmethod
    def _campaign_cache_keep(campaign: DropCampaign, now: datetime) -> bool:
        """The single retention rule shared by the in-memory prune and the on-disk
        load: keep active/future, recently-claimed, or partly-progressed campaigns."""
        return (
            (campaign.ends_at > now and campaign.status != "EXPIRED")
            or (campaign.all_drops_claimed and campaign.ends_at > now - timedelta(days=30))
            or (campaign.remaining_minutes > 0 and campaign.ends_at > now - timedelta(days=7))
        )

    def _campaign_to_jsonable(self, campaign: DropCampaign) -> dict[str, Any]:
        data = asdict(campaign)
        # datetimes are not JSON-serializable; store as ISO strings.
        data["starts_at"] = campaign.starts_at.isoformat()
        data["ends_at"] = campaign.ends_at.isoformat()
        return data

    def _campaign_from_jsonable(self, data: dict[str, Any]) -> DropCampaign | None:
        try:
            known = {f.name for f in fields(DropCampaign)}
            kwargs = {k: v for k, v in data.items() if k in known}
            kwargs["starts_at"] = datetime.fromisoformat(str(kwargs["starts_at"]))
            kwargs["ends_at"] = datetime.fromisoformat(str(kwargs["ends_at"]))
            return DropCampaign(**kwargs)
        except Exception:
            return None

    def _load_campaign_cache(self) -> None:
        """Populate _campaign_cache from disk on startup (best-effort). Expired
        entries are dropped using the same rule as the in-memory prune."""
        try:
            if not CAMPAIGN_CACHE_FILE.exists():
                return
            raw = json.loads(CAMPAIGN_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, list):
            return
        now = datetime.now(timezone.utc)
        loaded = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            campaign = self._campaign_from_jsonable(item)
            if campaign is None or not campaign.id:
                continue
            if not self._campaign_cache_keep(campaign, now):
                continue
            self._campaign_cache[campaign.id] = campaign
            loaded += 1
        if loaded:
            self._note(f"Cache de campanhas: {loaded} campanha(s) carregadas do disco.")

    def _save_campaign_cache(self, campaigns: list[DropCampaign]) -> None:
        """Persist the current cache to disk atomically (best-effort; a failure
        here must never break a poll)."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            payload = [self._campaign_to_jsonable(c) for c in campaigns]
            tmp = CAMPAIGN_CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, CAMPAIGN_CACHE_FILE)
        except Exception:
            pass

    def cached_campaigns(self) -> list[DropCampaign]:
        """Return copies of the currently-cached campaigns (loaded from disk on
        startup and merged from every poll). Lets the UI populate the filter/
        dashboard game lists immediately, before the first poll has run."""
        with self._campaign_cache_lock:
            return [dataclass_replace(c) for c in self._campaign_cache.values()]

    def _merge_campaign_cache(self, campaigns: list[DropCampaign]) -> list[DropCampaign]:
        """Merge a fetch_campaigns() result into the running per-client campaign
        cache (see self._campaign_cache) and return the full merged view, pruning
        entries that are now clearly expired. Reuses the same keep-window rules
        as the in-call expiry filter above."""
        now = datetime.now(timezone.utc)
        with self._campaign_cache_lock:
            for campaign in campaigns:
                if campaign.id:
                    self._campaign_cache[campaign.id] = campaign
            stale_ids = [
                cid
                for cid, cached in self._campaign_cache.items()
                if not self._campaign_cache_keep(cached, now)
            ]
            for cid in stale_ids:
                del self._campaign_cache[cid]
            # Snapshot references under the lock; we never mutate cached objects in
            # place (callers get copies), so serialising them after releasing the
            # lock is safe and keeps lock time minimal.
            snapshot = list(self._campaign_cache.values())
            # Return copies, not the cached objects themselves: callers (farmer.py)
            # mutate campaign fields in place while deciding, and fetch_campaigns()
            # can be invoked concurrently from both the background poll thread and
            # the main-thread on-demand retry — sharing live objects across those
            # would let one caller's in-progress mutation bleed into another's.
            merged = [dataclass_replace(cached) for cached in snapshot]
        self._save_campaign_cache(snapshot)
        merged.sort(key=lambda item: item.starts_at)
        merged.sort(key=lambda item: item.active, reverse=True)
        return merged

    def fetch_campaigns(
        self, *, allow_browser_fallback: bool = True, full_scan: bool = False
    ) -> list[DropCampaign]:
        """`full_scan=True` is for an explicit, user-requested deep refresh (the
        dashboard "Actualizar dashboard" button): it lifts the browser fallback's
        per-cycle detail-fetch cap so every whitelisted campaign missing real
        per-drop data gets a detail-page visit, not just a handful. Implies
        allow_browser_fallback (a full scan without it would do nothing extra)."""
        self._diagnostics.clear()
        if full_scan:
            allow_browser_fallback = True
        if allow_browser_fallback and threading.current_thread() is not threading.main_thread():
            # QWebEngine fallback must stay on Qt/main thread; worker-thread usage can crash the app.
            allow_browser_fallback = False
            full_scan = False
            self._note("Browser fallback ignorado fora do thread principal (segurança de estabilidade).")
        if not self.login_state.oauth_token:
            self._note("No auth-token cookie value saved yet.")
            return []

        try:
            self.validate_oauth_token()
        except ValueError as exc:
            self._note(str(exc))
            return []
        except requests.RequestException as exc:
            self._note(f"OAuth validation request failed: {exc}")
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
        try:
            attempted_response = self._post_gql(CAMPAIGNS_QUERY, client_profile="android")
            if isinstance(attempted_response, dict):
                campaigns_response = attempted_response
        except requests.RequestException as exc:
            self._note(f"ViewerDropsDashboard query failed: {exc}")
        dashboard_errors = self._graphql_error_messages(campaigns_response)
        dashboard_integrity_blocked = any(
            "failed integrity check" in message.casefold()
            for message in dashboard_errors
        )
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
        weak_listing = False
        minimum_expected = max(6, len(inventory_data))
        fallback_campaigns = self._campaigns_from_drops_page()
        if dashboard_integrity_blocked:
            self._note(
                "ViewerDropsDashboard bloqueado por integrity check. A usar IDs da página de drops e inventário (sem cache)."
            )
        if available_campaigns and len(available_campaigns) <= minimum_expected:
            self._note(
                "ViewerDropsDashboard returned a small campaign list. "
                "Enriching with drops page fallback IDs."
            )
        if fallback_campaigns:
            missing_fallback_ids = set(fallback_campaigns) - set(available_campaigns)
            if missing_fallback_ids:
                weak_listing = True
                self._note(
                    "Drops page fallback found additional active/upcoming campaign IDs "
                    "not present in ViewerDropsDashboard."
                )
            available_campaigns = {
                **fallback_campaigns,
                **available_campaigns,
            }
        if available_campaigns:
            self._note("ViewerDropsDashboard returned campaigns.")
        if not available_campaigns:
            weak_listing = True
        self._note(f"Dashboard returned {len(available_campaigns)} active/upcoming campaign(s).")

        # Build a broader detail-ID set when dashboard listing is integrity-limited.
        # This avoids being stuck with only in-progress inventory campaigns.
        detail_id_candidates: set[str] = set(available_campaigns)
        detail_id_candidates.update(inventory_data)
        detail_id_candidates = {
            cid for cid in detail_id_candidates if CAMPAIGN_UUID_PATTERN.fullmatch(str(cid or "").strip())
        }
        if (dashboard_integrity_blocked or not available_campaigns) and detail_id_candidates:
            self._note(
                "Integrity-limited listing: expanding DropCampaignDetails IDs with "
                f"inventory/drops-page hints ({len(detail_id_candidates)} candidate IDs)."
            )

        detailed_campaigns: dict[str, dict[str, Any]] = {}
        identity_candidates = [
            candidate
            for candidate in (self.login_state.user_id, self.login_state.login_name)
            if candidate
        ]
        # ViewerDropsDashboard just told us the integrity check is blocked this
        # cycle -- DropCampaignDetails sits behind the same protection, so retrying
        # it (up to 2 identities x 2 header-profile retries x chunk) is guaranteed
        # waste unless we have a harvested token that might succeed where the
        # dashboard call didn't (e.g. it was captured moments after that request).
        if dashboard_integrity_blocked and not self._current_integrity_token():
            self._note(
                "A saltar DropCampaignDetails: ViewerDropsDashboard já confirmou "
                "a integrity check bloqueada neste ciclo e não há token de "
                "integridade capturado para tentar."
            )
        else:
            for identity in identity_candidates:
                details_payload: list[dict[str, Any]] = []
                for campaign_id in detail_id_candidates:
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
                        else:
                            # Try alternative path for campaign details
                            alt_data = response.get("data", {}).get("dropCampaign")
                            if alt_data and alt_data.get("id"):
                                attempted_details[alt_data["id"]] = alt_data
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
            # Inventory is the authoritative source for user watch-time progress.
            # Re-apply it after structural merging to prevent stale progress in the UI.
            if campaign_id in inventory_data:
                inv = inventory_data[campaign_id]
                inv_drops = inv.get("timeBasedDrops") or []
                if inv_drops:
                    # Use inventory drops directly so progress/claim state always matches Twitch.
                    merged = {**merged, "timeBasedDrops": list(inv_drops)}

                inv_self = inv.get("self")
                if isinstance(inv_self, dict):
                    current_self = merged.get("self") or {}
                    if not isinstance(current_self, dict):
                        current_self = {}
                    # Keep inventory campaign-level minutes authoritative as well.
                    merged = {**merged, "self": {**current_self, **inv_self}}
            merged_campaigns[campaign_id] = merged

        campaigns: list[DropCampaign] = []
        for payload in merged_campaigns.values():
            campaign = self._parse_campaign(payload)
            if campaign is not None:
                campaigns.append(campaign)
                if campaign.required_minutes == 0 and campaign.progress_minutes == 0:
                    self._note(f"Campaign '{campaign.title}' has no progress data (0/0 min)")

        now = datetime.now(timezone.utc)
        recent_expired_window = timedelta(days=7)
        before_time_filter = len(campaigns)
        campaigns = [
            campaign
            for campaign in campaigns
            if (
                (campaign.ends_at > now and campaign.status != "EXPIRED")
                or (
                    campaign.all_drops_claimed
                    and campaign.ends_at > now - timedelta(days=30)
                )
                or (
                    campaign.remaining_minutes > 0
                    and campaign.ends_at > now - recent_expired_window
                )
            )
        ]
        if len(campaigns) != before_time_filter:
            self._note(
                f"Dropped {before_time_filter - len(campaigns)} expired campaign(s) from the parsed list."
            )

        campaigns.sort(key=lambda item: item.starts_at)
        campaigns.sort(key=lambda item: item.active, reverse=True)
        listing_too_small = len(campaigns) < max(minimum_expected, len(fallback_campaigns))
        should_try_browser_fallback = weak_listing or listing_too_small
        if dashboard_integrity_blocked and campaigns:
            # When integrity checks block dashboard listing, we often only see in-progress inventory campaigns.
            inventory_only_snapshot = bool(inventory_data) and len(campaigns) <= len(inventory_data)
            if not available_campaigns and inventory_only_snapshot:
                should_try_browser_fallback = True

        if campaigns and (should_try_browser_fallback or full_scan) and allow_browser_fallback:
            if full_scan:
                self._note("Scan completo pedido pelo utilizador: a obter detalhe de toda a whitelist...")
            elif dashboard_integrity_blocked:
                self._note(
                    "Campaign listing is integrity-limited. Trying rendered browser fallback for extra campaigns."
                )
            else:
                self._note(
                    "Campaign listing appears incomplete. Trying rendered browser fallback for the full list."
                )
            browser_campaigns = self._campaigns_from_browser_page(full_scan=full_scan)
            if browser_campaigns:
                # Merge only by campaign ID to avoid mixing drop progress across
                # different campaigns that happen to share the same game name.
                merged_by_id = {campaign.id: campaign for campaign in campaigns}
                
                for browser_campaign in browser_campaigns:
                    # Try exact ID match first
                    if browser_campaign.id in merged_by_id:
                        existing = merged_by_id[browser_campaign.id]
                        # Use browser campaign for better schedule/details, but keep progress from existing
                        browser_campaign.progress_minutes = existing.progress_minutes
                        browser_campaign.required_minutes = existing.required_minutes
                        browser_campaign.drops = list(existing.drops)
                        browser_campaign.next_drop_name = existing.next_drop_name
                        browser_campaign.next_drop_remaining_minutes = existing.next_drop_remaining_minutes
                        browser_campaign.next_drop_required_minutes = existing.next_drop_required_minutes
                        browser_campaign.all_drops_claimed = existing.all_drops_claimed
                        browser_campaign.requires_subscription = (
                            browser_campaign.requires_subscription or existing.requires_subscription
                        )
                        merged_by_id[browser_campaign.id] = browser_campaign
                    else:
                        # New campaign from browser
                        merged_by_id[browser_campaign.id] = browser_campaign
                
                campaigns = list(merged_by_id.values())
                campaigns.sort(key=lambda item: item.starts_at)
                campaigns.sort(key=lambda item: item.active, reverse=True)
                weak_listing = False
        elif campaigns and should_try_browser_fallback and not allow_browser_fallback:
            self._note("Browser fallback disabled for this campaign fetch call.")
        if not campaigns:
            if inventory_data or dashboard_integrity_blocked:
                self._note("ViewerDropsDashboard is empty or integrity-protected. Skipping browser fallback.")
            elif allow_browser_fallback:
                self._note("ViewerDropsDashboard is empty or integrity-protected. Trying browser fallback.")
                campaigns = self._campaigns_from_browser_page(full_scan=full_scan)
                campaigns.sort(key=lambda item: item.starts_at)
                campaigns.sort(key=lambda item: item.active, reverse=True)
                if campaigns:
                    weak_listing = False
            else:
                self._note("ViewerDropsDashboard is empty or integrity-protected, and browser fallback is disabled.")
        self._note(
            f"Parsed {len(campaigns)} campaign(s), {sum(campaign.eligible for campaign in campaigns)} eligible for farming."
        )
        if not campaigns:
            self._note("No campaigns were available for this account at the moment.")
        merged_campaigns = self._merge_campaign_cache(campaigns)
        if len(merged_campaigns) > len(campaigns):
            self._note(
                f"Combined with {len(merged_campaigns) - len(campaigns)} campaign(s) known from earlier fetches."
            )
        return merged_campaigns

    def resolve_game_slug(self, game_name: str) -> str:
        cached = self._slug_cache.get(game_name.casefold())
        if cached is not None:
            return cached

        payload = self._clone_query(GAME_REDIRECT_QUERY)
        payload["variables"]["name"] = game_name
        response = self._post_gql(payload)
        slug = ((response.get("data") or {}).get("game") or {}).get("slug", "") or ""
        self._slug_cache[game_name.casefold()] = slug
        if not slug:
            self._note(f"Could not resolve a Twitch directory slug for {game_name}.")
        return slug

    def resolve_game_box_art_url(self, game_name: str, *, game_slug: str = "") -> str:
        cache_key = game_name.casefold()
        cached = self._game_box_art_cache.get(cache_key)
        if cached is not None:
            return cached

        slug = (game_slug or "").strip() or self.resolve_game_slug(game_name)
        if slug:
            try:
                payload = self._clone_query(GAME_DIRECTORY_QUERY)
                payload["variables"]["slug"] = slug
                payload["variables"]["limit"] = 1
                response = self._post_gql(payload)
                game = (response.get("data") or {}).get("game") or {}
                art_url = self._game_box_art_url(game)
                if art_url:
                    self._game_box_art_cache[cache_key] = art_url
                    return art_url
            except requests.RequestException as exc:
                self._note(f"DirectoryPage_Game failed while resolving box art for {game_name}: {exc}")

        try:
            payload = self._clone_query(GAME_REDIRECT_QUERY)
            payload["variables"]["name"] = game_name
            response = self._post_gql(payload)
            game = (response.get("data") or {}).get("game") or {}
            art_url = self._game_box_art_url(game)
            if art_url:
                self._game_box_art_cache[cache_key] = art_url
                return art_url
        except requests.RequestException as exc:
            self._note(f"DirectoryGameRedirect failed while resolving box art for {game_name}: {exc}")

        directory_art = self._resolve_twitch_directory_box_art_url(game_name, slug=slug)
        if directory_art:
            self._game_box_art_cache[cache_key] = directory_art
            return directory_art

        external_url = self._resolve_external_game_box_art_url(game_name)
        if external_url:
            self._game_box_art_cache[cache_key] = external_url
            return external_url

        # Do NOT cache failures — allow retry on the next call
        return ""

    def _resolve_external_game_box_art_url(self, game_name: str) -> str:
        cache_key = game_name.casefold()
        cached = self._external_box_art_cache.get(cache_key)
        if cached is not None:
            return cached

        api_url = "https://store.steampowered.com/api/storesearch/"
        try:
            response = self.session.get(
                api_url,
                params={"term": game_name, "l": "english", "cc": "us"},
                headers={"User-Agent": WEB_USER_AGENT},
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            self._note(f"Steam store search failed while resolving box art for {game_name}: {exc}")
            fallback = self._resolve_google_game_box_art_url(game_name)
            if fallback:
                self._external_box_art_cache[cache_key] = fallback
            return fallback

        items = payload.get("items", []) or []
        normalized = game_name.casefold().strip()

        best_item: dict[str, Any] | None = None
        for item in items:
            name = str(item.get("name", "") or "").casefold().strip()
            if name and name == normalized:
                best_item = item
                break
        if best_item is None and items:
            best_item = items[0]
        if best_item is None:
            fallback = self._resolve_google_game_box_art_url(game_name)
            if fallback:
                self._external_box_art_cache[cache_key] = fallback
            return fallback

        app_id = str(best_item.get("id", "") or "").strip()
        if app_id:
            library_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900_2x.jpg"
            # Verify the library image actually exists before storing the URL
            try:
                head = self.session.head(
                    library_url,
                    headers={"User-Agent": WEB_USER_AGENT},
                    timeout=6,
                    allow_redirects=True,
                )
                if head.status_code == 200:
                    self._external_box_art_cache[cache_key] = library_url
                    return library_url
            except requests.RequestException:
                pass

        tiny_image = str(best_item.get("tiny_image", "") or "").strip()
        if tiny_image:
            self._external_box_art_cache[cache_key] = tiny_image
            return tiny_image

        duckduckgo = self._resolve_duckduckgo_game_box_art_url(game_name)
        if duckduckgo:
            self._external_box_art_cache[cache_key] = duckduckgo
            return duckduckgo

        fallback = self._resolve_google_game_box_art_url(game_name)
        if fallback:
            self._external_box_art_cache[cache_key] = fallback
        return fallback

    def _resolve_twitch_directory_box_art_url(self, game_name: str, *, slug: str = "") -> str:
        final_slug = (slug or "").strip() or self.resolve_game_slug(game_name)
        if not final_slug:
            return ""
        try:
            response = self.session.get(
                f"{TWITCH_URL}/directory/category/{quote(final_slug, safe='')}",
                headers={"User-Agent": WEB_USER_AGENT},
                timeout=12,
            )
            response.raise_for_status()
            html = response.text
        except requests.RequestException:
            return ""

        patterns = [
            r'<meta\s+property="og:image"\s+content="(https://[^"]+)"',
            r'<meta\s+content="(https://[^"]+)"\s+property="og:image"',
            r'"boxArtURL"\s*:\s*"(https?://[^"\\]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match is None:
                continue
            candidate = match.group(1).replace("\\/", "/").strip()
            if candidate:
                return candidate
        return ""

    def _resolve_duckduckgo_game_box_art_url(self, game_name: str) -> str:
        query = f"{game_name} game cover art"
        headers = {
            "User-Agent": WEB_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            page_response = self.session.get(
                "https://duckduckgo.com/",
                params={"q": query, "iax": "images", "ia": "images"},
                headers=headers,
                timeout=12,
            )
            page_response.raise_for_status()
            html = page_response.text
            match = re.search(r"vqd='([^']+)'", html)
            if match is None:
                match = re.search(r'vqd="([^"]+)"', html)
            if match is None:
                return ""
            vqd = match.group(1)

            api_response = self.session.get(
                "https://duckduckgo.com/i.js",
                params={
                    "l": "us-en",
                    "o": "json",
                    "q": query,
                    "vqd": vqd,
                    "f": ",,,",
                    "p": "1",
                },
                headers=headers,
                timeout=12,
            )
            api_response.raise_for_status()
            payload = api_response.json()
        except (requests.RequestException, ValueError):
            return ""

        for item in payload.get("results", []) or []:
            image_url = str(item.get("image", "") or "").strip()
            if not image_url:
                continue
            if not image_url.startswith("http"):
                continue
            return image_url
        return ""

    def _resolve_google_game_box_art_url(self, game_name: str) -> str:
        query = f"{game_name} game cover art"
        try:
            response = self.session.get(
                "https://www.google.com/search",
                params={"tbm": "isch", "hl": "en", "q": query},
                headers={
                    "User-Agent": WEB_USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=12,
            )
            response.raise_for_status()
            html = response.text
        except requests.RequestException as exc:
            self._note(f"Google image search failed while resolving box art for {game_name}: {exc}")
            return ""

        patterns = [
            r'"ou":"(https://[^"\\]+(?:jpg|jpeg|png|webp))"',
            r'"(https://[^"\\]+(?:jpg|jpeg|png|webp))"',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, html, flags=re.IGNORECASE):
                candidate = match.group(1)
                candidate = candidate.replace("\\/", "/").replace("\\u003d", "=").strip()
                if not candidate:
                    continue
                if "gstatic.com/images/branding" in candidate:
                    continue
                return candidate
        self._note(f"Google image search did not return a usable box art URL for {game_name}.")
        return ""

    def _fetch_streams_for_slug(
        self, campaign: DropCampaign, slug: str
    ) -> list[StreamCandidate]:
        """Query the game directory for live drops-enabled streams using a resolved slug."""
        payload = self._clone_query(GAME_DIRECTORY_QUERY)
        payload["variables"]["slug"] = slug
        response = self._post_gql(payload)
        # response["data"] can be None (e.g. PersistedQueryNotFound returns data:null)
        # Use `or {}` instead of `.get("data", {})` to guard against the None case.
        game_data = (response.get("data") or {}).get("game") or {}
        if not game_data:
            errors = self._graphql_error_messages(response)
            if errors:
                self._note(
                    f"DirectoryPage_Game returned no data for {campaign.game_name} "
                    f"(slug={slug!r}): {errors[0]}"
                )
            else:
                self._note(
                    f"DirectoryPage_Game returned empty game data for {campaign.game_name} "
                    f"(slug={slug!r}). Slug may be wrong."
                )
        edges = (game_data.get("streams") or {}).get("edges") or []
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
                    channel_id=str(broadcaster.get("id", "") or ""),
                    broadcast_id=str(node.get("id", "") or ""),
                )
            )
        self._note(f"Found {len(output)} drops-enabled stream(s) for {campaign.game_name}.")
        return output

    def _fetch_streams_from_allowed_channels(
        self, campaign: DropCampaign
    ) -> list[StreamCandidate]:
        """Query each allowed channel directly and return only the live ones."""
        output: list[StreamCandidate] = []
        for login in campaign.allowed_channels:
            try:
                info = self._stream_info(login)
            except Exception as exc:
                self._note(f"_stream_info failed for allowed channel {login!r}: {exc}")
                continue
            broadcast_id = info.get("broadcast_id", "")
            if not broadcast_id:
                # Channel is offline or not streaming
                continue
            channel_id = info.get("channel_id", "")
            output.append(
                StreamCandidate(
                    login=login,
                    display_name=login,
                    game_name=campaign.game_name,
                    viewer_count=0,
                    drops_enabled=True,
                    channel_id=channel_id,
                    broadcast_id=broadcast_id,
                )
            )
        self._note(
            f"Found {len(output)} live allowed channel(s) for {campaign.game_name}."
        )
        return output

    def fetch_streams(self, campaign: DropCampaign) -> list[StreamCandidate]:
        slug = campaign.game_slug or self.resolve_game_slug(campaign.game_name)

        if slug and slug.casefold() in SPECIAL_GAME_SLUGS:
            self._note(
                f"Campanha '{campaign.title}' é de jogo especial ({campaign.game_name}) — "
                "drops ganhos em qualquer stream com drops activos."
            )

        if not slug:
            # No slug: can only check allowed channels individually.
            if campaign.allowed_channels:
                return self._fetch_streams_from_allowed_channels(campaign)
            return []

        # Always query the game directory first (one API call, top streams by viewers).
        directory_streams = self._fetch_streams_for_slug(campaign, slug)

        if not campaign.allowed_channels:
            # No channel restriction — any drops-enabled stream is valid.
            return directory_streams

        # Campaign restricts which channels grant drops: filter the directory results.
        allowed_set = {login.casefold() for login in campaign.allowed_channels}
        filtered = [s for s in directory_streams if s.login.casefold() in allowed_set]
        if filtered:
            return filtered

        # None of the top directory streams are in the allowed list.
        # Fall back to checking each allowed channel individually.
        self._note(
            f"No allowed channels in top directory streams for {campaign.game_name}; "
            f"checking {len(campaign.allowed_channels)} allowed channel(s) directly."
        )
        return self._fetch_streams_from_allowed_channels(campaign)


if __name__ == "__main__":
    _root = Path(__file__).resolve().parents[2]
    _launcher = _root / "TwitchDropFarmer.pyw"
    _pythonw = Path(sys.executable).with_name("pythonw.exe")
    if sys.platform == "win32" and _launcher.exists() and _pythonw.exists():
        subprocess.Popen([str(_pythonw), str(_launcher)], cwd=str(_root))
        raise SystemExit(0)

    if str(_root / "src") not in sys.path:
        sys.path.insert(0, str(_root / "src"))
    from twitch_drop_farmer.__main__ import main as _main
    raise SystemExit(_main())
