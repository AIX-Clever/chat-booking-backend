"""
Infrastructure Adapter — SNS Publisher

Implements INotificationPublisher using AWS SNS.
"""
import json
import os

import boto3

from ..domain.models import INotificationPublisher


class SnsNotificationPublisher(INotificationPublisher):
    """Adapter: publishes immediate WhatsApp send events to SNS."""

    def __init__(self, topic_arn: str | None = None) -> None:
        self._topic_arn = topic_arn or os.environ.get("WHATSAPP_SNS_TOPIC_ARN", "")
        self._client = boto3.client("sns")

    def publish(
        self,
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
            "customer_phone": customer_phone,
            "message_body": message_body,
            "rule_id": rule_id,
        }
        self._client.publish(
            TopicArn=self._topic_arn,
            Message=json.dumps(payload),
            MessageAttributes={
                "event_type": {"DataType": "String", "StringValue": "WHATSAPP_SEND"},
            },
        )
