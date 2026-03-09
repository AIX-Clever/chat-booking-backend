import json
import os
import urllib.parse
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key

from shared.utils import Logger

logger = Logger()

# Initialize services outside handler for container reuse
dynamodb_resource = boto3.resource("dynamodb")
WHATSAPP_MESSAGES_TABLE = os.environ.get("WHATSAPP_MESSAGES_TABLE", "ChatBooking-WhatsappMessages")
whatsapp_table = dynamodb_resource.Table(WHATSAPP_MESSAGES_TABLE)

# Static response for incoming messages
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
        # If it's not a status update, it's an inbound message from the user
        from_number = payload.get("From")
        body_text = payload.get("Body", "")
        
        if from_number:
            logger.info("Received incoming message", from_number=from_number, body=body_text)
            # We return a TwiML response to send back the static automatic reply
            twiml = generate_twiml_response(STATIC_RESPONSE)
            
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "text/xml",
                },
                "body": twiml
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
