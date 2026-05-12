"""
Infrastructure Adapter — EventBridge Scheduler

Creates one-time schedules that directly invoke the notification_scheduler Lambda.
"""
from __future__ import annotations

import json
from datetime import datetime

import boto3

from ..domain.models import INotificationScheduler, ReminderPayload


class EventBridgeReminderScheduler(INotificationScheduler):

    def __init__(self) -> None:
        self._client = boto3.client("scheduler")

    def schedule(
        self,
        schedule_name: str,
        fire_at: datetime,
        payload: ReminderPayload,
        lambda_arn: str,
        role_arn: str,
        group_name: str,
    ) -> None:
        at_expression = f"at({fire_at.strftime('%Y-%m-%dT%H:%M:%S')})"
        self._client.create_schedule(
            Name=schedule_name,
            GroupName=group_name,
            ScheduleExpression=at_expression,
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            Target={
                "Arn": lambda_arn,
                "RoleArn": role_arn,
                "Input": json.dumps(payload.to_dict()),
            },
        )
