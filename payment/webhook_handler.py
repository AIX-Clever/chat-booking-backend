import json
import logging
import os
import requests
import hashlib
import hmac
import boto3
from datetime import datetime
from typing import Dict, Any, Optional

from shared.infrastructure.dynamodb_repositories import DynamoDBBookingRepository
from shared.domain.entities import TenantId, BookingStatus, PaymentStatus
from shared.infrastructure.notifications import EmailService
from shared.utils import Logger

logger = logging.getLogger()
logger.setLevel(logging.INFO)

booking_repo = DynamoDBBookingRepository()
email_service = EmailService()

def lambda_handler(event: Dict[str, Any], context):
    """
    Generic Webhook Handler for multiple payment providers:
    - Mercado Pago (Default)
    - Stripe (via headers)
    - Fintoc (via headers)
    """
    try:
        headers = event.get('headers', {})
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # Determine Provider
        if 'stripe-signature' in headers_lower:
            return _handle_stripe_webhook(event)
        elif 'fintoc-signature' in headers_lower:
            return _handle_fintoc_webhook(event)
        
        # Default: Mercado Pago
        query_params = event.get('queryStringParameters', {}) or {}
        topic = query_params.get('topic') or query_params.get('type')
        resource_id = query_params.get('id') or query_params.get('data.id')

        # Fallback to body parsing if query params are empty
        if not topic or not resource_id:
            body_str = event.get('body', '{}')
            body = json.loads(body_str) if isinstance(body_str, str) else body_str
            topic = body.get('type') or body.get('topic')
            resource_id = body.get('data', {}).get('id')

        logger.info(f"Received MP Webhook: Topic={topic}, ID={resource_id}")

        if topic != 'payment' and topic != 'merchant_order':
            return {'statusCode': 200, 'body': 'Ignored topic'}

        if not _verify_mp_signature(event, resource_id):
            return {'statusCode': 200, 'body': 'Invalid Signature'}

        return process_mp_payment(resource_id)

    except Exception as e:
        logger.error(f"Webhook Error: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def _verify_mp_signature(event: Dict[str, Any], data_id: str) -> bool:
    """
    Verifies the x-signature header from Mercado Pago.
    Format: ts=[timestamp],v1=[hash]
    Manifest: id:[data.id];request-id:[x-request-id];ts:[ts];
    """
    secret = os.environ.get('MP_WEBHOOK_SECRET')
    if not secret:
        logger.warning("MP_WEBHOOK_SECRET not configured. Skipping HMAC validation.")
        return True # Fail open for dev/migration

    headers = event.get('headers', {})
    # Case insensitive header lookup
    headers_lower = {k.lower(): v for k, v in headers.items()}
    
    x_signature = headers_lower.get('x-signature')
    x_request_id = headers_lower.get('x-request-id')

    if not x_signature or not x_request_id:
        logger.warning("Missing x-signature or x-request-id headers")
        return False

    try:
        # Parse ts and v1
        parts = {}
        for part in x_signature.split(','):
            key, value = part.split('=', 1)
            parts[key.strip()] = value.strip()
            
        ts = parts.get('ts')
        v1 = parts.get('v1')

        if not ts or not v1:
            logger.warning("Invalid x-signature format")
            return False

        # Build signed template
        # Template: id:[data.id];request-id:[x-request-id];ts:[ts];
        manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"

        cyphed_signature = hmac.new(
            secret.encode(),
            manifest.encode(),
            hashlib.sha256
        ).hexdigest()

        is_valid = hmac.compare_digest(cyphed_signature, v1)
        if not is_valid:
            logger.warning(f"Signature mismatch. Calculated: {cyphed_signature}, Received: {v1}")
            
        return is_valid

    except Exception as e:
        logger.error(f"Error validating MP signature: {e}")
        return False

def _handle_stripe_webhook(event: Dict[str, Any]):
    """Routing for Stripe events"""
    from shared.infrastructure.payment_factory import PaymentGatewayFactory
    try:
        stripe_adapter = PaymentGatewayFactory.get_gateway_by_name('stripe')
        webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
        sig_header = event.get('headers', {}).get('stripe-signature')
        
        payload_data = stripe_adapter.verify_webhook_signature(
            event.get('body', ''), sig_header, webhook_secret
        )
        
        if payload_data['type'] == 'payment_intent.succeeded':
            obj = payload_data['data']['object']
            metadata = obj.get('metadata', {})
            booking_id = metadata.get('booking_id')
            tenant_id_str = metadata.get('tenant_id')
            payment_id = obj.get('id')
            
            if tenant_id_str and booking_id:
                _update_booking_status(tenant_id_str, booking_id, payment_id)
                
        return {'statusCode': 200, 'body': 'OK'}
    except Exception as e:
        logger.error(f"Stripe Webhook Error: {e}")
        return {'statusCode': 400, 'body': 'Error'}

def _handle_fintoc_webhook(event: Dict[str, Any]):
    """Routing for Fintoc events (A2A Payments)"""
    # Assuming Fintoc follows a similar pattern to MP/Stripe with metadata/reference
    try:
        body = json.loads(event.get('body', '{}'))
        event_type = body.get('type')
        data = body.get('data', {})
        
        if event_type == 'link_intent.succeeded' or event_type == 'payment_intent.succeeded':
            # Fintoc usually puts refs in 'reference' or metadata
            reference = data.get('reference')
            payment_id = data.get('id')
            
            if reference and ':' in reference:
                tenant_id_str, booking_id = reference.split(':')
                _update_booking_status(tenant_id_str, booking_id, payment_id)
                
        return {'statusCode': 200, 'body': 'OK'}
    except Exception as e:
        logger.error(f"Fintoc Webhook Error: {e}")
        return {'statusCode': 400, 'body': 'Error'}

def process_mp_payment(payment_id: str):
    mp_token = os.environ.get('MP_ACCESS_TOKEN_PROD')
    if not mp_token:
        logger.error("MP_ACCESS_TOKEN_PROD missing")
        return {'statusCode': 500, 'body': 'Config Error'}
        
    try:
        # Fetch payment status from Source of Truth (Mercado Pago API)
        url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
        headers = {"Authorization": f"Bearer {mp_token}"}
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch payment {payment_id}: {response.text}")
            return {'statusCode': 200, 'body': 'OK'} 
            
        payment_data = response.json()
        status = payment_data.get('status')
        status_detail = payment_data.get('status_detail')
        external_reference = payment_data.get('external_reference') # "tenantId:bookingId"
        
        logger.info(f"Payment {payment_id}: status={status}, detail={status_detail}, ref={external_reference}")
        
        if status == 'approved' and external_reference:
            try:
                # Format: "tenant_uuid:booking_uuid"
                parts = external_reference.split(':')
                if len(parts) == 2:
                    tenant_id_str, booking_id = parts
                    _update_booking_status(tenant_id_str, booking_id, payment_id)
                else:
                    logger.warning(f"Invalid external_reference format: {external_reference}")
            except Exception as e:
                logger.error(f"Error parsing external_reference: {e}")
                
        return {'statusCode': 200, 'body': 'OK'}
        
    except Exception as e:
        logger.error(f"Error processing payment logic: {e}")
        return {'statusCode': 500, 'body': str(e)}

def _update_booking_status(tenant_id_str: str, booking_id: str, payment_id: str):
    tenant_id = TenantId(tenant_id_str)
    booking = booking_repo.get_by_id(tenant_id, booking_id)
    
    if not booking:
        print(f"Booking NOT FOUND: {booking_id}") # Using print as fallback or Logger
        return

    if booking.payment_status == PaymentStatus.PAID:
        logger.info(f"Booking {booking_id} is already PAID. Idempotency check ok.")
        return

    # Update Booking
    booking.payment_status = PaymentStatus.PAID
    if booking.status == BookingStatus.PENDING:
        booking.status = BookingStatus.CONFIRMED
        
    booking_repo.update(booking)
    logger.info(f"Booking {booking_id} successfully marked as PAID via MP {payment_id}")
    
    # Trigger DTE Issuance (Boleta)
    _issue_dte(booking, payment_id)

def _issue_dte(booking: Any, payment_id: str):
    """
    Enqueues the DTE issuance request into SQS for asynchronous processing.
    """
    queue_url = os.environ.get('DTE_QUEUE_URL')
    if not queue_url:
        logger.warning("DTE_QUEUE_URL not configured. Skipping SQS enqueuing.")
        return

    try:
        sqs = boto3.client('sqs')
        
        # Prepare payload for the worker
        payload = {
            "bookingId": booking.booking_id,
            "tenantId": str(booking.tenant_id),
            "paymentId": payment_id,
            "amount": float(booking.total_amount) if booking.total_amount else 0,
            "customer": {
                "name": booking.customer_info.name,
                "email": booking.customer_info.email,
                "phone": booking.customer_info.phone
            },
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"Enqueuing DTE task for Booking {booking.booking_id} into SQS")
        
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(payload)
        )
        
        logger.info(f"DTE task successfully enqueued for Booking {booking.booking_id}")

    except Exception as e:
        logger.error(f"Error enqueuing DTE task to SQS: {e}", exc_info=True)
