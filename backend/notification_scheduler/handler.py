"""
notification_scheduler Lambda — Entry Point

Two execution modes:
  1. BOOKING_CONFIRMED (via SNS → SQS): schedules future email/SMS reminders
  2. REMINDER_FIRE (direct EventBridge invoke): sends the pre-built reminder now

Architecture layers
-------------------
handler.py  (this file)          ← AWS Lambda entry point
  └─ application/                ← Use case orchestration (no AWS SDK)
       └─ domain/                ← Pure Python entities & ports
  └─ infrastructure/             ← AWS SDK adapters (boto3)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.utils import Logger

from .application.schedule_reminders import ScheduleRemindersUseCase
from .domain.models import BookingEvent, ReminderPayload
from .infrastructure.eventbridge_scheduler import EventBridgeReminderScheduler

logger = Logger()

_tenant_repo = DynamoDBTenantRepository()
_scheduler = EventBridgeReminderScheduler()
_use_case = ScheduleRemindersUseCase(
    tenant_repository=_tenant_repo,
    scheduler=_scheduler,
)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # Mode 2: EventBridge direct invoke (REMINDER_FIRE)
    if event.get("event_type") == "REMINDER_FIRE":
        return _handle_fire(event)

    # Mode 1: SQS records (BOOKING_CONFIRMED via SNS → SQS)
    processed = 0
    errors = 0
    for record in event.get("Records", []):
        try:
            payload = _parse_record(record)
            if payload is None:
                continue
            if payload.get("event_type") != "BOOKING_CONFIRMED":
                continue

            booking_event = _to_booking_event(payload)
            if booking_event is None:
                continue

            lambda_arn = getattr(context, "invoked_function_arn", "")
            _use_case.execute(booking_event, lambda_arn=lambda_arn)
            processed += 1
        except Exception as exc:
            logger.error("Error scheduling reminders", error=str(exc))
            errors += 1

    logger.info("notification_scheduler completed", processed=processed, errors=errors)
    return {"processed": processed, "errors": errors}


def _handle_fire(payload: dict) -> dict:
    """Send a pre-built reminder (email or SMS) immediately."""
    try:
        reminder = ReminderPayload.from_dict(payload)
        if reminder.channel == "email":
            _send_email(reminder)
        elif reminder.channel == "sms":
            _send_sms(reminder)
        else:
            logger.error("Unknown channel in REMINDER_FIRE", channel=reminder.channel)
        return {"sent": True, "channel": reminder.channel}
    except Exception as exc:
        logger.error("Error firing reminder", error=str(exc))
        return {"sent": False, "error": str(exc)}


def _send_email(reminder: ReminderPayload) -> None:
    sender = os.environ.get("SES_SENDER_EMAIL", "")
    if not sender or not reminder.to_address:
        logger.warning("Cannot send email reminder: missing sender or recipient")
        return
    region = os.environ.get("AWS_REGION", "us-east-2")
    ses = boto3.client("ses", region_name=region)
    ses.send_email(
        Source=sender,
        Destination={"ToAddresses": [reminder.to_address]},
        Message={
            "Subject": {"Data": reminder.subject, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": reminder.body_html, "Charset": "UTF-8"},
                "Text": {"Data": reminder.body_text, "Charset": "UTF-8"},
            },
        },
    )
    logger.info("Email reminder sent", to=reminder.to_address, rule_id=reminder.rule_id)


def _send_sms(reminder: ReminderPayload) -> None:
    if not reminder.phone_number or not reminder.message:
        logger.warning("Cannot send SMS reminder: missing phone or message")
        return
    region = os.environ.get("AWS_REGION", "us-east-2")
    sns = boto3.client("sns", region_name=region)
    sns.publish(
        PhoneNumber=reminder.phone_number,
        Message=reminder.message[:160],
        MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}},
    )
    logger.info("SMS reminder sent", phone=reminder.phone_number, rule_id=reminder.rule_id)


def _parse_record(record: dict) -> Optional[dict]:
    try:
        body = json.loads(record.get("body", "{}"))
        if "Message" in body:
            return json.loads(body["Message"])
        return body
    except (json.JSONDecodeError, KeyError):
        return None


def _to_booking_event(payload: dict) -> Optional[BookingEvent]:
    tenant_id = payload.get("tenant_id", "")
    booking_start_iso = payload.get("booking_start_time", "")

    if not tenant_id or not booking_start_iso:
        logger.error("Missing required fields", payload=str(payload))
        return None

    try:
        dt = datetime.fromisoformat(booking_start_iso.replace("Z", "+00:00"))
        booking_start = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        logger.error("Cannot parse booking_start_time", value=booking_start_iso)
        return None

    return BookingEvent(
        tenant_id=tenant_id,
        booking_id=payload.get("booking_id", "unknown"),
        booking_start_time=booking_start,
        customer_name=payload.get("customer_name", ""),
        customer_email=payload.get("customer_email", ""),
        customer_phone=payload.get("customer_phone", ""),
        service_name=payload.get("service_name", ""),
        provider_name=payload.get("provider_name", ""),
        provider_timezone=payload.get("provider_timezone", "UTC"),
    )
