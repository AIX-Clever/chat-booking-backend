import json
import os
import urllib.parse
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key

from shared.utils import Logger
from shared.infrastructure.dynamodb_repositories import (
    DynamoDBWaitingListRepository,
    DynamoDBBookingRepository,
    DynamoDBTenantRepository,
    DynamoDBProviderRepository,
    DynamoDBServiceRepository,
    DynamoDBClientRepository,
)
from shared.infrastructure.availability_repository import DynamoDBAvailabilityRepository
from shared.application.waitlist_service import WaitlistService
from shared.application.booking_service import BookingService
from shared.domain.entities import TenantId

logger = Logger()

# Initialize services outside handler for container reuse
dynamodb_resource = boto3.resource("dynamodb")
sqs_client = boto3.client("sqs")

WHATSAPP_MESSAGES_TABLE = os.environ.get("WHATSAPP_MESSAGES_TABLE", "ChatBooking-WhatsappMessages")
WAITLIST_PENDING_TABLE = os.environ.get("WAITLIST_PENDING_TABLE", "ChatBooking-WaitlistPending")
WHATSAPP_SENDER_QUEUE_URL = os.environ.get("WHATSAPP_SENDER_QUEUE_URL", "")

whatsapp_table = dynamodb_resource.Table(WHATSAPP_MESSAGES_TABLE)
waitlist_pending_table = dynamodb_resource.Table(WAITLIST_PENDING_TABLE)

waitlist_repo = DynamoDBWaitingListRepository()
booking_repo = DynamoDBBookingRepository()
tenant_repo = DynamoDBTenantRepository()
provider_repo = DynamoDBProviderRepository()
service_repo = DynamoDBServiceRepository()
availability_repo = DynamoDBAvailabilityRepository()
client_repo = DynamoDBClientRepository()
waitlist_service = WaitlistService(waitlist_repo, tenant_repo, provider_repo, availability_repo)
booking_service = BookingService(booking_repo, service_repo, provider_repo, tenant_repo)

# Static response for incoming messages that aren't waitlist replies
STATIC_RESPONSE = os.environ.get("WHATSAPP_STATIC_RESPONSE", "Este es un canal exclusivo para el envío de recordatorios médicos. Por el momento, no procesamos respuestas o mensajes por este medio.")

def update_message_status(message_sid: str, status: str, error_code: str = None, error_message: str = None):
    """Update message status in DynamoDB"""
    try:
        # First query the GSI to find the tenantId
        response = whatsapp_table.query(
            IndexName='messageId-index',
            KeyConditionExpression=Key('messageId').eq(message_sid)
        )
        items = response.get('Items', [])
        if not items:
            logger.warning("Message not found in DB for status update", message_sid=message_sid)
            return
            
        tenant_id = items[0]['tenantId']

        now = datetime.now(timezone.utc).isoformat()
        update_expr = "SET #status = :s, updatedAt = :u"
        expr_names = {"#status": "status"}
        expr_values = {":s": status, ":u": now}

        if error_code:
            update_expr += ", error_code = :ec, error_message = :em"
            expr_values[":ec"] = error_code
            expr_values[":em"] = error_message

        whatsapp_table.update_item(
            Key={"tenantId": tenant_id, "messageId": message_sid},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        logger.info("Updated message status", message_sid=message_sid, status=status)
    except Exception as e:
        logger.error("Failed to update message status", error=str(e), message_sid=message_sid)

def generate_twiml_response(text: str) -> str:
    """Generate basic TwiML response"""
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{text}</Message></Response>'


def _get_waitlist_pending(client_phone: str) -> dict | None:
    """Return the pending waitlist context for a phone number, or None."""
    try:
        response = waitlist_pending_table.get_item(
            Key={"clientPhone": client_phone}
        )
        return response.get("Item")
    except Exception as e:
        logger.error("Failed to get waitlist pending context", error=str(e))
        return None


def _delete_waitlist_pending(client_phone: str) -> None:
    try:
        waitlist_pending_table.delete_item(Key={"clientPhone": client_phone})
    except Exception as e:
        logger.error("Failed to delete waitlist pending context", error=str(e))


def _is_affirmative(text: str) -> bool:
    normalized = text.lower().strip()
    return normalized in {"si", "sí", "yes", "s", "ok", "dale", "confirmo", "confirmar", "acepto"}


def _is_negative(text: str) -> bool:
    normalized = text.lower().strip()
    return normalized in {"no", "n", "nop", "nope", "cancel", "cancelar", "rechazar", "rechazo"}


def _create_booking_from_waitlist(client_phone: str, tenant_id_str: str, booking_id: str) -> None:
    """Create a real Booking when a waitlist candidate accepts via WhatsApp."""
    if not booking_id:
        logger.warning("No bookingId in waitlist context, skipping booking creation")
        return
    try:
        tenant_id = TenantId(tenant_id_str)

        # 1. Load the soft-locked booking to get slot data
        original = booking_repo.get_by_id(tenant_id, booking_id)
        if not original:
            logger.error("Soft-locked booking not found", booking_id=booking_id)
            return

        # 2. Look up the client by phone (phone-index GSI)
        client_info = client_repo.find_by_phone(tenant_id, client_phone)
        if not client_info:
            # Fallback: strip whatsapp: prefix and retry
            plain_phone = client_phone.replace("whatsapp:", "")
            client_info = client_repo.find_by_phone(tenant_id, plain_phone)
        if not client_info:
            logger.error("Client not found for phone, skipping booking creation", phone=client_phone)
            return

        # 3. Create the new booking using the same slot
        booking_service.create_booking(
            tenant_id=tenant_id,
            service_id=original.service_id,
            provider_id=original.provider_id,
            start=original.start_time,
            end=original.end_time,
            client_first_name=client_info.first_name,
            client_last_name=client_info.last_name,
            client_email=client_info.email,
            client_phone=client_info.phone,
            ignore_availability=True,  # Slot already reserved via soft lock
        )
        logger.info("Booking created from waitlist acceptance", phone=client_phone, booking_id=booking_id)
    except Exception as e:
        logger.error("Failed to create booking from waitlist", error=str(e), booking_id=booking_id)


def _handle_waitlist_reply(client_phone: str, body_text: str, pending: dict) -> str:
    """Process a waitlist candidate's reply. Returns the TwiML message text."""
    tenant_id_str = pending.get("tenantId", "")
    waiting_list_id = pending.get("waitingListId", "")
    booking_id = pending.get("bookingId", "")
    service_id = pending.get("serviceId", "")

    if _is_affirmative(body_text):
        _delete_waitlist_pending(client_phone)
        try:
            waitlist_service.mark_booked(TenantId(tenant_id_str), waiting_list_id)
        except Exception as e:
            logger.error("Failed to mark waitlist entry as booked", error=str(e))
        logger.info("Waitlist candidate accepted", phone=client_phone, waiting_list_id=waiting_list_id)
        _create_booking_from_waitlist(client_phone, tenant_id_str, booking_id)
        return (
            "¡Perfecto! Tu reserva ha sido confirmada. "
            "Recibirás un recordatorio antes de tu cita."
        )

    if _is_negative(body_text):
        _delete_waitlist_pending(client_phone)
        try:
            waitlist_service.mark_declined(TenantId(tenant_id_str), waiting_list_id)
        except Exception as e:
            logger.error("Failed to mark waitlist entry as declined", error=str(e))

        # Find next candidate and notify them
        _advance_waitlist(tenant_id_str, service_id, booking_id)
        logger.info("Waitlist candidate declined", phone=client_phone, waiting_list_id=waiting_list_id)
        return "Entendido, hemos cancelado tu reserva en la lista de espera. ¡Hasta pronto!"

    # Unrecognized reply — ask again
    return "Por favor responde *Sí* para confirmar la hora o *No* para rechazarla."


def _advance_waitlist(tenant_id_str: str, service_id: str, booking_id: str) -> None:
    """Find the next PENDING candidate and send them a WhatsApp notification."""
    if not WHATSAPP_SENDER_QUEUE_URL:
        logger.warning("WHATSAPP_SENDER_QUEUE_URL not set, cannot advance waitlist")
        return
    try:
        tenant_id = TenantId(tenant_id_str)
        candidate = waitlist_service.process_cancellation(tenant_id, service_id)
        if not candidate:
            logger.info("No more waitlist candidates for service", service_id=service_id)
            return  # Soft lock expires naturally via softLockExpiresAt TTL

        waitlist_service.mark_contacted(tenant_id, candidate.waiting_list_id)
        if booking_id:
            booking_repo.soft_lock(tenant_id, booking_id)

        message = {
            "type": "waitlist_notification",
            "tenant_id": tenant_id_str,
            "to": candidate.client_id,
            "waitingListId": candidate.waiting_list_id,
            "bookingId": booking_id,
            "serviceId": service_id,
            "message": (
                "¡Buenas noticias! Se ha liberado una hora para "
                "el servicio que solicitaste. ¿Te gustaría tomarla?"
            ),
        }
        sqs_client.send_message(
            QueueUrl=WHATSAPP_SENDER_QUEUE_URL,
            MessageBody=json.dumps(message),
        )
        logger.info("Advanced waitlist to next candidate", candidate=candidate.client_id)
    except Exception as e:
        logger.error("Failed to advance waitlist", error=str(e))


def lambda_handler(event, context):
    """
    Webhook handler for Twilio WhatsApp (Status callbacks & Incoming messages).
    """
    logger.info("Received Whatsapp Webhook", event=event)

    try:
        # Twilio sends x-www-form-urlencoded body. If event.body is base64, AWS API GW might encode it.
        body = event.get("body", "")
        is_base64 = event.get("isBase64Encoded", False)
        
        if is_base64:
            import base64
            body = base64.b64decode(body).decode("utf-8")
            
        # Parse application/x-www-form-urlencoded
        parsed_body = urllib.parse.parse_qs(body)
        
        # Flatten the arrays from parse_qs (it returns values as lists)
        payload = {k: v[0] for k, v in parsed_body.items()}
        
        message_sid = payload.get("MessageSid")
        message_status = payload.get("MessageStatus")
        
        # 1. Handle Status Callback
        if message_status:
            error_code = payload.get("ErrorCode")
            error_msg = payload.get("ErrorMessage")
            
            if message_sid:
                update_message_status(message_sid, message_status, error_code, error_msg)
            
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"status": "status_updated"}),
            }
            
        # 2. Handle Incoming Message
        from_number = payload.get("From", "")
        body_text = payload.get("Body", "").strip()

        if from_number:
            logger.info("Received incoming message", from_number=from_number, body=body_text)

            # Check if there's a pending waitlist response for this phone
            pending = _get_waitlist_pending(from_number)
            if pending:
                reply_text = _handle_waitlist_reply(from_number, body_text, pending)
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/xml"},
                    "body": generate_twiml_response(reply_text),
                }

            twiml = generate_twiml_response(STATIC_RESPONSE)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/xml"},
                "body": twiml,
            }
            
        # If we reach here, it's an unrecognized payload
        return {
            "statusCode": 200,
            "body": "Ok"
        }

    except Exception as e:
        logger.error("Error processing Webhook", error=str(e))
        # Always return 200 to Twilio so they don't retry failed parse parsing endlessly unless it's a real 500 issue
        # But if we raise 500, Twilio will backoff and retry.
        return {
            "statusCode": 500,
            "body": "Internal Server Error"
        }
