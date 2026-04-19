import json
import boto3
from shared.subscriptions.mercadopago_client import MercadoPagoClient
from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.entities import SubscriptionStatus

dynamodb = boto3.resource('dynamodb')
mp_client = MercadoPagoClient()
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)
scheduler = boto3.client('scheduler')

def lambda_handler(event, context):
    """
    EventBridge Scheduler Worker
    Input: { "action": "REMOVE_PROMO" | "APPLY_DOWNGRADE", ... }
    """
    try:
        action = event.get('action')
        tenant_id = event.get('tenant_id')
        subscription_id = event.get('subscription_id')
        
        print(f"Executing {action} for {tenant_id}/{subscription_id}")
        
        if action == 'REMOVE_PROMO':
            handle_remove_promo(event)
        elif action == 'APPLY_DOWNGRADE':
            handle_downgrade(event)
        else:
            print(f"Unknown action: {action}")

    except Exception as e:
        print(f"Worker Error: {str(e)}")
        raise e

def handle_remove_promo(event):
    tenant_id = event['tenant_id']
    sub_id = event['subscription_id']
    target_price = float(event.get('target_price', 9.00))
    
    # 1. Update MP
    mp_client.update_preapproval(sub_id, target_price)
    
    # 2. Update DB
    SUBSCRIPTIONS_TABLE.update_item(
        Key={'tenantId': tenant_id, 'subscriptionId': sub_id},
        UpdateExpression="set currentPrice = :p, isPromoActive = :false, promoSchedulerArn = :null",
        ExpressionAttributeValues={
            ':p': str(target_price),
            ':false': False,
            ':null': None
        }
    )
    print("Promo removed successfully.")

def handle_downgrade(event):
    tenant_id = event['tenant_id']
    sub_id = event['subscription_id']
    target_plan = event['target_plan']
    target_price = float(event['target_price'])
    
    # 1. Update MP (Price change)
    mp_client.update_preapproval(sub_id, target_price)
    
    # 2. Update DB
    SUBSCRIPTIONS_TABLE.update_item(
        Key={'tenantId': tenant_id, 'subscriptionId': sub_id},
        UpdateExpression="set planId = :plan, currentPrice = :price, pendingChange = :null",
        ExpressionAttributeValues={
            ':plan': target_plan,
            ':price': str(target_price),
            ':null': None
        }
    )
    print(f"Downgrade to {target_plan} applied.")
