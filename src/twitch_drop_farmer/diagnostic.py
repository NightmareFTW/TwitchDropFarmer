"""Diagnostic system for validating farm configuration and connectivity."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import requests

from .stream_watcher import playlist_segment_urls

if TYPE_CHECKING:
    from .twitch_client import TwitchClient

logger = logging.getLogger(__name__)


class DiagnosticStatus(Enum):
    """Diagnostic test status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(slots=True)
class DiagnosticResult:
    """Result of a single diagnostic test."""

    name: str
    status: DiagnosticStatus
    duration_ms: float = 0.0
    message: str = ""
    details: dict = field(default_factory=dict)


@dataclass(slots=True)
class DiagnosticReport:
    """Complete diagnostic report."""

    timestamp: float = field(default_factory=time.time)
    results: list[DiagnosticResult] = field(default_factory=list)
    summary: str = ""
    overall_status: DiagnosticStatus = DiagnosticStatus.PENDING

    def add_result(self, result: DiagnosticResult) -> None:
        """Add diagnostic result."""
        self.results.append(result)

    def get_status_counts(self) -> dict[DiagnosticStatus, int]:
        """Count results by status."""
        counts = {status: 0 for status in DiagnosticStatus}
        for result in self.results:
            counts[result.status] += 1
        return counts

    def is_healthy(self) -> bool:
        """Check if all critical tests passed."""
        for result in self.results:
            if result.status == DiagnosticStatus.FAILED:
                return False
        return True


class DiagnosticEngine:
    """Runs diagnostic tests on farm configuration."""

    def __init__(self, client: TwitchClient) -> None:
        self.client = client
        self.report = DiagnosticReport()

    async def run_all_diagnostics(self) -> DiagnosticReport:
        """Run all diagnostic tests."""
        self.report = DiagnosticReport()

        # Sequential tests
        await self._test_oauth_token()
        await self._test_twitch_api_connectivity()
        await self._test_campaigns_availability()
        await self._test_heartbeat_system()

        # Summarize
        counts = self.report.get_status_counts()
        failed = counts[DiagnosticStatus.FAILED]
        warning = counts[DiagnosticStatus.WARNING]
        success = counts[DiagnosticStatus.SUCCESS]

        if failed > 0:
            self.report.overall_status = DiagnosticStatus.FAILED
            self.report.summary = f"❌ {failed} critical issue(s) found."
        elif warning > 0:
            self.report.overall_status = DiagnosticStatus.WARNING
            self.report.summary = f"⚠️ {warning} warning(s). {success} checks passed."
        else:
            self.report.overall_status = DiagnosticStatus.SUCCESS
            self.report.summary = f"✅ All {success} checks passed."

        return self.report

    async def _test_oauth_token(self) -> None:
        """Test OAuth token validity."""
        result = DiagnosticResult(
            name="OAuth Token",
            status=DiagnosticStatus.RUNNING,
        )
        start = time.time()

        try:
            token = (self.client.login_state.oauth_token or "").strip()
            auth_cookie = (
                self.client.session.cookies.get("auth-token", domain=".twitch.tv")
                or self.client.session.cookies.get("auth-token", domain="www.twitch.tv")
                or ""
            ).strip()

            if token:
                login_state = await asyncio.to_thread(self.client.validate_oauth_token)
                result.duration_ms = (time.time() - start) * 1000
                account_name = login_state.login_name or self.client.login_state.login_name or "unknown"
                result.status = DiagnosticStatus.SUCCESS
                result.message = f"Token valid for account '{account_name}'."
            elif auth_cookie:
                # Durable-session imports may still carry valid session cookies.
                result.duration_ms = (time.time() - start) * 1000
                result.status = DiagnosticStatus.WARNING
                result.message = (
                    "Session cookie present but OAuth token is not loaded in memory. "
                    "Re-import session JSON or refresh auth-token to enable full validation."
                )
            else:
                result.duration_ms = (time.time() - start) * 1000
                result.status = DiagnosticStatus.FAILED
                result.message = "No OAuth token or auth-session cookie found."
        except ValueError as exc:
            result.duration_ms = (time.time() - start) * 1000
            result.status = DiagnosticStatus.FAILED
            result.message = f"Token invalid or expired: {exc}"
        except Exception as exc:
            result.duration_ms = (time.time() - start) * 1000
            token = (self.client.login_state.oauth_token or "").strip()
            auth_cookie = (
                self.client.session.cookies.get("auth-token", domain=".twitch.tv")
                or self.client.session.cookies.get("auth-token", domain="www.twitch.tv")
                or ""
            ).strip()
            if token or auth_cookie:
                result.status = DiagnosticStatus.WARNING
                result.message = f"Token validation unavailable right now: {exc}"
            else:
                result.status = DiagnosticStatus.FAILED
                result.message = f"Token check failed: {exc}"

        self.report.add_result(result)

    async def _test_twitch_api_connectivity(self) -> None:
        """Ask Twitch's GraphQL API a real, cheap question and judge the answer.

        The old test sent a deliberately fake query (a hash of 32 zeros) and counted the
        HTTP 400 Twitch answers to that as "API unreachable", so it could never pass: an
        answer, even a refusal, proves the server is reachable. This asks for the slug of a
        category that always exists, and tells reachable-and-working, reachable-but-refusing
        and unreachable apart.
        """
        from .twitch_client import GAME_REDIRECT_QUERY

        result = DiagnosticResult(name="Twitch API Connectivity", status=DiagnosticStatus.RUNNING)
        start = time.time()
        try:
            payload = self.client._clone_query(GAME_REDIRECT_QUERY)
            payload["variables"]["name"] = "Just Chatting"
            response = await asyncio.to_thread(self.client._post_gql, payload)
            result.duration_ms = (time.time() - start) * 1000
            errors = self.client._graphql_error_messages(response)
            game = ((response.get("data") or {}).get("game") or {}) if isinstance(response, dict) else {}
            if game.get("slug"):
                result.status = DiagnosticStatus.SUCCESS
                result.message = f"Twitch GraphQL API reachable and answering ({result.duration_ms:.0f} ms)."
            elif errors:
                result.status = DiagnosticStatus.WARNING
                result.message = (
                    f"Twitch answered but rejected a basic query: {errors[0]}. If this says "
                    "PersistedQueryNotFound, Twitch changed an internal query and the app needs an update."
                )
            else:
                result.status = DiagnosticStatus.WARNING
                result.message = "Twitch answered but returned no data for a basic query (it may be throttling this connection)."
        except requests.HTTPError as exc:
            result.duration_ms = (time.time() - start) * 1000
            code = getattr(exc.response, "status_code", "?")
            result.status = DiagnosticStatus.FAILED
            result.message = f"Twitch is reachable but refused the request (HTTP {code})."
        except (requests.ConnectionError, requests.Timeout) as exc:
            result.duration_ms = (time.time() - start) * 1000
            result.status = DiagnosticStatus.FAILED
            result.message = f"API unreachable: {exc}"
        except Exception as exc:  # noqa: BLE001
            result.duration_ms = (time.time() - start) * 1000
            result.status = DiagnosticStatus.FAILED
            result.message = f"API check failed: {exc}"

        self.report.add_result(result)

    async def _test_campaigns_availability(self) -> None:
        """Test campaign fetching."""
        result = DiagnosticResult(
            name="Campaigns Availability",
            status=DiagnosticStatus.RUNNING,
        )
        start = time.time()

        try:
            campaigns = await asyncio.to_thread(
                self.client.fetch_campaigns,
                allow_browser_fallback=False,
            )
            result.duration_ms = (time.time() - start) * 1000

            if campaigns:
                result.status = DiagnosticStatus.SUCCESS
                result.message = f"Found {len(campaigns)} active campaign(s)."
                result.details = {"count": len(campaigns)}
            else:
                result.status = DiagnosticStatus.WARNING
                result.message = "No active campaigns found (may be normal)."
        except Exception as exc:
            result.duration_ms = (time.time() - start) * 1000
            result.status = DiagnosticStatus.FAILED
            result.message = f"Campaign fetch failed: {exc}"

        self.report.add_result(result)

    async def _test_heartbeat_system(self) -> None:
        """Check the path the farm uses to count as a viewer: playback token, playlist, segment.

        This used to report "Heartbeat system ready" without checking anything (0.0 ms). It
        now does what the watcher does for a live channel, passively and anonymously (no
        minute-watched event is sent, so no watch time is credited to the channel it picks):
        gets a playback token, reads the media playlist and requests one segment.
        """
        result = DiagnosticResult(name="Watch Pipeline (HLS)", status=DiagnosticStatus.RUNNING)
        start = time.time()
        try:
            login = await asyncio.to_thread(self._any_live_channel)
            if not login:
                result.duration_ms = (time.time() - start) * 1000
                result.status = DiagnosticStatus.WARNING
                result.message = "Could not find a live channel to test the video path with."
            else:
                text, base_url = await asyncio.to_thread(self.client.hls_playlist_snapshot, login)
                urls = playlist_segment_urls(text, base_url)
                if not urls:
                    result.status = DiagnosticStatus.WARNING
                    result.message = "The playlist of a live channel came back with no segments."
                else:
                    await asyncio.to_thread(self.client.hls_touch_segment, login, urls[-1])
                    result.status = DiagnosticStatus.SUCCESS
                    result.message = f"Playback token, playlist ({len(urls)} segments) and a segment all answered."
                result.duration_ms = (time.time() - start) * 1000
        except Exception as exc:  # noqa: BLE001
            result.duration_ms = (time.time() - start) * 1000
            result.status = DiagnosticStatus.FAILED
            result.message = f"The video path failed: {exc}"

        self.report.add_result(result)

    def _any_live_channel(self) -> str:
        """The login of some live channel (the top one of a busy category), or ""."""
        from .twitch_client import GAME_DIRECTORY_QUERY

        payload = self.client._clone_query(GAME_DIRECTORY_QUERY)
        payload["variables"]["slug"] = "just-chatting"
        payload["variables"]["limit"] = 1
        payload["variables"]["options"]["systemFilters"] = []
        response = self.client._post_gql(payload)
        game = ((response.get("data") or {}).get("game") or {}) if isinstance(response, dict) else {}
        for edge in (game.get("streams") or {}).get("edges") or []:
            login = (((edge or {}).get("node") or {}).get("broadcaster") or {}).get("login") or ""
            if login:
                return str(login)
        return ""
