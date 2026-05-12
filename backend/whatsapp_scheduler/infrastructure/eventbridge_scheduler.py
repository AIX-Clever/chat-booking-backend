"""
Infrastructure Adapter — EventBridge Scheduler

Implements INotificationScheduler using AWS EventBridge Scheduler.
"""
import json
import os
from datetime import datetime

import boto3

from ..domain.models import INotificationScheduler


class EventBridgeNotificationScheduler(INotificationScheduler):
    """Adapter: creates one-time EventBridge Scheduler schedules that publish to SNS."""

    def __init__(
        self,
        topic_arn: str | None = None,
        scheduler_role_arn: str | None = None,
        group_name: str | None = None,
    ) -> None:
        self._topic_arn = topic_arn or os.environ.get("WHATSAPP_SNS_TOPIC_ARN", "")
        self._role_arn = scheduler_role_arn or os.environ.get("SCHEDULER_ROLE_ARN", "")
        self._group_name = group_name or os.environ.get("SCHEDULER_GROUP_NAME", "ChatBooking-WhatsappSchedules")
        self._client = boto3.client("scheduler")

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
        payload = {
            "event_type": "WHATSAPP_SEND",
            "tenant_id": tenant_id,
            "booking_id": booking_id,
            "to": customer_phone,
            "message": message_body,
            "rule_id": rule_id,
        }
        # Format: yyyy-MM-ddTHH:mm:ss (EventBridge interprets as UTC)
        at_expression = f"at({fire_at.strftime('%Y-%m-%dT%H:%M:%S')})"

        self._client.create_schedule(
            Name=schedule_name,
            GroupName=self._group_name,
            ScheduleExpression=at_expression,
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            Target={
                "Arn": self._topic_arn,
                "RoleArn": self._role_arn,
                "Input": json.dumps(payload),
            },
        )
