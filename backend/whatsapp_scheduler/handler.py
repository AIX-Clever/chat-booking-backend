"""
whatsapp_scheduler Lambda — Entry Point

This file is intentionally thin: it only handles the AWS Lambda contract
(parsing SQS/SNS records, building the BookingEvent, wiring dependencies)
and delegates ALL logic to the application use case.

Architecture layers
-------------------
handler.py  (this file)          ← AWS Lambda entry point
  └─ application/                ← Use case orchestration (no AWS SDK)
       └─ domain/                ← Pure Python entities & ports
  └─ infrastructure/             ← AWS SDK adapters (boto3)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.utils import Logger

from .application.schedule_notifications import ScheduleNotificationsUseCase
from .domain.models import BookingEvent
from .infrastructure.eventbridge_scheduler import EventBridgeNotificationScheduler
from .infrastructure.sns_publisher import SnsNotificationPublisher

logger = Logger()

# ---------------------------------------------------------------------------
# Dependency wiring (singleton per container)
# ---------------------------------------------------------------------------
_tenant_repo = DynamoDBTenantRepository()
_publisher = SnsNotificationPublisher()
_scheduler = EventBridgeNotificationScheduler()
_use_case = ScheduleNotificationsUseCase(
    tenant_repository=_tenant_repo,
    publisher=_publisher,
    scheduler=_scheduler,
)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda entry point — parse records and delegate to use case."""
    processed = 0
    errors = 0

    for record in event.get("Records", []):
        try:
            payload = _parse_record(record)
            if payload is None:
                continue
            if payload.get("event_type") != "BOOKING_CONFIRMED":
                logger.info("Skipping non-BOOKING_CONFIRMED event", event_type=payload.get("event_type"))
                continue

            booking_event = _to_booking_event(payload)
            if booking_event is None:
                continue

            _use_case.execute(booking_event)
            processed += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Error processing record", error=str(exc))
            errors += 1

    logger.info("whatsapp_scheduler completed", processed=processed, errors=errors)
    return {"processed": processed, "errors": errors}


# ---------------------------------------------------------------------------
# Parsing helpers (infrastructure concern — stay in handler)
# ---------------------------------------------------------------------------

def _parse_record(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse SNS-wrapped or raw SQS body into a dict."""
    try:
        body = json.loads(record.get("body", "{}"))
        if "Message" in body:
            return json.loads(body["Message"])
        return body
    except (json.JSONDecodeError, KeyError):
        return None


def _to_booking_event(payload: Dict[str, Any]) -> Optional[BookingEvent]:
    """Map a raw dict from SNS into a domain BookingEvent."""
    tenant_id = payload.get("tenant_id", "")
    customer_phone = payload.get("customer_phone", "")
    booking_start_iso = payload.get("booking_start_time", "")

    if not tenant_id or not booking_start_iso:
        logger.error("Missing required fields in payload", payload=str(payload))
        return None

    booking_start_dt = _parse_iso(booking_start_iso)
    if booking_start_dt is None:
        logger.error("Could not parse booking_start_time", value=booking_start_iso)
        return None

    return BookingEvent(
        tenant_id=tenant_id,
        booking_id=payload.get("booking_id", "unknown"),
        booking_start_time=booking_start_dt,
        customer_phone=customer_phone,
        customer_name=payload.get("customer_name", ""),
        service_name=payload.get("service_name", "tu servicio"),
    )


def _parse_iso(iso_string: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
