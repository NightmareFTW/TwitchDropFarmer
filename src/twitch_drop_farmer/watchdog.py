"""Watchdog system for monitoring farm progress and automatic recovery."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class WatchdogState(Enum):
    """Watchdog monitoring state."""

    IDLE = "idle"
    MONITORING = "monitoring"
    STALLED = "stalled"
    RECOVERING = "recovering"


@dataclass(slots=True)
class ProgressSnapshot:
    """Snapshot of farm progress at a point in time."""

    timestamp: float = field(default_factory=time.time)
    total_progress_minutes: int = 0
    active_campaign_id: str = ""
    active_channel: str = ""
    message: str = ""

    def time_since_snapshot(self) -> float:
        """Seconds elapsed since this snapshot."""
        return time.time() - self.timestamp


@dataclass(slots=True)
class WatchdogConfig:
    """Configuration for watchdog behavior."""

    stall_timeout_min: int = 30  # Trigger recovery if no progress for N minutes
    stall_check_interval_sec: int = 60  # How often to check for stalls
    max_recovery_attempts: int = 3  # Max recovery cycles before giving up
    recovery_cooldown_sec: int = 120  # Wait between recovery attempts


class Watchdog:
    """Monitor farm progress and trigger automatic recovery."""

    def __init__(self, config: WatchdogConfig | None = None) -> None:
        self.config = config or WatchdogConfig()
        self.state = WatchdogState.IDLE
        self.last_snapshot: ProgressSnapshot | None = None
        self.recovery_attempts = 0
        self.last_recovery_time = 0.0
        self.is_enabled = True

    def update_progress(self, total_progress_minutes: int, campaign_id: str, channel: str) -> None:
        """Update current farming progress."""
        self.last_snapshot = ProgressSnapshot(
            total_progress_minutes=total_progress_minutes,
            active_campaign_id=campaign_id,
            active_channel=channel,
        )
        self.recovery_attempts = 0  # Reset counter on progress
        self.state = WatchdogState.MONITORING

    def check_stall(self) -> tuple[bool, str]:
        """
        Check if progress has stalled.

        Returns (is_stalled, reason).
        """
        if not self.is_enabled or self.state == WatchdogState.RECOVERING:
            return False, ""

        if self.last_snapshot is None:
            return False, "No progress snapshot yet"

        elapsed_min = self.last_snapshot.time_since_snapshot() / 60
        if elapsed_min >= self.config.stall_timeout_min:
            self.state = WatchdogState.STALLED
            reason = f"No progress for {elapsed_min:.0f} minutes (threshold: {self.config.stall_timeout_min})"
            logger.warning(f"Watchdog: {reason}")
            return True, reason

        return False, ""

    def should_attempt_recovery(self) -> bool:
        """Check if automatic recovery should be attempted."""
        if not self.is_enabled or self.state != WatchdogState.STALLED:
            return False

        if self.recovery_attempts >= self.config.max_recovery_attempts:
            logger.error("Watchdog: Max recovery attempts exceeded.")
            return False

        elapsed_since_last = time.time() - self.last_recovery_time
        if elapsed_since_last < self.config.recovery_cooldown_sec:
            logger.debug(f"Watchdog: Recovery cooldown active ({elapsed_since_last:.0f}s)")
            return False

        return True

    def trigger_recovery(self, recovery_action: str) -> None:
        """Mark recovery as triggered."""
        self.state = WatchdogState.RECOVERING
        self.recovery_attempts += 1
        self.last_recovery_time = time.time()
        logger.info(f"Watchdog: Attempting recovery #{self.recovery_attempts}: {recovery_action}")

    def recovery_succeeded(self) -> None:
        """Mark recovery as successful."""
        self.state = WatchdogState.MONITORING
        self.recovery_attempts = 0
        logger.info("Watchdog: Recovery succeeded, resumed monitoring.")

    def recovery_failed(self) -> None:
        """Mark recovery as failed."""
        if self.recovery_attempts >= self.config.max_recovery_attempts:
            self.state = WatchdogState.IDLE
            logger.error("Watchdog: Recovery failed and max attempts exceeded.")
        else:
            self.state = WatchdogState.STALLED

    def reset(self) -> None:
        """Reset watchdog state."""
        self.state = WatchdogState.IDLE
        self.last_snapshot = None
        self.recovery_attempts = 0
        self.last_recovery_time = 0.0

    def get_status(self) -> dict:
        """Get current watchdog status."""
        return {
            "state": self.state.value,
            "enabled": self.is_enabled,
            "recovery_attempts": self.recovery_attempts,
            "last_snapshot": (
                {
                    "timestamp": self.last_snapshot.timestamp,
                    "progress_minutes": self.last_snapshot.total_progress_minutes,
                    "campaign_id": self.last_snapshot.active_campaign_id,
                    "channel": self.last_snapshot.active_channel,
                    "elapsed_minutes": self.last_snapshot.time_since_snapshot() / 60,
                }
                if self.last_snapshot
                else None
            ),
        }
