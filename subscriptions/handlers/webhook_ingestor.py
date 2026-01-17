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
        
        # 1. Extract Signature Components
        x_signature = headers.get('x-signature')
        x_request_id = headers.get('x-request-id')
        
        # Query Params (id is usually there for "topic" notifications, or in body for others)
        # MP sends data.id in query string as ?id=... or ?data.id=... depending on topic
        # BUT for the manifest we need the `data.id` from the notification.
        # Let's extract from query params first, then body if needed.
        query_params = event.get('queryStringParameters') or {}
        data_id = query_params.get('data.id') or query_params.get('id')
        
        if not x_signature or not x_request_id or not data_id:
            print("Missing signature headers or data.id")
            # If missing headers, might be a health check or unauthorized
            return lambda_response(403, {'message': 'Missing signature components'})

        # Parse ts and v1 from x-signature
        parts = {p.split('=')[0]: p.split('=')[1] for p in x_signature.split(',')}
        ts = parts.get('ts')
        v1 = parts.get('v1')
        
        if not ts or not v1:
            print("Invalid signature format")
            return lambda_response(403, {'message': 'Invalid signature format'})

        # 2. Build Manifest
        # Template: id:[data.id];request-id:[x-request-id];ts:[ts];
        manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
        
        # 3. Calculate HMAC
        secret = SubscriptionConfig.MP_WEBHOOK_SECRET
        if not secret:
            print("Missing MP_WEBHOOK_SECRET in config")
            return lambda_response(500, {'message': 'Configuration Error'})

        calculated_hmac = hmac.new(
            secret.encode(),
            manifest.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # 4. Compare
        if not hmac.compare_digest(calculated_hmac, v1):
            print(f"Signature Mismatch. Calculated: {calculated_hmac}, Received: {v1}")
            return lambda_response(403, {'message': 'Invalid signature'})

        # 5. Push to SQS (If valid)
        body = event.get('body', '{}')
        
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                'source': 'mercadopago',
                'raw_data': body,
                'headers': headers,
                'query_params': query_params
            })
        )
        
        return lambda_response(200, {'message': 'OK'})

    except Exception as e:
        print(f"Ingestor Error: {str(e)}")
        # If we fail to ingest (SQS down?), return 500 so MP retries
        return lambda_response(500, {'message': 'Internal Error'})
