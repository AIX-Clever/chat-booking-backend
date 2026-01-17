import json
import boto3
from datetime import datetime
from shared.subscriptions.mercadopago_client import MercadoPagoClient
from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.entities import Subscription, SubscriptionStatus, PaymentAudit

dynamodb = boto3.resource('dynamodb')
mp_client = MercadoPagoClient()
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)

def lambda_handler(event, context):
    """
    SQS Event Processor
    """
    for record in event.get('Records', []):
        try:
            body = json.loads(record['body'])
            raw_data = body.get('raw_data')
            
            if isinstance(raw_data, str):
                msg_body = json.loads(raw_data)
            else:
                msg_body = raw_data
                
            # Mercado Pago Notification Structure
            # { "action": "payment.created", "data": { "id": "123" } }
            
            resource_id = None
            if 'data' in msg_body and 'id' in msg_body['data']:
                resource_id = msg_body['data']['id']
            elif 'id' in msg_body:
                # v1 fallback
                resource_id = msg_body['id']
            
            if not resource_id:
                print("Skipping: No resource ID found")
                continue
                
            topic = msg_body.get('type') or msg_body.get('action')
            
            if topic == 'payment':
                process_payment(resource_id, raw_data)
            elif topic == 'subscription_preapproval':
                process_subscription_update(resource_id)
            
        except Exception as e:
            print(f"Error processing record: {str(e)}")
            # Raise to retry (SQS DLQ logic handles poison pills)
            raise e 

def process_payment(payment_id, raw_data):
    # 1. Fetch from source of truth
    payment_info = mp_client.get_payment(payment_id)
    
    tenant_id = payment_info.get('external_reference')
    status = payment_info.get('status')
    amount = float(payment_info.get('transaction_amount', 0))
    
    if not tenant_id:
        print(f"Skipping payment {payment_id}: No external_reference (tenant_id)")
        return

    # 2. Idempotency Check & Auditoria
    audit = PaymentAudit(
        tenant_id=tenant_id,
        payment_id=str(payment_id),
        amount=amount,
        status=status,
        processed_at=datetime.utcnow().isoformat() + 'Z',
        raw_data=str(raw_data)
    )
    
    try:
        SUBSCRIPTIONS_TABLE.put_item(
            Item=audit.to_item(),
            ConditionExpression='attribute_not_exists(paymentId)' # Prevent double processing
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        print(f"Payment {payment_id} already processed. Skipping.")
        return

    # 3. Update Subscription Status if Approved
    if status == 'approved':
        # Extend validity / Unpause
        # Need to find the subscription associated with this tenant
        # Simplified: We assume 1 active sub per tenant. 
        # Ideally, MP payment has 'preapproval_id' in 'metadata' usually?
        
        # update_expression="set #s = :s, #u = :u",
        SUBSCRIPTIONS_TABLE.update_item(
            Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'}, # Or lookup logic
             # For this prototype we assume SK is stored or we blindly update status
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': SubscriptionStatus.AUTHORIZED.value}
        )

def process_subscription_update(preapproval_id):
    # Logic to sync status if subscription is cancelled/paused in MP dashboard directly
    pass
