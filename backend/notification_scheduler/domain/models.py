"""
Domain Layer — notification_scheduler

Pure Python: no boto3, no I/O, no framework dependencies.
Handles Email and SMS reminder scheduling.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


class Channel:
    EMAIL = "email"
    SMS = "sms"


class TriggerType:
    ON_BOOKING = "on_booking"
    HOURS_BEFORE = "hours_before"


@dataclass(frozen=True)
class NotificationRule:
    id: str
    trigger: str
    active: bool
    hours_before: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "NotificationRule":
        return cls(
            id=data.get("id", data.get("trigger", "unknown")),
            trigger=data.get("trigger", TriggerType.ON_BOOKING),
            active=data.get("active", True),
            hours_before=data.get("hours_before"),
        )

    def is_hours_before(self) -> bool:
        return self.trigger == TriggerType.HOURS_BEFORE and self.hours_before is not None


@dataclass(frozen=True)
class BookingEvent:
    """Immutable representation of a BOOKING_CONFIRMED event."""
    tenant_id: str
    booking_id: str
    booking_start_time: datetime
    customer_name: str
    customer_email: str
    customer_phone: str
    service_name: str
    provider_name: str
    provider_timezone: str

    def fire_time(self, rule: NotificationRule) -> Optional[datetime]:
        if not rule.is_hours_before():
            return None
        return self.booking_start_time - timedelta(hours=rule.hours_before)


@dataclass(frozen=True)
class ReminderPayload:
    """Pre-built reminder ready to send when EventBridge fires."""
    channel: str          # Channel.EMAIL or Channel.SMS
    tenant_id: str
    booking_id: str
    rule_id: str
    # Email fields
    to_address: str = ""
    subject: str = ""
    body_html: str = ""
    body_text: str = ""
    # SMS fields
    phone_number: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "event_type": "REMINDER_FIRE",
            "channel": self.channel,
            "tenant_id": self.tenant_id,
            "booking_id": self.booking_id,
            "rule_id": self.rule_id,
            "to_address": self.to_address,
            "subject": self.subject,
            "body_html": self.body_html,
            "body_text": self.body_text,
            "phone_number": self.phone_number,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReminderPayload":
        return cls(
            channel=data["channel"],
            tenant_id=data["tenant_id"],
            booking_id=data["booking_id"],
            rule_id=data.get("rule_id", ""),
            to_address=data.get("to_address", ""),
            subject=data.get("subject", ""),
            body_html=data.get("body_html", ""),
            body_text=data.get("body_text", ""),
            phone_number=data.get("phone_number", ""),
            message=data.get("message", ""),
        )


class INotificationScheduler(ABC):
    @abstractmethod
    def schedule(
        self,
        schedule_name: str,
        fire_at: datetime,
        payload: ReminderPayload,
        lambda_arn: str,
        role_arn: str,
        group_name: str,
    ) -> None:
        """Create a one-time EventBridge schedule that directly invokes a Lambda."""
