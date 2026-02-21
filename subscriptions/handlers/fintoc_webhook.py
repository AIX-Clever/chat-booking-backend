import json
import boto3
import os
import hmac
import hashlib
from datetime import datetime
from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.entities import Subscription, SubscriptionStatus

dynamodb = boto3.resource('dynamodb')
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)

def lambda_handler(event, context):
    try:
        # 1. Verify Webhook Signature (Security)
        fintoc_webhook_secret = os.environ.get('FINTOC_WEBHOOK_SECRET')
        signature_header = event.get('headers', {}).get('Fintoc-Signature') or event.get('headers', {}).get('fintoc-signature')
        raw_body = event.get('body', '')

        print(f"Full Event: {json.dumps(event)}")
        
        if not signature_header or not fintoc_webhook_secret:
            print("Missing signature header or webhook secret. Skipping verification for now (WARNING).")
        else:
            try:
                from fintoc import WebhookSignature
                WebhookSignature.verify_header(raw_body, signature_header, fintoc_webhook_secret)
                print("Webhook signature verified successfully.")
            except Exception as sig_err:
                print(f"Webhook signature verification failed: {sig_err}")
                return {'statusCode': 403, 'body': 'Invalid signature'}

        body = json.loads(raw_body)
        event_type = body.get('type')
        data = body.get('data', {})

        print(f"Received Fintoc Webhook: {event_type}")

        # 2. Handle 'movement.created' (Payment Received)
        if event_type == 'movement.created':
            # This happens when a transfer is detected
            account_id = data.get('account_id')
            amount = data.get('amount')
            description = data.get('description')
            
            # TODO: Match movement to a tenant/subscription
            # Fintoc doesn't utilize 'external_reference' like MP in movements easily.
            # We need to match by 'holder_id' or a unique code in the description.
            
            print(f"Payment detected: {amount} CLP from Account {account_id}")

        # 3. Handle 'subscription_intent.succeeded' (Successful Payment)
        elif event_type == 'subscription_intent.succeeded':
            intent_id = data.get('id')
            print(f"Subscription Intent Succeeded: {intent_id}")
            
            # Find the tenant associated with this intent ID (using GSI)
            response = SUBSCRIPTIONS_TABLE.query(
                IndexName='mpPreapprovalId-index',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('mpPreapprovalId').eq(intent_id)
            )
            items = response.get('Items', [])
            
            if not items:
                print(f"No subscription found for intent ID (GSI): {intent_id}")
                # Fallback to Scan ONLY if necessary (for transition or if GSI is not ready)
                # print("Fallback to Scan...")
                # response = SUBSCRIPTIONS_TABLE.scan(
                #     FilterExpression=boto3.dynamodb.conditions.Attr('mpPreapprovalId').eq(intent_id)
                # )
                # items = response.get('Items', [])
            else:
                for item in items:
                    tenant_id = item['tenantId']
                    sub_id = item['subscriptionId']
                    current_status = item.get('status')
                    
                    if current_status == SubscriptionStatus.AUTHORIZED.value:
                        print(f"Subscription {sub_id} for tenant {tenant_id} is already AUTHORIZED. Skipping.")
                        continue

                    print(f"Activating subscription {sub_id} for tenant {tenant_id}")
                    
                    # Update status to AUTHORIZED (Idempotent update)
                    SUBSCRIPTIONS_TABLE.update_item(
                        Key={'tenantId': tenant_id, 'subscriptionId': sub_id},
                        UpdateExpression="SET #s = :s, updatedAt = :u",
                        ExpressionAttributeNames={'#s': 'status'},
                        ExpressionAttributeValues={
                            ':s': SubscriptionStatus.AUTHORIZED.value,
                            ':u': datetime.now().isoformat()
                        }
                    )
                    
                    # Also update 'CURRENT' pointer
                    SUBSCRIPTIONS_TABLE.update_item(
                        Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'},
                        UpdateExpression="SET #s = :s, updatedAt = :u",
                        ExpressionAttributeNames={'#s': 'status'},
                        ExpressionAttributeValues={
                            ':s': SubscriptionStatus.AUTHORIZED.value,
                            ':u': datetime.now().isoformat()
                        }
                    )
                    print(f"Successfully activated tenant {tenant_id}")

        # 4. Handle 'link.created' (Account Connected)
        elif event_type == 'link.created':
            link_token = data.get('link_token')
            holder_id = data.get('holder_id')
            username = data.get('username')
            
            print(f"New Bank Account Connected: {username} ({holder_id})")
            # Here we would update the Tenant's subscription method to 'FINTOC'

        return {'statusCode': 200, 'body': 'OK'}

    except Exception as e:
        print(f"Error processing Fintoc webhook: {e}")
        return {'statusCode': 500, 'body': str(e)}
