import json
import logging
import os
import requests
from typing import Any, Dict

from shared.infrastructure.dynamodb_repositories import DynamoDBBookingRepository
from shared.domain.entities import TenantId

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

booking_repo = DynamoDBBookingRepository()

def lambda_handler(event: Dict[str, Any], context):
    """
    SQS Worker for DTE Issuance.
    Processes messages from the queue, calls the LibreDTE microservice,
    and updates the booking with the generated DTE info.
    """
    for record in event.get('Records', []):
        try:
            body = json.loads(record['body'])
            booking_id = body.get('bookingId')
            payment_id = body.get('paymentId')
            tenant_id_str = body.get('tenantId')
            
            if not tenant_id_str or (not booking_id and not payment_id):
                logger.error(f"Invalid message payload: {body}")
                continue

            msg_type = "Booking" if booking_id else "Subscription"
            logger.info(f"Processing DTE issuance for {msg_type}: {booking_id or payment_id}")
            
            # Call LibreDTE Microservice
            _process_dte_issuance(body)
            
        except Exception as e:
            logger.error(f"Error processing SQS record: {e}", exc_info=True)
            # Re-raising so SQS can trigger a retry
            raise e

    return {"statusCode": 200, "body": "Success"}

def _process_dte_issuance(payload: Dict[str, Any]):
    """
    Communicates with the LibreDTE microservice and updates the database.
    """
    dte_api_url = os.environ.get('DTE_API_URL')
    if not dte_api_url:
        logger.error("DTE_API_URL not configured in worker")
        return

    booking_id = payload.get('bookingId')
    payment_id = payload.get('paymentId')
    tenant_id_str = payload.get('tenantId') # Emisor
    subscription_tenant_id = payload.get('subscription_tenant_id') # Customer (for subscriptions)
    tenant_id = TenantId(tenant_id_str)

    try:
        # 1. Call LibreDTE Microservice
        response = requests.post(
            f"{dte_api_url.rstrip('/')}/emitir-dte", 
            json=payload,
            timeout=25
        )
        
        if response.status_code not in [200, 201, 202]:
            error_msg = f"DTE Microservice failed ({response.status_code}): {response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)

        result = response.json()
        dte_folio = result.get('folio')
        dte_pdf_url = result.get('pdfUrl')

        if not dte_folio:
            logger.warning(f"DTE Microservice success but NO FOLIO returned: {result}")
            return

        # 2. Update Database
        if booking_id:
            # Update Booking
            booking = booking_repo.get_by_id(tenant_id, booking_id)
            if booking:
                booking.dte_folio = str(dte_folio)
                booking.dte_pdf_url = dte_pdf_url
                booking_repo.update(booking)
                logger.info(f"Booking {booking_id} updated with DTE Folio {dte_folio}")
            else:
                logger.error(f"Booking {booking_id} NOT FOUND in repository during update")
        
        elif payment_id:
            # Update Subscription Payment (Invoice)
            import boto3
            from shared.subscriptions.config import SubscriptionConfig
            
            dynamodb = boto3.resource('dynamodb')
            table = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)
            
            # Use subscription_tenant_id if provided, else emisor tenant_id_str
            target_tenant = subscription_tenant_id or tenant_id_str

            table.update_item(
                Key={
                    'tenantId': target_tenant,
                    'subscriptionId': f"PAYMENT#{payment_id}"
                },
                UpdateExpression="set dteFolio = :f, dtePdfUrl = :u",
                ExpressionAttributeValues={
                    ':f': str(dte_folio),
                    ':u': dte_pdf_url
                }
            )
            logger.info(
                f"Subscription Payment {payment_id} for {target_tenant} "
                f"updated with DTE Folio {dte_folio}"
            )

    except requests.exceptions.RequestException as e:
        logger.error(f"Connection error to DTE Microservice: {e}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in DTE worker logic: {e}")
        raise e
