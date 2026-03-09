import json
import os
import urllib.request
import urllib.parse
import base64
from typing import Dict, Any
import boto3
from datetime import datetime, timezone

from shared.domain.entities import TenantId
from shared.limit_service import TenantLimitService
from shared.metrics import MetricsService
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.utils import Logger

logger = Logger()

# Initialize services outside handler for container reuse
dynamodb_resource = boto3.resource("dynamodb")
tenant_repo = DynamoDBTenantRepository()
metrics_service = MetricsService()
limit_service = TenantLimitService(tenant_repo, metrics_service)

WHATSAPP_MESSAGES_TABLE = os.environ.get("WHATSAPP_MESSAGES_TABLE", "ChatBooking-WhatsappMessages")
whatsapp_table = dynamodb_resource.Table(WHATSAPP_MESSAGES_TABLE)

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
# Usually WhatsApp numbers in Twilio start with "whatsapp:"
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "whatsapp:+14155238886") 


def send_twilio_whatsapp(to_number: str, message_body: str, tenant) -> Dict[str, Any]:
    """Sends a WhatsApp message via Twilio API."""
    settings = tenant.settings or {}
    twilio_sid = settings.get("twilio_account_sid", TWILIO_ACCOUNT_SID)
    twilio_auth = settings.get("twilio_auth_token", TWILIO_AUTH_TOKEN)
    twilio_number = settings.get("twilio_whatsapp_number", TWILIO_PHONE_NUMBER)

    if not twilio_sid or not twilio_auth:
        logger.error("Twilio credentials are not set for tenant and no fallback.", tenant_id=tenant.tenant_id.value)
        raise ValueError("Missing Twilio credentials")

    # Format numbers
    to_formatted = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
    from_formatted = twilio_number if twilio_number.startswith("whatsapp:") else f"whatsapp:{twilio_number}"

    data = urllib.parse.urlencode({
        "To": to_formatted,
        "From": from_formatted,
        "Body": message_body,
    }).encode("utf-8")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
    
    # Basic Auth
    auth_str = f"{twilio_sid}:{twilio_auth}"
    auth_header = "Basic " + base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            return response_data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error("Twilio API HTTPError", error=error_body, status_code=e.code)
        # We can raise a specific error that won't be retried if it's auth failure etc.
        if e.code in [400, 401, 403]:
            # Do not retry for specific client/auth errors to prevent infinite loops in SQS DLQ bouncing
            raise Exception(f"Twilio Fatal Error: {error_body}")
        raise
    except Exception as e:
        logger.error("Twilio API Error", error=str(e))
        raise

def save_message_record(tenant_id: str, message_id: str, to: str, provider: str, raw_response: dict):
    """Saves the message state to DynamoDB"""
    try:
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "tenantId": tenant_id,
            "messageId": message_id,
            "destinationPhone": to,
            "provider": provider,
            "status": "queued", # Initial status from Twilio
            "createdAt": now,
            "updatedAt": now,
            "raw_response": json.dumps(raw_response)
        }
        whatsapp_table.put_item(Item=item)
    except Exception as e:
        logger.error("Failed to save whatsapp message record", error=str(e), tenant_id=tenant_id)


def lambda_handler(event, context):
    """
    SQS Event Handler for sending WhatsApp messages.
    """
    logger.info("Received SQS event for whatsapp_sender", record_count=len(event.get("Records", [])))
    
    for record in event.get("Records", []):
        try:
            body_str = record.get("body", "{}")
            body = json.loads(body_str)
            
            # If triggered via SNS -> SQS, the actual message might be wrapped in 'Message'
            if "Message" in body and "TopicArn" in body:
                body = json.loads(body["Message"])

            tenant_id_str = body.get("tenant_id")
            to_number = body.get("to")
            message_text = body.get("message")

            if not tenant_id_str or not to_number or not message_text:
                logger.error("Invalid message payload", payload=body)
                continue # Skip this message

            tenant_id = TenantId(tenant_id_str)

            tenant = tenant_repo.get_by_id(tenant_id)
            if not tenant:
                logger.error("Tenant not found", tenant_id=tenant_id_str)
                continue

            # 1. Quota Validation
            if not limit_service.check_can_send_message(tenant_id):
                logger.warning("Tenant exceeded message quota. Aborting WhatsApp send.", tenant_id=tenant_id_str)
                # We do not raise an exception, so it's not retried
                metrics_service.increment_error(tenant_id_str, "whatsapp_quota_exceeded")
                continue

            # 2. Send Message via Twilio
            logger.info("Sending WhatsApp message", tenant_id=tenant_id_str, to=to_number)
            response = send_twilio_whatsapp(to_number, message_text, tenant)
            
            # Twilio's Message SID
            message_sid = response.get("sid", "unknown_sid")
            
            # 3. Save Record
            save_message_record(
                tenant_id=tenant_id_str,
                message_id=message_sid,
                to=to_number,
                provider="twilio",
                raw_response=response
            )

            # 4. Update usage quotas
            metrics_service.increment_message(tenant_id_str)
            # Track specifically whatsapp messages as well
            metrics_service._atomic_increment(
                tenant_id_str, 
                f"MONTH#{metrics_service._get_periods()['month']}", 
                "whatsappMessages"
            )

            logger.info("WhatsApp message dispatched successfully", message_sid=message_sid, tenant_id=tenant_id_str)

        except Exception as e:
            logger.error("Error processing SQS record", error=str(e), record=str(record))
            # Reraise to let SQS retry or move it to DLQ
            raise e
