from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class DropCampaign:
    id: str
    game_name: str
    title: str
    ends_at: datetime
    progress_minutes: int = 0
    required_minutes: int = 0
    starts_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    game_slug: str = ""
    game_box_art_url: str = ""
    linked: bool = True
    link_url: str = ""
    status: str = ""
    allowed_channels: list[str] = field(default_factory=list)
    has_badge_or_emote: bool = False
    next_drop_name: str = ""
    next_drop_remaining_minutes: int = 0
    next_drop_required_minutes: int = 0

    @property
    def completion(self) -> float:
        if self.required_minutes <= 0:
            return 0.0
        return min(1.0, self.progress_minutes / self.required_minutes)

    @property
    def remaining_minutes(self) -> int:
        if self.required_minutes <= 0:
            return 0
        return max(0, self.required_minutes - self.progress_minutes)

    @property
    def seconds_until_end(self) -> int:
        now = datetime.now(timezone.utc)
        target = self.ends_at
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0, int((target - now).total_seconds()))

    @property
    def active(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.starts_at <= now < self.ends_at and self.status != "EXPIRED"

    @property
    def upcoming(self) -> bool:
        now = datetime.now(timezone.utc)
        return now < self.starts_at and self.status != "EXPIRED"

    @property
    def eligible(self) -> bool:
        return self.linked or self.has_badge_or_emote

    @property
    def linkable(self) -> bool:
        return bool(self.link_url and not self.linked)

    @property
    def next_drop_eta_seconds(self) -> int:
        return max(0, self.next_drop_remaining_minutes * 60)


@dataclass(slots=True)
class StreamCandidate:
    login: str
    display_name: str
    game_name: str
    viewer_count: int
    drops_enabled: bool


@dataclass(slots=True, frozen=True)
class ChannelOption:
    login: str
    display_name: str

    @property
    def label(self) -> str:
        if not self.display_name:
            return self.login
        if self.display_name.casefold() == self.login.casefold():
            return self.display_name
        return f"{self.display_name} ({self.login})"


@dataclass(slots=True)
class FarmDecision:
    campaign: DropCampaign
    stream: StreamCandidate | None
    reason_code: str
    used_channel_whitelist: bool = False
