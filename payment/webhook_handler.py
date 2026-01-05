import json
import logging
import os
from typing import Dict, Any

from shared.infrastructure.dynamodb_repositories import DynamoDBBookingRepository
from shared.infrastructure.payment_factory import PaymentGatewayFactory
from shared.domain.entities import TenantId, BookingStatus, PaymentStatus
from shared.infrastructure.notifications import EmailService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

booking_repo = DynamoDBBookingRepository()
email_service = EmailService()

def lambda_handler(event: Dict[str, Any], context):
    """
    Generic Webhook Router for Payments.
    Path: /webhooks/payment/{provider}
    """
    try:
        # 1. Router Logic: Get Provider from Path or Env
        # If using Function URL, path params might not be parsed standardly if not proxy.
        # Assuming we pass provider in env var if separate lambdas, 
        # OR we parse `rawPath` if using a single Function URL.
        # Let's assume this lambda is deployed "per provider" or we use a path extraction.
        # Simplest: Look at path parameters if coming from API Gateway, or rawPath.
        
        provider = 'stripe' # Default for now if standard.
        
        raw_path = event.get('rawPath', '')
        if '/stripe' in raw_path:
            provider = 'stripe'
        elif '/mercadopago' in raw_path:
            provider = 'mercadopago'
            
        logger.info(f"Received webhook for provider: {provider}")

        # 2. Get Adapter
        gateway = PaymentGatewayFactory.get_gateway_by_name(provider)
        
        # 3. Verify Signature
        headers = event.get('headers', {})
        body = event.get('body', '')
        
        # Stripe specific header
        sig_header = headers.get('stripe-signature') or headers.get('Stripe-Signature')
        webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
        
        # Verify
        event_payload = gateway.verify_webhook_signature(body, sig_header, webhook_secret)
        
        # 4. Process Event (Domain Agnostic if possible, but adapters usually return dicts)
        # We need to standardize the event loop.
        # For Stripe: 'type' == 'payment_intent.succeeded'
        
        event_type = event_payload.get('type')
        
        if event_type == 'payment_intent.succeeded':
            payment_intent = event_payload['data']['object']
            payment_id = payment_intent['id']
            metadata = payment_intent.get('metadata', {})
            booking_id = metadata.get('booking_id')
            tenant_id_str = metadata.get('tenant_id')
            
            if booking_id and tenant_id_str:
                _process_successful_payment(tenant_id_str, booking_id, payment_id)
            else:
                logger.warning("Booking ID or Tenant ID missing in metadata", extra={'metadata': metadata})
                
        return {
            'statusCode': 200,
            'body': json.dumps({'received': True})
        }
        
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': str(e)})
        }

def _process_successful_payment(tenant_id_str: str, booking_id: str, payment_id: str):
    tenant_id = TenantId(tenant_id_str)
    booking = booking_repo.get_by_id(tenant_id, booking_id)
    
    if not booking:
        logger.error(f"Booking not found: {booking_id}")
        return

    if booking.payment_status == PaymentStatus.PAID:
        logger.info(f"Booking {booking_id} already paid.")
        return

    # Update Booking
    booking.payment_status = PaymentStatus.PAID
    # Could imply status=CONFIRMED if it was pending payment to confirm
    if booking.status == BookingStatus.PENDING:
        booking.status = BookingStatus.CONFIRMED
        
    booking_repo.update(booking)
    logger.info(f"Booking {booking_id} marked as PAID via {payment_id}")
    
    # Send Notification (Payment Received) - Optional
    # We already sent "Booking Confirmed" in create? 
    # If create was PENDING (unpaid), maybe we didn't send email yet?
    # In previous step, create_booking sends email immediately. 
    # TODO: Refine email logic to only send when PAID? 
    # For now, let's keep it simple.
