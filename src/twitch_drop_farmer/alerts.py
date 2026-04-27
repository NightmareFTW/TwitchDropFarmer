"""Alert and notification system."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity level."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(Enum):
    """Types of alerts that can be triggered."""

    CAMPAIGN_EXPIRING_SOON = "campaign_expiring_soon"
    TOKEN_INVALID = "token_invalid"
    NO_PROGRESS = "no_progress"
    FARM_COMPLETE = "farm_complete"
    STREAM_OFFLINE = "stream_offline"
    API_ERROR = "api_error"
    WATCHDOG_RECOVERED = "watchdog_recovered"


@dataclass(slots=True)
class Alert:
    """Single alert instance."""

    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    dismissible: bool = True
    auto_dismiss_sec: int | None = None  # Auto-dismiss timeout in seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "dismissible": self.dismissible,
            "auto_dismiss_sec": self.auto_dismiss_sec,
        }


class AlertManager:
    """Centralized alert management."""

    def __init__(self) -> None:
        self.alerts: list[Alert] = []
        self.callbacks: list[Callable[[Alert], None]] = []
        self.config: dict[AlertType, bool] = {
            alert_type: True for alert_type in AlertType
        }

    def register_callback(self, callback: Callable[[Alert], None]) -> None:
        """Register callback to be called when alert is raised."""
        self.callbacks.append(callback)

    def set_alert_enabled(self, alert_type: AlertType, enabled: bool) -> None:
        """Enable or disable specific alert type."""
        self.config[alert_type] = enabled

    def is_alert_enabled(self, alert_type: AlertType) -> bool:
        """Check if alert type is enabled."""
        return self.config.get(alert_type, True)

    def raise_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        dismissible: bool = True,
        auto_dismiss_sec: int | None = None,
    ) -> Alert:
        """Raise a new alert."""
        if not self.is_alert_enabled(alert_type):
            logger.debug(f"Alert {alert_type.value} is disabled, skipping.")
            return Alert(
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
            )

        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            dismissible=dismissible,
            auto_dismiss_sec=auto_dismiss_sec,
        )

        self.alerts.append(alert)
        logger.log(
            {
                AlertSeverity.INFO: logging.INFO,
                AlertSeverity.WARNING: logging.WARNING,
                AlertSeverity.ERROR: logging.ERROR,
                AlertSeverity.CRITICAL: logging.CRITICAL,
            }[severity],
            f"Alert [{alert_type.value}]: {title} - {message}",
        )

        # Notify callbacks
        for callback in self.callbacks:
            try:
                callback(alert)
            except Exception as exc:
                logger.error(f"Alert callback failed: {exc}")

        return alert

    def dismiss_alert(self, alert_index: int) -> None:
        """Dismiss alert by index."""
        if 0 <= alert_index < len(self.alerts):
            alert = self.alerts.pop(alert_index)
            logger.debug(f"Dismissed alert: {alert.title}")

    def get_recent_alerts(self, limit: int = 10) -> list[Alert]:
        """Get recent alerts, newest first."""
        return list(reversed(self.alerts[-limit:]))

    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self.alerts.clear()

    def show_desktop_notification(self, alert: Alert) -> bool:
        """Show desktop notification (Windows 10+ only)."""
        if sys.platform != "win32":
            return False

        try:
            from win10toast import ToastNotifier

            toaster = ToastNotifier()
            toaster.show_toast(
                title=alert.title,
                msg=alert.message,
                duration=max(3, (alert.auto_dismiss_sec or 5)),
                threaded=True,
            )
            return True
        except Exception as exc:
            logger.debug(f"Desktop notification failed: {exc}")
            return False


# Global alert manager instance
_alert_manager: AlertManager | None = None


def get_alert_manager() -> AlertManager:
    """Get or create global alert manager."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
