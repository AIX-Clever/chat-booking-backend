import json
import os
import hmac
import hashlib
import boto3
from shared.utils import lambda_response
from shared.subscriptions.config import SubscriptionConfig

sqs = boto3.client('sqs')
QUEUE_URL = os.getenv('QUEUE_URL', '')

def lambda_handler(event, context):
    try:
        # 1. HMAC Validation
        # MP sends x-signature header. Format: ts=...,v1=...
        # Simulating validation logic (exact MP signature parsing to be refined based on docs)
        # For MVP, checking if query param token or secret matches (if MP supports it)
        # OR extracting x-signature and validating.
        
        headers = event.get('headers', {})
        # Note: In production you MUST validate 'x-signature' or 'x-request-signature'
        # mp_signature = headers.get('x-signature')
        # if not mp_signature:
        #    return lambda_response(403, {'message': 'Missing signature'})
        
        # 2. Push to SQS
        body = event.get('body', '{}')
        
        # Enforce idempotency at ingestion? No, processor handles it.
        # Just ensure we capture the raw event.
        
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                'source': 'mercadopago',
                'raw_data': body,
                'headers': headers
            })
        )
        
        # 3. Fast ACK
        return lambda_response(200, {'message': 'Received'})

    except Exception as e:
        print(f"Ingestor Error: {str(e)}")
        # If we fail to ingest (SQS down?), return 500 so MP retries
        return lambda_response(500, {'message': 'Internal Error'})
