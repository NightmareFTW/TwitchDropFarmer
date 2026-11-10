from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Callable

from .config import AppConfig
from .models import ChannelOption, DropCampaign, FarmDecision, StreamCandidate
from .twitch_client import TwitchClient
from .alerts import get_alert_manager, AlertType, AlertSeverity
from .energy_profiles import get_profile_by_name

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FarmSnapshot:
    campaigns: list[DropCampaign]
    decisions: list[FarmDecision]
    available_games: list[str]
    available_channels: list[ChannelOption]
    messages: list[str] = field(default_factory=list)


class FarmEngine:
    # Request budget. Every poll used to refresh the whole campaign list and then ask the
    # game directory about EVERY whitelisted game (~100 sequential requests, about once a
    # minute): far more than a person watching Twitch, and the sort of volume that gets an
    # address distrusted. Now the campaign list is reused for CAMPAIGN_REFRESH_SEC, and a
    # poll only asks about the games it needs:
    #   * the campaign being farmed: every poll (its channel may have gone offline);
    #   * the first FRONT_LIVE_WANTED campaigns with a live channel (the farm's next
    #     choices): re-checked after FRONT_TTL_SEC, at most MAX_FRONT_LOOKUPS per poll;
    #   * everything else (it only feeds the dashboard ribbons): after BACKGROUND_TTL_SEC,
    #     at most MAX_BACKGROUND_LOOKUPS per poll.
    # What was not looked up keeps its last answer (or "stream_unchecked" if there is none).
    CAMPAIGN_REFRESH_SEC = 600.0
    FRONT_TTL_SEC = 300.0
    FRONT_LIVE_WANTED = 2
    MAX_FRONT_LOOKUPS = 6
    BACKGROUND_TTL_SEC = 3600.0
    MAX_BACKGROUND_LOOKUPS = 8

    def _campaign_is_known_subscription_locked(self, campaign: DropCampaign) -> bool:
        if campaign.all_drops_claimed:
            return False

        if campaign.requires_subscription and not campaign.has_watchable_drops:
            return True

        if campaign.has_watchable_drops:
            return False

        text_chunks: list[str] = [campaign.title, campaign.next_drop_name, campaign.link_url]
        for drop in campaign.drops or []:
            if not isinstance(drop, dict):
                continue
            text_chunks.append(str(drop.get("name") or ""))
            metadata_text = str(drop.get("metadata") or "")
            if metadata_text:
                text_chunks.append(metadata_text)

        combined = "\n".join(chunk for chunk in text_chunks if chunk).casefold()
        patterns = (
            "subscribe to redeem",
            "subscription required",
            "subscription-only",
            "sub-only",
            "subscription only",
            "subscriber only",
            "subscribers only",
            "sub only",
            "subs only",
            "subscrição",
            "subscricao",
            "apenas subs",
            "apenas para subs",
            "so para subs",
        )
        if combined and any(pattern in combined for pattern in patterns):
            return True

        source_hint = str(getattr(campaign, "source", "") or "").casefold()
        if source_hint != "twitch":
            return False

        known_positive = 0
        known_zero = 0
        known_total = 0
        for drop in campaign.drops or []:
            if not isinstance(drop, dict):
                continue
            required = drop.get("requiredMinutesWatched")
            if required is None:
                continue
            try:
                required_value = int(required)
            except (TypeError, ValueError):
                continue
            known_total += 1
            if required_value > 0:
                known_positive += 1
            elif required_value == 0:
                known_zero += 1

        if known_total > 0 and known_positive == 0 and known_zero == known_total:
            return True

        return False

    def __init__(
        self,
        client: TwitchClient,
        config: AppConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.config = config
        self.alert_manager = get_alert_manager()
        self._clock = clock
        # Campaigns are shared with the UI on purpose: it merges live progress into these
        # objects, so reusing them keeps that progress between full refreshes.
        self._campaign_cache: list[DropCampaign] = []
        self._campaigns_fetched_at: float | None = None
        self._stream_cache: dict[str, tuple[float, list[StreamCandidate]]] = {}
        self.focus_campaign_ids: set[str] = set()
        # The channel being watched right now is kept while it stays valid (see
        # _channel_priority), and a channel that stopped crediting progress is skipped for a
        # while (see penalize_channel). Stall detection itself lives in farm_health.py.
        self.current_channel = ""
        self._channel_penalty: dict[str, float] = {}

        # Apply energy profile settings if available
        profile = get_profile_by_name(config.energy_profile)
        if profile:
            self.polling_interval_sec = profile.polling_interval_sec
            self.api_timeout_sec = profile.api_timeout_sec
            logger.info(f"FarmEngine iniciado com perfil: {config.energy_profile}")

    def _game_is_allowed(self, game: str) -> bool:
        game_key = game.casefold()
        blacklist = {item.casefold() for item in self.config.blacklist_games}
        whitelist = {item.casefold() for item in self.config.whitelist_games}
        if game_key in blacklist:
            return False
        if whitelist and game_key not in whitelist:
            return False
        return True

    def set_current_channel(self, login: str) -> None:
        """The channel being farmed now: it is kept while it remains a valid choice."""
        self.current_channel = (login or "").casefold()

    def penalize_channel(self, login: str, seconds: float) -> None:
        """Skip ``login`` for ``seconds`` (it stopped crediting progress)."""
        if login:
            self._channel_penalty[login.casefold()] = self._clock() + seconds

    def _channel_penalized(self, login: str) -> bool:
        until = self._channel_penalty.get(login.casefold())
        if until is None:
            return False
        if self._clock() >= until:
            del self._channel_penalty[login.casefold()]
            return False
        return True

    def _channel_priority(self, stream: StreamCandidate) -> tuple[int, int, int, int]:
        whitelist = {item.casefold() for item in self.config.whitelist_channels}
        preferred = int(bool(whitelist) and stream.login.casefold() in whitelist)
        # Staying on the channel already being watched beats a slightly bigger one: moving
        # restarts the watch session, and viewer counts swap places all the time.
        current = int(bool(self.current_channel) and stream.login.casefold() == self.current_channel)
        return (preferred, int(stream.drops_enabled), current, stream.viewer_count)

    def reselect(self, decision: FarmDecision) -> None:
        """Pick the stream of ``decision`` again from the last lookup (no network).

        Used right after a channel was penalized, so the farm moves at once instead of
        waiting for the next poll. With no alternative the decision ends up without a stream
        and the farm falls through to the next campaign.
        """
        cached = self._stream_cache.get(decision.campaign.id)
        streams = cached[1] if cached is not None else []
        decision.stream = self.choose_stream(decision.campaign, streams)
        decision.reason_code = "stream_selected" if decision.stream is not None else "no_valid_stream"

    def choose_stream(self, campaign: DropCampaign, streams: list[StreamCandidate]) -> StreamCandidate | None:
        blacklist = {item.casefold() for item in self.config.blacklist_channels}
        allowed = {item.casefold() for item in campaign.allowed_channels}
        base_valid = [
            stream
            for stream in streams
            if stream.login.casefold() not in blacklist and not self._channel_penalized(stream.login)
        ]
        if allowed:
            filtered = [
                stream
                for stream in base_valid
                if stream.login.casefold() in allowed
            ]
            # When the campaign restricts to specific channels, only those are eligible.
            valid = filtered
        else:
            valid = base_valid
        valid.sort(key=self._channel_priority, reverse=True)
        return valid[0] if valid else None

    def _campaign_sort_key(self, campaign: DropCampaign) -> tuple[float, ...]:
        remaining = campaign.remaining_minutes
        required = campaign.required_minutes if campaign.required_minutes > 0 else 10**9
        seconds_until_end = campaign.seconds_until_end
        mode = self.config.sort_mode

        if mode == "shortest_campaign":
            return (required, remaining, seconds_until_end)
        if mode == "longest_campaign":
            return (-required, -remaining, seconds_until_end)
        if mode == "least_remaining":
            return (remaining, seconds_until_end, required)
        if mode == "most_remaining":
            return (-remaining, seconds_until_end, -required)
        return (seconds_until_end, remaining, required)

    def _phase_and_sort_key(self, campaign: DropCampaign) -> tuple[int, tuple[float, ...]]:
        if campaign.active:
            phase = 0
        elif campaign.upcoming:
            phase = 1
        else:
            phase = 2
        return (phase, self._campaign_sort_key(campaign))

    def _decision_sort_key(self, decision: FarmDecision) -> tuple[int, tuple[float, ...]]:
        return self._phase_and_sort_key(decision.campaign)

    def _lookup_streams(self, campaign: DropCampaign, messages: list[str]) -> list[StreamCandidate] | None:
        """Ask Twitch for the live channels of ``campaign``; ``None`` if the request failed."""
        try:
            streams = self.client.fetch_streams(campaign)
        except Exception as exc:
            messages.append(f"Failed to fetch streams for {campaign.game_name}: {exc}")
            # Raise token alert if appropriate
            if "token" in str(exc).lower() and self.config.alert_token_invalid:
                self.alert_manager.raise_alert(
                    AlertType.TOKEN_INVALID,
                    AlertSeverity.ERROR,
                    "Token Inválido",
                    f"Erro ao buscar streams: {exc}"
                )
            streams = None
        messages.extend(self.client.consume_diagnostics())
        return streams

    def set_focus(self, *campaign_ids: str) -> None:
        """Campaigns whose channel must be re-checked on every poll (the farmed one)."""
        self.focus_campaign_ids = {cid for cid in campaign_ids if cid}

    def remember_streams(self, campaign: DropCampaign, streams: list[StreamCandidate]) -> None:
        """Store a stream lookup made outside ``poll`` (e.g. when the user picks a game)."""
        self._stream_cache[campaign.id] = (self._clock(), list(streams))

    def _load_campaigns(
        self, *, allow_browser_fallback: bool, full_scan: bool, force: bool
    ) -> tuple[list[DropCampaign], list[str]]:
        """The campaign list, from Twitch at most every CAMPAIGN_REFRESH_SEC."""
        now = self._clock()
        cached_age = None if self._campaigns_fetched_at is None else now - self._campaigns_fetched_at
        if (
            not force
            and not full_scan
            and self._campaign_cache
            and cached_age is not None
            and cached_age < self.CAMPAIGN_REFRESH_SEC
        ):
            return self._campaign_cache, list(self.client.consume_diagnostics())

        campaigns = self.client.fetch_campaigns(
            allow_browser_fallback=allow_browser_fallback, full_scan=full_scan
        )
        messages = list(self.client.consume_diagnostics())
        if campaigns:
            self._campaign_cache = campaigns
            self._campaigns_fetched_at = now
        elif self._campaign_cache:
            # A failed refresh must not empty the dashboard: keep the last list.
            messages.append("A actualização das campanhas falhou; mantém-se a lista anterior.")
            return self._campaign_cache, messages
        return campaigns, messages

    def poll(
        self,
        *,
        allow_browser_fallback: bool | None = None,
        full_scan: bool = False,
        force_campaigns: bool = False,
    ) -> FarmSnapshot:
        if allow_browser_fallback is None:
            allow_browser_fallback = threading.current_thread() is threading.main_thread()
        campaigns, messages = self._load_campaigns(
            allow_browser_fallback=allow_browser_fallback,
            full_scan=full_scan,
            force=force_campaigns,
        )
        available_games = sorted({campaign.game_name for campaign in campaigns}, key=str.casefold)
        available_channels: dict[str, ChannelOption] = {}
        decisions: list[FarmDecision] = []

        streamable: list[DropCampaign] = []
        for campaign in campaigns:
            if not self._game_is_allowed(campaign.game_name):
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="game_filtered",
                    )
                )
                continue

            # Subscription-only campaigns cannot be farmed by watch-time automation.
            # Only classify as such when the campaign carries explicit subscription evidence.
            if self._campaign_is_known_subscription_locked(campaign) and not campaign.all_drops_claimed:
                campaign.requires_subscription = True
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="subscription_required",
                    )
                )
                continue

            if campaign.all_drops_claimed:
                # Raise completion alert if enabled
                if self.config.alert_farm_complete:
                    self.alert_manager.raise_alert(
                        AlertType.FARM_COMPLETE,
                        AlertSeverity.INFO,
                        "Campanha Concluída",
                        f"{campaign.game_name} - Drop completado!"
                    )
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="campaign_completed",
                    )
                )
                continue

            if self._campaign_is_known_subscription_locked(campaign) and not campaign.all_drops_claimed:
                campaign.requires_subscription = True
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="subscription_required",
                    )
                )
                continue

            if campaign.required_minutes > 0 and campaign.remaining_minutes <= 0:
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="campaign_completed",
                    )
                )
                continue

            # Browser-only / no actionable drop data: campanha sem dados de drop farmiável.
            # Campanhas activas sem dados passam à detecção de streams para mostrar o
            # ribbon correcto (LIVE vs SEM CANAIS) em vez de INATIVO.  Só ignora
            # campanhas inactivas que também não têm dados de drop watchável.
            if campaign.required_minutes == 0 and not campaign.drops and not campaign.active:
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="no_actionable_drop_data",
                    )
                )
                continue

            # Check for expiring campaigns — use real campaign endAt, not watch time remaining.
            if (
                getattr(campaign, "timestamp_source", "") == "campaign"
                and campaign.seconds_until_end < 3600
            ):
                if self.config.alert_campaign_expiring_soon:
                    self.alert_manager.raise_alert(
                        AlertType.CAMPAIGN_EXPIRING_SOON,
                        AlertSeverity.WARNING,
                        "Campanha a expirar",
                        f"{campaign.game_name} — termina em {campaign.seconds_until_end // 60} minutos"
                    )

            # Inventory campaigns with synthetic timestamps (missing startAt/endAt from
            # Twitch API) may arrive as EXPIRED/inactive.  Repair them so the active
            # property returns True and the campaign can be farmed.
            # Também repara campanhas activas sem dados de drop (required_minutes=0,
            # drops=[]) que chegam com timestamps sintéticos — a API devolveu status
            # ACTIVE mas sem datas, por isso o campaign.active seria False sem a reparação.
            _has_actionable = bool(campaign.drops) or campaign.required_minutes > 0
            _api_says_active = campaign.status == "ACTIVE"
            if campaign.timestamps_are_synthetic and (_has_actionable or _api_says_active) and not campaign.active:
                _now = datetime.now(timezone.utc)
                campaign.starts_at = _now - timedelta(hours=1)
                campaign.ends_at = _now + timedelta(days=30)
                campaign.status = "ACTIVE"

            if not campaign.active:
                if campaign.upcoming:
                    _reason = "campaign_upcoming"
                elif campaign.status == "EXPIRED" and not campaign.timestamps_are_synthetic:
                    _reason = "campaign_expired"
                else:
                    _reason = "campaign_not_active"
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code=_reason,
                    )
                )
                continue

            # Inventory campaigns (non-empty drops) may have linked=False when
            # isAccountConnected=False in the Twitch API response.  Account linking
            # is only required at claim time; watch-time accumulates regardless.
            _is_inventory = bool(campaign.drops) or campaign.required_minutes > 0
            if not campaign.eligible and not _is_inventory:
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="account_not_linked",
                    )
                )
                continue

            streamable.append(campaign)

        # Highest priority first, so the request budget below is spent where it matters:
        # the campaigns being farmed, then the ones already in progress (what the user is
        # most likely to want to continue), then the ones with real drop data, then the
        # rest in the user's sort order.
        streamable.sort(
            key=lambda item: (
                item.id not in self.focus_campaign_ids,
                item.progress_minutes <= 0,
                not (item.drops or item.required_minutes > 0),
                *self._phase_and_sort_key(item),
            )
        )
        now = self._clock()
        front_live = 0
        front_lookups = 0
        background_lookups = 0
        looked_up = 0
        unchecked = 0
        for campaign in streamable:
            cached = self._stream_cache.get(campaign.id)
            age = float("inf") if cached is None else now - cached[0]
            focus = campaign.id in self.focus_campaign_ids
            in_front = front_live < self.FRONT_LIVE_WANTED and front_lookups < self.MAX_FRONT_LOOKUPS
            if focus:
                refresh = True
            elif in_front:
                refresh = age >= self.FRONT_TTL_SEC
                front_lookups += int(refresh)
            else:
                refresh = age >= self.BACKGROUND_TTL_SEC and background_lookups < self.MAX_BACKGROUND_LOOKUPS
                background_lookups += int(refresh)

            streams: list[StreamCandidate] | None = cached[1] if cached is not None else None
            if refresh:
                looked_up += 1
                fetched = self._lookup_streams(campaign, messages)
                if fetched is not None:
                    streams = fetched
                    self._stream_cache[campaign.id] = (now, fetched)
                elif streams is None:
                    streams = []  # first lookup failed: report it as "no stream", as before

            if streams is None:
                unchecked += 1
                decisions.append(
                    FarmDecision(campaign=campaign, stream=None, reason_code="stream_unchecked")
                )
                continue

            for stream in streams:
                available_channels[stream.login.casefold()] = ChannelOption(
                    login=stream.login,
                    display_name=stream.display_name or stream.login,
                )

            selected = self.choose_stream(campaign, streams)
            if selected is not None and (focus or in_front):
                front_live += 1
            decisions.append(
                FarmDecision(
                    campaign=campaign,
                    stream=selected,
                    reason_code="stream_selected" if selected else "no_valid_stream",
                    used_channel_whitelist=bool(
                        selected
                        and self.config.whitelist_channels
                        and selected.login.casefold()
                        in {item.casefold() for item in self.config.whitelist_channels}
                    ),
                )
            )

        if streamable:
            messages.append(
                f"Canais: {looked_up} consulta(s) nesta volta, {len(streamable) - looked_up - unchecked} "
                f"jogo(s) com a última resposta guardada, {unchecked} por verificar."
            )

        decisions.sort(key=self._decision_sort_key)
        return FarmSnapshot(
            campaigns=list(campaigns),
            decisions=decisions,
            available_games=available_games,
            available_channels=sorted(available_channels.values(), key=lambda item: item.label.casefold()),
            messages=messages,
        )
