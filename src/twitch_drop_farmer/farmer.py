from __future__ import annotations

from dataclasses import dataclass, field

from .config import AppConfig
from .models import ChannelOption, DropCampaign, FarmDecision, StreamCandidate
from .twitch_client import TwitchClient


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
            # Twitch ACL payload can contain labels that are not channel logins.
            # If no live stream matches ACL entries, fall back to drops-enabled streams.
            valid = filtered if filtered else base_valid
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

    def poll(self) -> FarmSnapshot:
        campaigns = self.client.fetch_campaigns()
        messages = self.client.consume_diagnostics()
        available_games = sorted({campaign.game_name for campaign in campaigns}, key=str.casefold)
        available_channels: dict[str, ChannelOption] = {}
        decisions: list[FarmDecision] = []

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
            if campaign.requires_subscription and not campaign.all_drops_claimed:
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="subscription_required",
                    )
                )
                continue

            if campaign.all_drops_claimed:
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="campaign_completed",
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

            if not campaign.active:
                decisions.append(
                    FarmDecision(
                        campaign=campaign,
                        stream=None,
                        reason_code="campaign_upcoming" if campaign.upcoming else "campaign_not_active",
                    )
                )
                continue

            if not campaign.eligible:
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

        decisions.sort(key=self._decision_sort_key)
        return FarmSnapshot(
            campaigns=campaigns,
            decisions=decisions,
            available_games=available_games,
            available_channels=sorted(available_channels.values(), key=lambda item: item.label.casefold()),
            messages=messages,
        )
