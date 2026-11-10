"""Stall detection for the campaign being farmed, with escalating recovery steps.

The old watchdog was fed the progress of every campaign that had a channel, so its "no
progress" clock was reset by whichever campaign came next and it never fired; its recovery
only wrote a message. This monitor is fed once per heartbeat with the progress of the
campaign that is really being farmed (as reconciled from Twitch's Inventory) and answers
with the next step to try when that progress stops moving:

1. restart the HLS watch session (new playback token, new playlist), the cheap fix;
2. switch to another channel of the same campaign (the current one may not be crediting);
3. give up on the campaign for a while and farm another one.

Each step fires once per stall. The thresholds derive from the single "stall timeout" the
user can set (minutes without progress before the farm is considered stuck): the last step
happens at the timeout, the others at fractions of it. Steps 1 and 2 are timed per channel
(a new channel gets a fresh chance), step 3 is timed per campaign, so changing channels
cannot postpone giving up on a campaign that does not move.

It is pure logic (no Qt, no network) with an injectable clock.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Callable

# Progress is reconciled about once a minute, so a gap this long between two observations
# means the app was paused, offline or busy: that time must not count as a stall.
BLACKOUT_SEC = 180.0

RESTART_FRACTION = 0.2
CHANNEL_FRACTION = 0.5
MIN_RESTART_MIN = 4.0
MIN_CHANNEL_MIN = 8.0
MIN_CAMPAIGN_MIN = 12.0


class Action(Enum):
    NONE = "none"
    RESTART_WATCH = "restart_watch"
    SWITCH_CHANNEL = "switch_channel"
    SWITCH_CAMPAIGN = "switch_campaign"


# How far a recovery went (reported with the "recovered" notice).
LEVEL_RESTART = 1
LEVEL_CHANNEL = 2
LEVEL_CAMPAIGN = 3


def thresholds(timeout_min: float) -> tuple[float, float, float]:
    """Minutes without progress at which each step fires, always increasing."""
    campaign = max(float(timeout_min), MIN_CAMPAIGN_MIN)
    channel = max(campaign * CHANNEL_FRACTION, MIN_CHANNEL_MIN)
    restart = max(campaign * RESTART_FRACTION, MIN_RESTART_MIN)
    channel = max(channel, restart + 1.0)
    campaign = max(campaign, channel + 1.0)
    return restart, channel, campaign


class FarmHealth:
    def __init__(self, timeout_min: float = 30.0, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.enabled = True
        self.timeout_min = timeout_min
        self.reset()

    def reset(self) -> None:
        self._key: tuple[str, str] | None = None  # (campaign, channel) being watched
        self._progress = -1
        self._since = 0.0  # when this campaign+channel last made progress (or was first seen)
        self._campaign_since = 0.0  # the same, but for the campaign whatever the channel
        self._campaign_fired = False
        self._last_observed = 0.0
        self._stage = 0  # channel-level steps already fired for the current stall
        self._acted_level = 0  # the furthest step taken since the farm last moved
        self._recovered_level = 0

    def set_timeout(self, minutes: float) -> None:
        self.timeout_min = minutes

    # ----------------------------------------------------------------- feeding
    def observe(self, campaign_id: str, channel: str, progress_minutes: int) -> None:
        """Record the campaign progress seen after a heartbeat for this campaign and channel."""
        now = self._clock()
        key = (campaign_id, channel.casefold())
        if self._key is None or key[0] != self._key[0]:
            # A different campaign: its own clock starts now.
            self._campaign_since = now
            self._campaign_fired = False
        if key != self._key:
            # A different channel (or campaign) starts with a fresh set of steps.
            self._key = key
            self._progress = progress_minutes
            self._since = now
            self._last_observed = now
            self._stage = 0
            return
        gap = now - self._last_observed
        if gap > BLACKOUT_SEC:
            self._since += gap
            self._campaign_since += gap
        if progress_minutes > self._progress:
            self._progress = progress_minutes
            self._since = now
            self._campaign_since = now
            self._campaign_fired = False
            self._stage = 0
            if self._acted_level:
                self._recovered_level = self._acted_level
                self._acted_level = 0
        self._last_observed = now

    # ---------------------------------------------------------------- deciding
    def stalled_minutes(self) -> float:
        """Minutes the current campaign+channel has gone without progress."""
        if self._key is None:
            return 0.0
        return max(0.0, (self._last_observed - self._since) / 60.0)

    def campaign_stalled_minutes(self) -> float:
        """Minutes the current campaign has gone without progress, whichever channel."""
        if self._key is None:
            return 0.0
        return max(0.0, (self._last_observed - self._campaign_since) / 60.0)

    def check(self) -> Action:
        """The next recovery step if the current target has stalled, else ``Action.NONE``."""
        if not self.enabled or self._key is None:
            return Action.NONE
        restart, channel, campaign = thresholds(self.timeout_min)
        if not self._campaign_fired and self.campaign_stalled_minutes() >= campaign:
            self._campaign_fired = True
            self._acted_level = max(self._acted_level, LEVEL_CAMPAIGN)
            return Action.SWITCH_CAMPAIGN
        steps = (
            (restart, Action.RESTART_WATCH, LEVEL_RESTART),
            (channel, Action.SWITCH_CHANNEL, LEVEL_CHANNEL),
        )
        if self._stage >= len(steps):
            return Action.NONE
        minutes, action, level = steps[self._stage]
        if self.stalled_minutes() < minutes:
            return Action.NONE
        self._stage += 1
        self._acted_level = max(self._acted_level, level)
        return action

    def take_recovered(self) -> int:
        """How far the recovery went if progress has moved again since, once; else 0."""
        level, self._recovered_level = self._recovered_level, 0
        return level
