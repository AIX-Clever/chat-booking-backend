"""
Application Layer — ScheduleRemindersUseCase

Orchestrates domain logic with injected ports.
No direct boto3 / AWS SDK calls here.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from shared.domain.repositories import ITenantRepository
from shared.utils import Logger

from ..domain.message_builder import build_reminder_payload
from ..domain.models import (
    BookingEvent,
    Channel,
    INotificationScheduler,
    NotificationRule,
    TriggerType,
)

logger = Logger()

DEFAULT_EMAIL_RULES = [
    {"id": "remind_24h", "trigger": TriggerType.HOURS_BEFORE, "active": True, "hours_before": 24},
]
DEFAULT_SMS_RULES: list = []


class ScheduleRemindersUseCase:
    """
    Given a BOOKING_CONFIRMED event, reads the tenant's email_notifications.rules
    and sms_notifications.rules and schedules future reminders via EventBridge.

    Only handles `hours_before` rules (on_booking is handled synchronously in
    booking_service.py). Skips rules where fire_at is in the past.
    """

    def __init__(
        self,
        tenant_repository: ITenantRepository,
        scheduler: INotificationScheduler,
    ) -> None:
        self._tenant_repo = tenant_repository
        self._scheduler = scheduler

    def execute(self, event: BookingEvent) -> None:
        tenant = self._tenant_repo.get_by_id(event.tenant_id)
        if not tenant:
            raise ValueError(f"Tenant not found: {event.tenant_id}")

        settings: dict = tenant.settings or {}
        email_cfg = settings.get("email_notifications", {})
        sms_cfg = settings.get("sms_notifications", {})

        email_enabled = email_cfg.get("enabled", True)
        sms_enabled = sms_cfg.get("enabled", False)

        lambda_arn = os.environ.get("NOTIFICATION_SCHEDULER_LAMBDA_ARN", "")
        role_arn = os.environ.get("NOTIFICATION_SCHEDULER_ROLE_ARN", "")
        group_name = os.environ.get("NOTIFICATION_SCHEDULER_GROUP", "ChatBooking-NotificationSchedules")
        sender_email = os.environ.get("SES_SENDER_EMAIL", "")

        now_utc = datetime.now(timezone.utc)

        if email_enabled and event.customer_email:
            email_rules = [NotificationRule.from_dict(r) for r in email_cfg.get("rules", DEFAULT_EMAIL_RULES)]
            email_templates = email_cfg.get("templates", {})
            for rule in email_rules:
                self._schedule_if_valid(
                    channel=Channel.EMAIL,
                    rule=rule,
                    event=event,
                    now_utc=now_utc,
                    email_templates=email_templates,
                    sms_templates=None,
                    sender_email=sender_email,
                    lambda_arn=lambda_arn,
                    role_arn=role_arn,
                    group_name=group_name,
                )

        if sms_enabled and event.customer_phone:
            sms_rules = [NotificationRule.from_dict(r) for r in sms_cfg.get("rules", DEFAULT_SMS_RULES)]
            sms_templates = sms_cfg.get("templates", {})
            for rule in sms_rules:
                self._schedule_if_valid(
                    channel=Channel.SMS,
                    rule=rule,
                    event=event,
                    now_utc=now_utc,
                    email_templates=None,
                    sms_templates=sms_templates,
                    sender_email=sender_email,
                    lambda_arn=lambda_arn,
                    role_arn=role_arn,
                    group_name=group_name,
                )

    def _schedule_if_valid(
        self,
        channel: str,
        rule: NotificationRule,
        event: BookingEvent,
        now_utc: datetime,
        email_templates,
        sms_templates,
        sender_email: str,
        lambda_arn: str,
        role_arn: str,
        group_name: str,
    ) -> None:
        if not rule.active or not rule.is_hours_before():
            return

        fire_at = event.fire_time(rule)
        if fire_at is None or fire_at <= now_utc:
            logger.warning(
                "Skipping reminder: fire_at is in the past or None",
                channel=channel,
                rule_id=rule.id,
                fire_at=fire_at.isoformat() if fire_at else "None",
            )
            return

        payload = build_reminder_payload(
            channel=channel,
            rule=rule,
            event=event,
            fire_at=fire_at,
            email_templates=email_templates,
            sms_templates=sms_templates,
            sender_email=sender_email,
        )
        schedule_name = f"notif-{channel[:3]}-{event.booking_id}-{rule.id}"[:64]

        self._scheduler.schedule(
            schedule_name=schedule_name,
            fire_at=fire_at,
            payload=payload,
            lambda_arn=lambda_arn,
            role_arn=role_arn,
            group_name=group_name,
        )
        logger.info(
            "Reminder scheduled",
            channel=channel,
            rule_id=rule.id,
            fire_at=fire_at.isoformat(),
            tenant_id=event.tenant_id,
        )
