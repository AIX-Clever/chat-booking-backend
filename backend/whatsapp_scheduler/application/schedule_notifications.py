"""
Application Layer — ScheduleNotificationsUseCase

Orchestrates domain logic with injected ports.
No direct boto3 / AWS SDK calls here.
"""
from datetime import datetime, timezone

from shared.domain.repositories import ITenantRepository
from shared.utils import Logger

from ..domain.models import BookingEvent, NotificationRule, TriggerType, INotificationPublisher, INotificationScheduler
from ..domain.message_builder import build_message

logger = Logger()

from typing import List

DEFAULT_RULES: List[dict] = [
    {
        "id": "on_booking",
        "name": "Confirmación al reservar",
        "trigger": TriggerType.ON_BOOKING,
        "active": True,
        "hours_before": None
    },
    {
        "id": "remind_24h",
        "name": "Recordatorio 24h antes",
        "trigger": TriggerType.HOURS_BEFORE,
        "active": True,
        "hours_before": 24
    },
    {
        "id": "remind_2h",
        "name": "Recordatorio 2h antes",
        "trigger": TriggerType.HOURS_BEFORE,
        "active": False,
        "hours_before": 2
    },
]


class ScheduleNotificationsUseCase:
    """
    Use Case: given a BOOKING_CONFIRMED event, read the tenant's
    notification rules and dispatch immediate or future WhatsApp messages.

    Dependencies are injected via constructor (ports), making this
    fully testable without any AWS SDK.
    """

    def __init__(
        self,
        tenant_repository: ITenantRepository,
        publisher: INotificationPublisher,
        scheduler: INotificationScheduler,
    ) -> None:
        self._tenant_repo = tenant_repository
        self._publisher = publisher
        self._scheduler = scheduler

    def execute(self, event: BookingEvent) -> None:
        """
        Main entry point. Raises ValueError if tenant not found or phone missing.
        """
        if not event.customer_phone:
            logger.warning("No customer_phone in BookingEvent, skipping", tenant_id=event.tenant_id)
            return

        tenant = self._tenant_repo.get_by_id(event.tenant_id)
        if not tenant:
            raise ValueError(f"Tenant not found: {event.tenant_id}")

        settings: dict = tenant.settings or {}
        raw_rules = settings.get("notification_rules", DEFAULT_RULES)
        rules = [NotificationRule.from_dict(r) for r in raw_rules]
        custom_templates = settings.get("whatsapp_notifications", {}).get("templates")

        for rule in rules:
            if not rule.active:
                continue
            self._dispatch(rule, event, custom_templates)

    # ------------------------------------------------------------------

    def _dispatch(self, rule: NotificationRule, event: BookingEvent, custom_templates: dict = None) -> None:
        message_body = build_message(rule, event, custom_templates)
        schedule_name = f"wa-{event.booking_id}-{rule.id}"[:64]

        if rule.is_on_booking():
            self._publisher.publish(
                tenant_id=event.tenant_id,
                booking_id=event.booking_id,
                customer_phone=event.customer_phone,
                message_body=message_body,
                rule_id=rule.id,
            )
            logger.info("Immediate notification published", rule_id=rule.id, tenant_id=event.tenant_id)
            return

        if rule.is_hours_before():
            fire_at = event.fire_time_for_rule(rule)
            if fire_at is None:
                return

            now_utc = datetime.now(timezone.utc)
            if fire_at <= now_utc:
                logger.warning(
                    "Scheduled fire time is in the past — skipping",
                    rule_id=rule.id,
                    fire_at=fire_at.isoformat(),
                )
                return

            self._scheduler.schedule(
                schedule_name=schedule_name,
                fire_at=fire_at,
                tenant_id=event.tenant_id,
                booking_id=event.booking_id,
                customer_phone=event.customer_phone,
                message_body=message_body,
                rule_id=rule.id,
            )
            logger.info("Notification scheduled", rule_id=rule.id, fire_at=fire_at.isoformat())
