from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .models import DropCampaign, FarmDecision, StreamCandidate
from .twitch_client import TwitchClient


@dataclass(slots=True)
class FarmSnapshot:
    campaigns: list[DropCampaign]
    decisions: list[FarmDecision]


class FarmEngine:
    def __init__(self, client: TwitchClient, config: AppConfig) -> None:
        self.client = client
        self.config = config

    def _accept_game(self, game: str) -> bool:
        gl = game.casefold()
        if gl in {x.casefold() for x in self.config.blacklist_games}:
            return False
        if self.config.whitelist_games and gl not in {x.casefold() for x in self.config.whitelist_games}:
            return False
        return True

    def choose_stream(self, streams: list[StreamCandidate]) -> StreamCandidate | None:
        valid = [
            s for s in streams
            if s.login.casefold() not in {x.casefold() for x in self.config.blacklist_channels}
        ]
        valid.sort(key=lambda x: (x.drops_enabled, x.viewer_count), reverse=True)
        return valid[0] if valid else None

    def poll(self) -> FarmSnapshot:
        campaigns = self.client.fetch_campaigns()
        decisions: list[FarmDecision] = []
        for campaign in campaigns:
            if not self._accept_game(campaign.game_name):
                decisions.append(FarmDecision(campaign, None, "Filtrado por blacklist/whitelist"))
                continue
            streams = self.client.fetch_streams(campaign.game_name)
            selected = self.choose_stream(streams)
            decisions.append(
                FarmDecision(
                    campaign=campaign,
                    stream=selected,
                    reason="Melhor stream por drops+viewers" if selected else "Sem stream válida",
                )
            )
        return FarmSnapshot(campaigns=campaigns, decisions=decisions)
