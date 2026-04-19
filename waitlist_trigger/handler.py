"""
Waitlist Trigger Lambda Handler (Adapter Layer)

Triggered by DynamoDB Stream from the Bookings table.
Processes booking cancellations and notifies the first
eligible waitlist candidate via WhatsApp.
"""

import json
import os
import boto3

from shared.infrastructure.dynamodb_repositories import (
    DynamoDBWaitingListRepository,
    DynamoDBTenantRepository,
    DynamoDBProviderRepository,
)
from shared.infrastructure.availability_repository import (
    DynamoDBAvailabilityRepository,
)
from shared.application.waitlist_service import WaitlistService
from shared.domain.entities import TenantId
from shared.utils import Logger

logger = Logger()

# Initialize dependencies (singleton)
waitlist_repo = DynamoDBWaitingListRepository()
tenant_repo = DynamoDBTenantRepository()
provider_repo = DynamoDBProviderRepository()
availability_repo = DynamoDBAvailabilityRepository()

waitlist_service = WaitlistService(
    waitlist_repo=waitlist_repo,
    tenant_repo=tenant_repo,
    provider_repo=provider_repo,
    availability_repo=availability_repo,
)

# SQS client for WhatsApp notifications
sqs_client = boto3.client("sqs")
WHATSAPP_QUEUE_URL = os.environ.get("WHATSAPP_SENDER_QUEUE_URL", "")


def handler(event, context):
    """Process DynamoDB Stream events from Bookings table.

    Filters for MODIFY events where booking status changes to CANCELLED,
    then finds and notifies the next waitlist candidate.
    """
    processed = 0
    errors = 0

    for record in event.get("Records", []):
        try:
            # Only process MODIFY events (status changes)
            if record.get("eventName") != "MODIFY":
                continue

            new_image = record.get("dynamodb", {}).get("NewImage", {})
            old_image = record.get("dynamodb", {}).get("OldImage", {})

            new_status = _extract_string(new_image.get("status", {}))
            old_status = _extract_string(old_image.get("status", {}))

            # Only process when status changes TO CANCELLED
            if new_status != "CANCELLED" or old_status == "CANCELLED":
                continue

            tenant_id_str = _extract_string(
                new_image.get("tenantId", {})
            )
            service_id = _extract_string(
                new_image.get("serviceId", {})
            )
            provider_id = _extract_string(
                new_image.get("providerId", {})
            )

            if not tenant_id_str or not service_id:
                logger.warning(
                    "Missing tenantId or serviceId in stream record"
                )
                continue

            logger.info(
                f"Booking cancelled: tenant={tenant_id_str}, "
                f"service={service_id}, provider={provider_id}"
            )

            tenant_id = TenantId(tenant_id_str)

            # Find next waitlist candidate
            candidate = waitlist_service.process_cancellation(
                tenant_id=tenant_id,
                service_id=service_id,
                provider_id=provider_id,
            )

            if candidate:
                # Mark as contacted
                waitlist_service.mark_contacted(
                    tenant_id, candidate.waiting_list_id
                )

                # Send WhatsApp notification via SQS
                _send_whatsapp_notification(
                    tenant_id=tenant_id_str,
                    client_id=candidate.client_id,
                    service_id=service_id,
                    waiting_list_id=candidate.waiting_list_id,
                )
                processed += 1
                logger.info(
                    f"Notified waitlist candidate: "
                    f"{candidate.client_id}"
                )
            else:
                logger.info(
                    "No eligible waitlist candidates found"
                )

        except Exception as e:
            errors += 1
            logger.error(
                f"Error processing stream record: {e}"
            )

    logger.info(
        f"Waitlist trigger completed: "
        f"{processed} notified, {errors} errors"
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "processed": processed,
            "errors": errors,
        }),
    }


def _extract_string(dynamo_value: dict) -> str:
    """Extract string value from DynamoDB Stream format."""
    if isinstance(dynamo_value, dict):
        return dynamo_value.get("S", "")
    return str(dynamo_value) if dynamo_value else ""


def _send_whatsapp_notification(
    tenant_id: str,
    client_id: str,
    service_id: str,
    waiting_list_id: str,
) -> None:
    """Send a WhatsApp notification to the waitlist candidate."""
    if not WHATSAPP_QUEUE_URL:
        logger.warning(
            "WHATSAPP_SENDER_QUEUE_URL not configured, "
            "skipping notification"
        )
        return

    message = {
        "type": "waitlist_notification",
        "tenantId": tenant_id,
        "clientId": client_id,
        "serviceId": service_id,
        "waitingListId": waiting_list_id,
        "message": (
            "¡Buenas noticias! Se ha liberado una hora para "
            "el servicio que solicitaste. ¿Te gustaría tomarla?"
        ),
    }

    try:
        sqs_client.send_message(
            QueueUrl=WHATSAPP_QUEUE_URL,
            MessageBody=json.dumps(message),
        )
    except Exception as e:
        logger.error(f"Error sending WhatsApp notification: {e}")
