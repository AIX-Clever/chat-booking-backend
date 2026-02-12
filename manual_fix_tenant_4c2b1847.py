
import boto3
import os
from datetime import datetime

# Configure region
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

def fix_tenant():
    dynamodb = boto3.resource('dynamodb')
    
    # 1. Fix Subscription (Create 'CURRENT' pointer)
    subs_table = dynamodb.Table('ChatBooking-Subscriptions')
    
    # Data from existing subscription 104f79ce52b94607aa0aedcc879d5cb8
    current_sub = {
        "tenantId": "4c2b1847",
        "subscriptionId": "CURRENT",
        "status": "AUTHORIZED", # Manually creating as AUTHORIZED since payment is assumed OK
        "planId": "pro",
        "mpPreapprovalId": "104f79ce52b94607aa0aedcc879d5cb8", # Link to real ID
        "isPromoActive": True,
        "createdAt": "2026-02-12T17:43:05.526901+00:00",
        "updatedAt": datetime.utcnow().isoformat() + "+00:00",
        "currentPrice": "29990"
    }
    
    print("Creating CURRENT subscription record...")
    subs_table.put_item(Item=current_sub)
    print("SUCCESS: Subscription CURRENT created/updated.")
    
    # 2. Fix Tenant Plan
    tenants_table = dynamodb.Table('ChatBooking-Tenants')
    
    print("Updating Tenant plan to PRO and status to ACTIVE...")
    tenants_table.update_item(
        Key={'tenantId': '4c2b1847'},
        UpdateExpression="set #p = :p, #s = :s",
        ExpressionAttributeNames={
            '#p': 'plan',
            '#s': 'status'
        },
        ExpressionAttributeValues={
            ':p': 'PRO',
            ':s': 'ACTIVE'
        }
    )
    print("SUCCESS: Tenant updated.")
    
    # 3. Verify
    resp = tenants_table.get_item(Key={'tenantId': '4c2b1847'})
    print(f"Final Tenant State: {resp.get('Item')}")

if __name__ == '__main__':
    fix_tenant()
