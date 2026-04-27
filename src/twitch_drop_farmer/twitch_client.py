from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
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
    from twitch_drop_farmer.config import COOKIE_FILE, CONFIG_DIR
    from twitch_drop_farmer.models import DropCampaign, StreamCandidate
else:
    from .config import COOKIE_FILE, CONFIG_DIR
    from .models import DropCampaign, StreamCandidate


GQL_URL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = ""
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
ANDROID_APP_CLIENT_ID = ""
ANDROID_APP_USER_AGENT = (
    "Dalvik/2.1.0 (Linux; U; Android 16; SM-S911B Build/TP1A.220624.014) "
    "tv.twitch.android.app/25.3.0/2503006"
)
TWITCH_URL = "https://www.twitch.tv"
CAMPAIGN_CACHE_FILE = CONFIG_DIR / "campaign_cache.json"

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

SPADE_PATTERN = re.compile(r'"spade_?url"\s*:\s*"(https://[^"\\]+)"', re.I)
SETTINGS_PATTERN = re.compile(r'src="(https://[\w.]+/config/settings\.[0-9a-f]{32}\.js)"', re.I)


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
        self._campaign_cache: list[DropCampaign] = []
        self._streamless_media_playlist: dict[str, str] = {}
        self._streamless_spade_url: dict[str, str] = {}
        self.device_id = ""
        self.session_id = secrets.token_hex(16)
        self._load_cookies()
        self._load_campaign_cache()

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

    def _campaign_to_cache_payload(self, campaign: DropCampaign) -> dict[str, Any]:
        return {
            "id": campaign.id,
            "game_name": campaign.game_name,
            "title": campaign.title,
            "ends_at": campaign.ends_at.isoformat(),
            "progress_minutes": campaign.progress_minutes,
            "required_minutes": campaign.required_minutes,
            "starts_at": campaign.starts_at.isoformat(),
            "game_slug": campaign.game_slug,
            "game_box_art_url": campaign.game_box_art_url,
            "linked": campaign.linked,
            "link_url": campaign.link_url,
            "status": campaign.status,
            "allowed_channels": list(campaign.allowed_channels),
            "has_badge_or_emote": campaign.has_badge_or_emote,
            "all_drops_claimed": campaign.all_drops_claimed,
            "requires_subscription": campaign.requires_subscription,
            "next_drop_name": campaign.next_drop_name,
            "next_drop_remaining_minutes": campaign.next_drop_remaining_minutes,
            "next_drop_required_minutes": campaign.next_drop_required_minutes,
            "drops": campaign.drops,
        }

    def _campaign_from_cache_payload(self, payload: dict[str, Any]) -> DropCampaign | None:
        campaign_id = str(payload.get("id", "") or "").strip()
        if not campaign_id:
            return None
        ends_at = self._parse_timestamp(payload.get("ends_at"))
        starts_at = self._parse_timestamp(payload.get("starts_at"))
        return DropCampaign(
            id=campaign_id,
            game_name=str(payload.get("game_name", "") or ""),
            title=str(payload.get("title", "") or ""),
            ends_at=ends_at,
            progress_minutes=int(payload.get("progress_minutes", 0) or 0),
            required_minutes=int(payload.get("required_minutes", 0) or 0),
            starts_at=starts_at,
            game_slug=str(payload.get("game_slug", "") or ""),
            game_box_art_url=str(payload.get("game_box_art_url", "") or ""),
            linked=bool(payload.get("linked", True)),
            link_url=str(payload.get("link_url", "") or ""),
            status=str(payload.get("status", "") or ""),
            allowed_channels=list(payload.get("allowed_channels", []) or []),
            has_badge_or_emote=bool(payload.get("has_badge_or_emote", False)),
            all_drops_claimed=bool(payload.get("all_drops_claimed", False)),
            requires_subscription=bool(payload.get("requires_subscription", False)),
            next_drop_name=str(payload.get("next_drop_name", "") or ""),
            next_drop_remaining_minutes=int(payload.get("next_drop_remaining_minutes", 0) or 0),
            next_drop_required_minutes=int(payload.get("next_drop_required_minutes", 0) or 0),
            drops=list(payload.get("drops", []) or []),
        )

    def _load_campaign_cache(self) -> None:
        if not CAMPAIGN_CACHE_FILE.exists():
            return
        try:
            payload = json.loads(CAMPAIGN_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        entries = payload.get("campaigns", []) if isinstance(payload, dict) else []
        loaded: list[DropCampaign] = []
        now = datetime.now(timezone.utc)
        for item in entries:
            if not isinstance(item, dict):
                continue
            campaign = self._campaign_from_cache_payload(item)
            if campaign and campaign.ends_at > now:
                loaded.append(campaign)
        if loaded:
            self._campaign_cache = loaded
            self._note(f"Loaded persisted campaign cache ({len(loaded)}).")

    def _save_campaign_cache(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "campaigns": [self._campaign_to_cache_payload(campaign) for campaign in self._campaign_cache],
        }
        try:
            CAMPAIGN_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            self._note("Could not persist campaign cache to disk.")

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
        return headers

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
        cached = self._streamless_media_playlist.get(channel_login.casefold(), "")
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

        self._streamless_media_playlist[channel_login.casefold()] = media_playlist
        return media_playlist

    def _stream_info(self, channel_login: str) -> dict[str, str]:
        payload = self._clone_query(STREAM_INFO_QUERY)
        payload["variables"]["channel"] = channel_login
        response = self._post_gql(payload, client_profile="web")
        user = response.get("data", {}).get("user") or {}
        stream = user.get("stream") or {}
        channel_id = str(user.get("id", "") or "").strip()
        broadcast_id = str(stream.get("id", "") or "").strip()
        return {
            "channel_id": channel_id,
            "broadcast_id": broadcast_id,
        }

    def _extract_spade_url(self, html_or_js: str) -> str:
        match = SPADE_PATTERN.search(html_or_js)
        if match is None:
            return ""
        return match.group(1).replace(r"\/", "/")

    def _streamless_spade_endpoint(self, channel_login: str) -> str:
        cache_key = channel_login.casefold()
        cached = self._streamless_spade_url.get(cache_key, "")
        if cached:
            return cached

        response = self.session.get(
            f"https://m.twitch.tv/{channel_login}",
            headers={"User-Agent": WEB_USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        html = response.text

        spade_url = self._extract_spade_url(html)
        if not spade_url:
            settings_match = SETTINGS_PATTERN.search(html)
            if settings_match is None:
                raise ValueError("Could not locate Twitch settings script for spade URL extraction.")
            settings_url = settings_match.group(1)
            settings_response = self.session.get(
                settings_url,
                headers={"User-Agent": WEB_USER_AGENT},
                timeout=20,
            )
            settings_response.raise_for_status()
            spade_url = self._extract_spade_url(settings_response.text)
        if not spade_url:
            raise ValueError("Could not extract spade URL from channel page.")

        self._streamless_spade_url[cache_key] = spade_url
        return spade_url

    def _streamless_spade_payload(
        self,
        *,
        channel_login: str,
        channel_id: str,
        broadcast_id: str,
    ) -> dict[str, str]:
        payload = [
            {
                "event": "minute-watched",
                "properties": {
                    "broadcast_id": broadcast_id,
                    "channel_id": channel_id,
                    "channel": channel_login,
                    "hidden": False,
                    "live": True,
                    "location": "channel",
                    "logged_in": True,
                    "muted": False,
                    "player": "site",
                    "user_id": self.login_state.user_id,
                },
            }
        ]
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        return {"data": base64.b64encode(raw.encode("utf-8")).decode("ascii")}

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
            self._streamless_media_playlist.pop(channel_login.casefold(), None)
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

    def streamless_watch_heartbeat(
        self,
        channel_login: str,
        *,
        channel_id: str = "",
        broadcast_id: str = "",
    ) -> bool:
        login = channel_login.strip()
        if not login:
            return False
        if not self.login_state.oauth_token:
            self._note("Streamless heartbeat skipped because no auth-token is set.")
            return False

        try:
            ids = {"channel_id": channel_id.strip(), "broadcast_id": broadcast_id.strip()}
            if not ids["channel_id"] or not ids["broadcast_id"]:
                ids = self._stream_info(login)
            if not ids["channel_id"] or not ids["broadcast_id"]:
                self._note(f"Streamless heartbeat could not resolve stream IDs for {login}.")
                return self._streamless_watch_hls_head(login)

            spade_url = self._streamless_spade_endpoint(login)
            payload = self._streamless_spade_payload(
                channel_login=login,
                channel_id=ids["channel_id"],
                broadcast_id=ids["broadcast_id"],
            )
            response = self.session.post(
                spade_url,
                data=payload,
                headers=self._stream_headers(login),
                timeout=20,
            )
            if response.status_code == 204:
                self._note(f"Streamless watcher is tracking channel {login}.")
                return True
            self._note(f"Spade heartbeat returned HTTP {response.status_code} for {login}.")
            return self._streamless_watch_hls_head(login)
        except Exception as exc:
            self._note(f"Streamless heartbeat failed for {login}: {exc}")
            self._streamless_spade_url.pop(login.casefold(), None)
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
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
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
        keyword_patterns = (
            "subscribe to redeem",
            "subscription only",
            "subscription-only",
            "requires subscription",
            "requires a subscription",
            "subscribers only",
            "subscriber only",
            "sub only",
            "subs only",
            "subs-only",
            "subscricao para resgatar",
            "subscrição para resgatar",
            "subscricao obrigatoria",
            "subscrição obrigatória",
            "apenas subs",
            "apenas para subs",
            "só para subs",
        )

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
                    if key_norm in subscription_flag_keys and bool(value):
                        return True
                    if ("subscription" in key_norm or "subscriber" in key_norm) and bool(value):
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

        def walk_strings(node: Any) -> bool:
            if isinstance(node, str):
                text = node.strip().casefold()
                if "sub" in text and any(
                    token in text for token in ("redeem", "resgat", "claim", "required", "obrigat", "only")
                ):
                    return True
                return any(pattern in text for pattern in keyword_patterns)
            if isinstance(node, dict):
                for value in node.values():
                    if walk_strings(value):
                        return True
                return False
            if isinstance(node, list):
                for item in node:
                    if walk_strings(item):
                        return True
                return False
            return False

        if walk_struct(payload):
            return True
        if walk_strings(payload):
            return True
        for drop in drops:
            if walk_struct(drop):
                return True
            if walk_strings(drop):
                return True
        return False

    def _drop_progress_items(self, drops: list[dict[str, Any]]) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for drop in drops:
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

        html = response.text
        patterns = (
            # Standard JSON blocks.
            r'"id"\s*:\s*"([0-9a-fA-F-]{36})".{0,2000}?"status"\s*:\s*"(ACTIVE|UPCOMING)"',
            r'"status"\s*:\s*"(ACTIVE|UPCOMING)".{0,2000}?"id"\s*:\s*"([0-9a-fA-F-]{36})"',
            # Escaped JSON inside script payloads.
            r'\\"id\\"\s*:\s*\\"([0-9a-fA-F-]{36})\\".{0,2000}?\\"status\\"\s*:\s*\\"(ACTIVE|UPCOMING)\\"',
            r'\\"status\\"\s*:\s*\\"(ACTIVE|UPCOMING)\\".{0,2000}?\\"id\\"\s*:\s*\\"([0-9a-fA-F-]{36})\\"',
            # Alternative id key names used by some Twitch payloads.
            r'"(?:dropID|campaignId|dropCampaignId)"\s*:\s*"([0-9a-fA-F-]{36})".{0,2000}?"status"\s*:\s*"(ACTIVE|UPCOMING)"',
            r'\\"(?:dropID|campaignId|dropCampaignId)\\"\s*:\s*\\"([0-9a-fA-F-]{36})\\".{0,2000}?\\"status\\"\s*:\s*\\"(ACTIVE|UPCOMING)\\"',
        )
        found: dict[str, dict[str, Any]] = {}
        for pattern in patterns:
            for match in re.finditer(pattern, html, flags=re.DOTALL):
                first, second = match.groups()
                if first in {"ACTIVE", "UPCOMING"}:
                    status = first
                    campaign_id = second
                else:
                    campaign_id = first
                    status = second
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
            or "subscrição" in lowered
            or "subscricao" in lowered
            or "subscrição necessária" in lowered
            or "subscricao necessaria" in lowered
            or "apenas subs" in lowered
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

    def _campaigns_from_browser_page(self) -> list[DropCampaign]:
        try:
            from PySide6.QtCore import QEventLoop, QTimer, QUrl
            from PySide6.QtNetwork import QNetworkCookie
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
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
        payload: dict[str, Any] = {"raw": ""}
        timed_out = {"value": False}
        empty_rounds = {"value": 0}
        poll_timer = QTimer()
        poll_timer.setInterval(2_000)
        poll_timer.setSingleShot(False)

        try:
            def finish() -> None:
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
                        const bodyText = (document.body && document.body.innerText ? document.body.innerText : "").trim();
                        if (!bodyText) {
                            return "";
                        }
                        return bodyText;
                    })();
                """

                def on_result(raw: Any) -> None:
                    text = raw if isinstance(raw, str) else ""
                    has_campaign_like_schedule = bool(
                        re.search(r"(?:GMT|UTC)(?:[+-]\\d+)?", text)
                    )
                    if text and has_campaign_like_schedule:
                        payload["raw"] = text
                        finish()
                        return
                    empty_rounds["value"] += 1
                    if empty_rounds["value"] >= 12:
                        self._note("Browser fallback stopped early after repeated empty card polls.")
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
            timeout.start(25_000)
            page.load(QUrl(f"{TWITCH_URL}/drops/campaigns"))
            loop.exec()

            poll_timer.stop()
            timeout.stop()
        finally:
            shiboken_delete(page)
            shiboken_delete(profile)
            if owned_app:
                app.quit()

        if timed_out["value"]:
            self._note("Browser fallback timed out while loading the rendered Drops page.")
            return []

        raw_cards = payload["raw"]
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
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
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
        shiboken_delete(page)
        shiboken_delete(profile)
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
        starts_at = self._parse_timestamp(starts_at_raw)
        ends_at = self._parse_timestamp(ends_at_raw)
        status = str(data.get("status", "") or "").strip().upper()
        now = datetime.now(timezone.utc)

        if ends_at <= starts_at:
            self._note(
                f"Skipping campaign '{data.get('name') or game_name}' due to invalid schedule "
                f"({starts_at.isoformat()} -> {ends_at.isoformat()})."
            )
            return None

        if ends_at <= now:
            status = "EXPIRED"

        drops = data.get("timeBasedDrops", []) or []
        if not drops:
            drops = self._extract_drop_like_entries(data)
        total_required, total_remaining = self._drop_totals(drops)
        next_drop_name, next_drop_remaining, next_drop_required = self._next_drop_info(drops)
        all_drops_claimed = self._all_drops_claimed(drops)
        requires_subscription = self._campaign_requires_subscription(data, drops)
        
        # If no drops found in standard locations, try alternative extraction
        if total_required <= 0:
            total_required, total_remaining = self._extract_campaign_progress_data(data)
            if total_required > 0 and not next_drop_name:
                next_drop_name = str(data.get("name", "")).strip() or "Drop"
                next_drop_remaining = total_remaining
                next_drop_required = total_required
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
            next_drop_name=next_drop_name,
            next_drop_remaining_minutes=next_drop_remaining,
            next_drop_required_minutes=next_drop_required,
            drops=self._drop_progress_items(drops),
        )
        return campaign

    def fetch_campaigns(self, *, allow_browser_fallback: bool = True) -> list[DropCampaign]:
        self._diagnostics.clear()
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
            cached = [campaign for campaign in self._campaign_cache if campaign.ends_at > datetime.now(timezone.utc)]
            if cached:
                self._note(
                    f"Using cached campaign list ({len(cached)}) after transient validation failure."
                )
                return cached
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
            cached = [campaign for campaign in self._campaign_cache if campaign.ends_at > datetime.now(timezone.utc)]
            if cached:
                self._note(
                    f"ViewerDropsDashboard returned no payload. Using cached campaign list ({len(cached)})."
                )
                return cached
            return []
        dashboard_user = campaigns_response.get("data", {}).get("currentUser")
        if dashboard_user is None:
            self._note("ViewerDropsDashboard returned currentUser=null.")
            cached = [campaign for campaign in self._campaign_cache if campaign.ends_at > datetime.now(timezone.utc)]
            if cached:
                self._note(
                    f"Using cached campaign list ({len(cached)}) after currentUser=null from dashboard."
                )
                return cached
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
                "ViewerDropsDashboard blocked by integrity check. Using drops-page IDs plus inventory/cache fallback."
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

        if campaigns and should_try_browser_fallback and allow_browser_fallback:
            if dashboard_integrity_blocked:
                self._note(
                    "Campaign listing is integrity-limited. Trying rendered browser fallback for extra campaigns."
                )
            else:
                self._note(
                    "Campaign listing appears incomplete. Trying rendered browser fallback for the full list."
                )
            browser_campaigns = self._campaigns_from_browser_page()
            if browser_campaigns:
                # Merge by both ID and game name to preserve progress data
                merged_by_id = {campaign.id: campaign for campaign in campaigns}
                merged_by_game = {campaign.game_name.lower(): campaign for campaign in campaigns}
                
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
                    # Try game name match (case-insensitive)
                    elif browser_campaign.game_name.lower() in merged_by_game:
                        existing = merged_by_game[browser_campaign.game_name.lower()]
                        # Use browser campaign for schedule but keep progress from inventory
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
                        # Remove old campaign and add merged one
                        del merged_by_id[existing.id]
                        merged_by_id[browser_campaign.id] = browser_campaign
                        merged_by_game[browser_campaign.game_name.lower()] = browser_campaign
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
                cached = [campaign for campaign in self._campaign_cache if campaign.ends_at > datetime.now(timezone.utc)]
                if cached:
                    self._note(f"Using cached campaign list ({len(cached)}) instead of browser fallback.")
                    campaigns = cached
            elif allow_browser_fallback:
                self._note("ViewerDropsDashboard is empty or integrity-protected. Trying browser fallback.")
                campaigns = self._campaigns_from_browser_page()
                campaigns.sort(key=lambda item: item.starts_at)
                campaigns.sort(key=lambda item: item.active, reverse=True)
                if campaigns:
                    weak_listing = False
            else:
                self._note("ViewerDropsDashboard is empty or integrity-protected, and browser fallback is disabled.")
        now = datetime.now(timezone.utc)
        cached_campaigns = [campaign for campaign in self._campaign_cache if campaign.ends_at > now]
        if campaigns and cached_campaigns:
            inventory_ids = set(inventory_data)
            fresh_ids = {campaign.id for campaign in campaigns}
            cached_ids = {campaign.id for campaign in cached_campaigns}
            dashboard_matches_inventory = bool(inventory_ids) and fresh_ids == inventory_ids
            cache_has_more_campaigns = len(cached_ids) > len(fresh_ids) and bool(cached_ids - fresh_ids)
            if dashboard_matches_inventory and cache_has_more_campaigns:
                weak_listing = True
                self._note(
                    "Dashboard listing mirrors only in-progress inventory campaigns. "
                    "Keeping cached active/upcoming campaigns as fallback."
                )
        if campaigns and self._campaign_cache and weak_listing:
            # Inventory-only responses can hide valid active/upcoming campaigns.
            merged_by_id: dict[str, DropCampaign] = {
                campaign.id: campaign
                for campaign in cached_campaigns
                if campaign.ends_at > now
            }
            for campaign in campaigns:
                merged_by_id[campaign.id] = campaign
            if len(merged_by_id) > len(campaigns):
                campaigns = list(merged_by_id.values())
                campaigns.sort(key=lambda item: item.starts_at)
                campaigns.sort(key=lambda item: item.active, reverse=True)
                self._note(
                    f"Merged cached campaigns ({len(campaigns)}) because Twitch listing appears incomplete."
                )
        if campaigns and cached_campaigns and weak_listing:
            # Prevent sudden campaign drops when Twitch returns only a partial listing.
            if len(campaigns) < len(cached_campaigns):
                campaigns = cached_campaigns
                self._note(
                    "Kept cached campaign snapshot because fresh listing was smaller and likely incomplete."
                )

        if campaigns:
            # Keep a best-effort cache so the UI does not go empty when Twitch integrity checks block listing APIs.
            self._campaign_cache = [campaign for campaign in campaigns if campaign.ends_at > now]
            self._save_campaign_cache()
        elif self._campaign_cache:
            cached = [campaign for campaign in self._campaign_cache if campaign.ends_at > now]
            if cached:
                campaigns = cached
                self._campaign_cache = cached
                self._save_campaign_cache()
                self._note(
                    f"Using cached campaign list ({len(cached)}) because Twitch returned no active campaigns."
                )
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
                game = response.get("data", {}).get("game", {}) or {}
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
            game = response.get("data", {}).get("game", {}) or {}
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
                    channel_id=str(broadcaster.get("id", "") or ""),
                    broadcast_id=str(node.get("id", "") or ""),
                )
            )
        self._note(f"Found {len(output)} drops-enabled stream(s) for {campaign.game_name}.")
        return output


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
