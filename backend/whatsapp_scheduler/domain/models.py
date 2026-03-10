"""
Domain Layer — whatsapp_scheduler

Pure Python: no boto3, no I/O, no framework dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TriggerType:
    ON_BOOKING = "on_booking"
    HOURS_BEFORE = "hours_before"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NotificationRule:
    """Represents a single notification rule configured by a tenant."""
    id: str
    name: str
    trigger: str          # TriggerType constant
    active: bool
    hours_before: Optional[int] = None  # only meaningful when trigger=HOURS_BEFORE

    @classmethod
    def from_dict(cls, data: dict) -> "NotificationRule":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            trigger=data.get("trigger", TriggerType.ON_BOOKING),
            active=data.get("active", False),
            hours_before=data.get("hours_before"),
        )

    def is_hours_before(self) -> bool:
        return self.trigger == TriggerType.HOURS_BEFORE

    def is_on_booking(self) -> bool:
        return self.trigger == TriggerType.ON_BOOKING


@dataclass(frozen=True)
class BookingEvent:
    """Immutable representation of a BOOKING_CONFIRMED event."""
    tenant_id: str
    booking_id: str
    booking_start_time: datetime
    customer_phone: str
    customer_name: str
    service_name: str

    def fire_time_for_rule(self, rule: NotificationRule) -> Optional[datetime]:
        """Return the UTC datetime when a notification for this rule should fire."""
        if rule.is_on_booking():
            return None  # immediate — no scheduled time needed
        if rule.hours_before is None:
            return None
        return self.booking_start_time - timedelta(hours=rule.hours_before)


# ---------------------------------------------------------------------------
# Ports (Interfaces)
# ---------------------------------------------------------------------------

from abc import ABC, abstractmethod


class INotificationPublisher(ABC):
    """Port: publish an immediate WhatsApp send event."""

    @abstractmethod
    def publish(
        self,
        tenant_id: str,
        booking_id: str,
        customer_phone: str,
        message_body: str,
        rule_id: str,
    ) -> None:
        """Publish an immediate send event to the messaging infrastructure."""


class INotificationScheduler(ABC):
    """Port: schedule a future WhatsApp send event."""

    @abstractmethod
    def schedule(
        self,
        schedule_name: str,
        fire_at: datetime,
        tenant_id: str,
        booking_id: str,
        customer_phone: str,
        message_body: str,
        rule_id: str,
    ) -> None:
        """Create a one-time schedule that fires at fire_at (UTC)."""
