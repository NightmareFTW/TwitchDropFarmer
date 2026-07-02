from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import threading

from .config import AppConfig
from .models import ChannelOption, DropCampaign, FarmDecision, StreamCandidate
from .twitch_client import TwitchClient
from .watchdog import Watchdog, WatchdogConfig
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
    def __init__(self, client: TwitchClient, config: AppConfig) -> None:
        self.client = client
        self.config = config
        self.alert_manager = get_alert_manager()
        
        # Setup watchdog with config-based timeout
        watchdog_config = WatchdogConfig(
            stall_timeout_min=config.watchdog_stall_timeout_min,
            stall_check_interval_sec=60,
            max_recovery_attempts=3,
            recovery_cooldown_sec=120,
        )
        self.watchdog = Watchdog(watchdog_config)
        self.watchdog.is_enabled = config.watchdog_enabled
        
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

    def _channel_priority(self, stream: StreamCandidate) -> tuple[int, int, int]:
        whitelist = {item.casefold() for item in self.config.whitelist_channels}
        preferred = int(bool(whitelist) and stream.login.casefold() in whitelist)
        return (preferred, int(stream.drops_enabled), stream.viewer_count)

    def choose_stream(self, campaign: DropCampaign, streams: list[StreamCandidate]) -> StreamCandidate | None:
        blacklist = {item.casefold() for item in self.config.blacklist_channels}
        allowed = {item.casefold() for item in campaign.allowed_channels}
        base_valid = [
            stream
            for stream in streams
            if stream.login.casefold() not in blacklist
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

    def _decision_sort_key(self, decision: FarmDecision) -> tuple[int, tuple[float, ...]]:
        campaign = decision.campaign
        if campaign.active:
            phase = 0
        elif campaign.upcoming:
            phase = 1
        else:
            phase = 2
        return (phase, self._campaign_sort_key(campaign))

    def poll(self, *, allow_browser_fallback: bool | None = None, full_scan: bool = False) -> FarmSnapshot:
        if allow_browser_fallback is None:
            allow_browser_fallback = threading.current_thread() is threading.main_thread()
        campaigns = self.client.fetch_campaigns(
            allow_browser_fallback=allow_browser_fallback, full_scan=full_scan
        )
        messages = self.client.consume_diagnostics()
        available_games = sorted({campaign.game_name for campaign in campaigns}, key=str.casefold)
        available_channels: dict[str, ChannelOption] = {}
        decisions: list[FarmDecision] = []

        # Check for stalls and attempt recovery
        if self.config.watchdog_enabled:
            is_stalled, stall_reason = self.watchdog.check_stall()
            if is_stalled:
                messages.append(f"⚠️ Watchdog: {stall_reason}")
                # Attempt recovery if configured
                if self.watchdog.should_attempt_recovery():
                    self.watchdog.trigger_recovery("Token refresh + stream switch")
                    # Here you could add recovery logic like token refresh
                    # For now, just mark recovery as attempted
                    messages.append("A tentar recuperação automática...")

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
            # If the campaign has at least one watchable drop, proceed to farm those instead.
            if campaign.requires_subscription and not campaign.has_watchable_drops and not campaign.all_drops_claimed:
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

            subscription_only = (
                bool(campaign.drops)
                and not campaign.has_watchable_drops
                and campaign.required_minutes <= 0
            )
            if (campaign.requires_subscription or subscription_only) and not campaign.all_drops_claimed:
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
                streams = []
            messages.extend(self.client.consume_diagnostics())
            for stream in streams:
                available_channels[stream.login.casefold()] = ChannelOption(
                    login=stream.login,
                    display_name=stream.display_name or stream.login,
                )

            selected = self.choose_stream(campaign, streams)
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
            
            # Update watchdog with farming progress
            if selected and self.config.watchdog_enabled:
                total_minutes = campaign.required_minutes or 0
                self.watchdog.update_progress(
                    total_progress_minutes=total_minutes - campaign.remaining_minutes,
                    campaign_id=campaign.id,
                    channel=selected.login
                )

        decisions.sort(key=self._decision_sort_key)
        return FarmSnapshot(
            campaigns=campaigns,
            decisions=decisions,
            available_games=available_games,
            available_channels=sorted(available_channels.values(), key=lambda item: item.label.casefold()),
            messages=messages,
        )
