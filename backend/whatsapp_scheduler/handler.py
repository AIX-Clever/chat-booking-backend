"""whatsapp_scheduler Lambda — schedules timed WhatsApp notifications via EventBridge Scheduler.

Triggered by: SNS Topic (ChatBooking-WhatsappNotificationTopic)
Filter: event_type = BOOKING_CONFIRMED

For each active notification rule in tenant.settings.notification_rules:
  - 'on_booking'   → publishes immediately to the same SNS topic (whatsapp_sender picks it up)
  - 'hours_before' → creates an EventBridge Scheduler one-time schedule that fires
                     at (booking_start_time - hours_before) and publishes to SNS
"""
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import boto3

from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.utils import Logger

logger = Logger()

# ---------------------------------------------------------------------------
# Clients (outside handler for container reuse)
# ---------------------------------------------------------------------------
tenant_repo = DynamoDBTenantRepository()
scheduler_client = boto3.client("scheduler")
sns_client = boto3.client("sns")

SNS_TOPIC_ARN = os.environ.get("WHATSAPP_SNS_TOPIC_ARN", "")
SCHEDULER_GROUP_NAME = os.environ.get("SCHEDULER_GROUP_NAME", "ChatBooking-WhatsappSchedules")
SCHEDULER_ROLE_ARN = os.environ.get("SCHEDULER_ROLE_ARN", "")

# Default rules applied when a tenant has no custom configuration
DEFAULT_RULES: List[Dict[str, Any]] = [
    {"id": "on_booking",  "name": "Confirmación al reservar", "trigger": "on_booking",   "active": True,  "hours_before": None},
    {"id": "remind_24h",  "name": "Recordatorio 24h antes",   "trigger": "hours_before", "active": True,  "hours_before": 24},
    {"id": "remind_2h",   "name": "Recordatorio 2h antes",    "trigger": "hours_before", "active": False, "hours_before": 2},
]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process BOOKING_CONFIRMED SNS events and schedule WhatsApp notifications."""
    processed = 0
    errors = 0

    for record in event.get("Records", []):
        try:
            payload = _parse_record(record)
            if payload is None or payload.get("event_type") != "BOOKING_CONFIRMED":
                logger.info("Skipping non-BOOKING_CONFIRMED event")
                continue
            _process_booking(payload)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Error processing record", error=str(exc))
            errors += 1

    logger.info("whatsapp_scheduler completed", processed=processed, errors=errors)
    return {"processed": processed, "errors": errors}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _process_booking(payload: Dict[str, Any]) -> None:
    tenant_id: str = payload["tenant_id"]
    booking_start_iso: str = payload["booking_start_time"]  # ISO 8601 UTC
    customer_phone: str = payload.get("customer_phone", "")
    customer_name: str = payload.get("customer_name", "")
    service_name: str = payload.get("service_name", "")
    booking_id: str = payload.get("booking_id", str(uuid.uuid4()))

    if not customer_phone:
        logger.warn("No customer_phone in payload, skipping", tenant_id=tenant_id)
        return

    # Load tenant and its notification rules
    tenant = tenant_repo.get_by_id(tenant_id)
    if not tenant:
        logger.error("Tenant not found", tenant_id=tenant_id)
        return

    settings: Dict[str, Any] = tenant.settings or {}
    rules: List[Dict[str, Any]] = settings.get("notification_rules", DEFAULT_RULES)

    booking_start_dt = _parse_iso(booking_start_iso)

    for rule in rules:
        if not rule.get("active", False):
            continue
        try:
            _dispatch_rule(
                rule=rule,
                tenant_id=tenant_id,
                booking_id=booking_id,
                booking_start_dt=booking_start_dt,
                customer_phone=customer_phone,
                customer_name=customer_name,
                service_name=service_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to dispatch rule", rule_id=rule.get("id"), error=str(exc))


def _dispatch_rule(
    rule: Dict[str, Any],
    tenant_id: str,
    booking_id: str,
    booking_start_dt: Optional[datetime],
    customer_phone: str,
    customer_name: str,
    service_name: str,
) -> None:
    trigger = rule.get("trigger")
    rule_id = rule.get("id", "unknown")
    message_body = _build_message(rule, customer_name, service_name, booking_start_dt)

    sns_payload = {
        "event_type": "WHATSAPP_SEND",
        "tenant_id": tenant_id,
        "booking_id": booking_id,
        "customer_phone": customer_phone,
        "message_body": message_body,
        "rule_id": rule_id,
    }

    if trigger == "on_booking":
        # Publish immediately to SNS so whatsapp_sender picks it up
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(sns_payload),
            MessageAttributes={
                "event_type": {"DataType": "String", "StringValue": "WHATSAPP_SEND"},
            },
        )
        logger.info("Immediate notification sent", rule_id=rule_id, tenant_id=tenant_id)

    elif trigger == "hours_before" and booking_start_dt:
        hours: int = rule.get("hours_before", 24)
        fire_at: datetime = booking_start_dt - timedelta(hours=hours)
        now_utc = datetime.now(timezone.utc)

        if fire_at <= now_utc:
            logger.warn("Scheduled time is in the past, skipping", rule_id=rule_id, fire_at=fire_at.isoformat())
            return

        schedule_name = f"wa-{booking_id}-{rule_id}"[:64]
        _create_eventbridge_schedule(
            schedule_name=schedule_name,
            fire_at=fire_at,
            sns_payload=sns_payload,
        )
        logger.info("Scheduled notification", rule_id=rule_id, fire_at=fire_at.isoformat())


def _create_eventbridge_schedule(
    schedule_name: str,
    fire_at: datetime,
    sns_payload: Dict[str, Any],
) -> None:
    """Creates a one-time EventBridge Scheduler schedule that publishes to SNS."""
    # Format: yyyy-MM-ddTHH:mm:ss (no timezone offset, EventBridge uses UTC)
    at_expression = f"at({fire_at.strftime('%Y-%m-%dT%H:%M:%S')})"

    scheduler_client.create_schedule(
        Name=schedule_name,
        GroupName=SCHEDULER_GROUP_NAME,
        ScheduleExpression=at_expression,
        ScheduleExpressionTimezone="UTC",
        FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE",  # auto-cleanup after firing
        Target={
            "Arn": SNS_TOPIC_ARN,
            "RoleArn": SCHEDULER_ROLE_ARN,
            "Input": json.dumps(sns_payload),
        },
    )


# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

def _build_message(
    rule: Dict[str, Any],
    customer_name: str,
    service_name: str,
    booking_start_dt: Optional[datetime],
) -> str:
    trigger = rule.get("trigger")
    name_part = f"Hola {customer_name}" if customer_name else "Hola"
    time_part = (
        booking_start_dt.strftime("%-d de %B a las %H:%M") if booking_start_dt else "tu cita"
    )

    if trigger == "on_booking":
        return (
            f"{name_part}, tu reserva de {service_name} ha sido confirmada para el {time_part}. "
            "¡Te esperamos!"
        )
    elif trigger == "hours_before":
        hours = rule.get("hours_before", 24)
        if hours >= 24:
            label = f"{hours // 24} día(s)"
        else:
            label = f"{hours} hora(s)"
        return (
            f"{name_part}, te recordamos que tienes {service_name} en {label}. "
            f"📅 {time_part}. ¡Te esperamos!"
        )
    return f"{name_part}, tienes una cita próximamente."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_record(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse SNS → SQS or direct SNS record formats."""
    try:
        body = record.get("body", "{}")
        # Direct SNS record has 'Message' key
        outer = json.loads(body)
        if "Message" in outer:
            return json.loads(outer["Message"])
        return outer
    except (json.JSONDecodeError, KeyError):
        return None


def _parse_iso(iso_string: str) -> Optional[datetime]:
    """Parse ISO 8601 string to timezone-aware datetime (UTC)."""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None
