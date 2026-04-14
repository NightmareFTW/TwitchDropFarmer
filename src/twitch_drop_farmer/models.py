from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class DropCampaign:
    id: str
    game_name: str
    title: str
    ends_at: datetime
    progress_minutes: int = 0
    required_minutes: int = 0

    @property
    def completion(self) -> float:
        if self.required_minutes <= 0:
            return 0.0
        return min(1.0, self.progress_minutes / self.required_minutes)


@dataclass(slots=True)
class StreamCandidate:
    login: str
    display_name: str
    game_name: str
    viewer_count: int
    drops_enabled: bool


@dataclass(slots=True)
class FarmDecision:
    campaign: DropCampaign
    stream: StreamCandidate | None
    reason: str
