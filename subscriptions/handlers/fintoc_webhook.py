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
        # Fintoc sends a signature in headers to verify authenticity
        # (Simplified for initial implementation, add full HMAC check later)
        
        print(f"Full Event: {json.dumps(event)}")
        headers = event.get('headers', {})
        print(f"Headers: {json.dumps(headers)}")
        
        body = json.loads(event.get('body', '{}'))
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
            
            # Find the tenant associated with this intent ID
            # We can use a scan with filter since we don't have a GSI on mpPreapprovalId (which we used for Fintoc Intent ID)
            # though in a production system we should use a GSI.
            response = SUBSCRIPTIONS_TABLE.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('mpPreapprovalId').eq(intent_id)
            )
            items = response.get('Items', [])
            
            if not items:
                print(f"No subscription found for intent ID: {intent_id}")
            else:
                for item in items:
                    tenant_id = item['tenantId']
                    sub_id = item['subscriptionId']
                    print(f"Activating subscription {sub_id} for tenant {tenant_id}")
                    
                    # Update the specific item
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
