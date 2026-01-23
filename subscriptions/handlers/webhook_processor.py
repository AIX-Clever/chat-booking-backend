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
        
        # update_expression="set #s = :s, #u = :u",
        SUBSCRIPTIONS_TABLE.update_item(
            Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'}, # Or lookup logic
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': SubscriptionStatus.AUTHORIZED.value}
        )

        # 4. Sync Plan to Tenant Entity
        try:
            from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
            from shared.domain.entities import TenantPlan
            
            # Fetch Subscription to get the Plan
            sub_resp = SUBSCRIPTIONS_TABLE.get_item(Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'})
            sub_item = sub_resp.get('Item')
            
            if sub_item and 'planId' in sub_item:
                new_plan_str = sub_item['planId']
                
                # Update Tenant
                repo = DynamoDBTenantRepository()
                tenant = repo.get_by_id(tenant_id)
                if tenant:
                    # Update local entity
                    if new_plan_str.upper() in TenantPlan._member_names_:
                         tenant.plan = TenantPlan[new_plan_str.upper()]
                         repo.save(tenant)
                         print(f"Updated tenant {tenant_id} plan to {tenant.plan}")
                    else:
                        print(f"Warning: Unknown plan {new_plan_str}")
        except Exception as e:
            print(f"Failed to sync tenant plan: {e}")
            
    elif status == 'rejected' or status == 'cancelled':
        print(f"Payment {payment_id} was rejected/cancelled. Not activating plan.")
    elif status == 'refunded' or status == 'charged_back':
        print(f"Payment {payment_id} was {status}. Downgrading tenant to LITE.")
        try:
            from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
            from shared.domain.entities import TenantPlan

            tenant_repo = DynamoDBTenantRepository()
            tenant = tenant_repo.get_by_id(tenant_id)
            if tenant:
                tenant.plan = TenantPlan.LITE
                tenant_repo.save(tenant)
                print(f"Downgraded tenant {tenant_id} to LITE (Reason: {status})")
            else:
                print(f"Tenant {tenant_id} not found for {status} payment.")
        except Exception as e:
            print(f"Failed to process {status} payment: {e}")


def process_subscription_update(preapproval_id):
    # Logic to sync status if subscription is cancelled/paused in MP dashboard directly
    print(f"Processing subscription update for {preapproval_id}")
    try:
        # 1. Fetch current status from MP
        preapproval_info = mp_client.get_preapproval(preapproval_id)
        status = preapproval_info.get('status')
        tenant_id = preapproval_info.get('external_reference')
        
        print(f"Subscription {preapproval_id} status: {status} for tenant {tenant_id}")
        
        if not tenant_id:
            print("No tenant_id found in preapproval.")
            return

        # 2. Handle Cancelled/Paused Status
        if status in ['cancelled', 'paused']:
            # Downgrade Logic
            print(f"Downgrading tenant {tenant_id} due to status: {status}")
            
            # Map status to Enum
            new_sub_status = SubscriptionStatus.CANCELLED.value if status == 'cancelled' else SubscriptionStatus.PAUSED.value
            
            # Update Subscription
            SUBSCRIPTIONS_TABLE.update_item(
                Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'},
                UpdateExpression="set #s = :s",
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':s': new_sub_status}
            )
            
            # Update Tenant to LITE
            try:
                from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
                from shared.domain.entities import TenantPlan
                
                repo = DynamoDBTenantRepository()
                tenant = repo.get_by_id(tenant_id)
                if tenant:
                    tenant.plan = TenantPlan.LITE
                    repo.save(tenant)
                    print(f"Downgraded tenant {tenant_id} to LITE (Reason: {status})")
            except Exception as e:
                 print(f"Failed to downgrade tenant: {e}")
                
    except Exception as e:
        print(f"Error processing subscription update: {e}")
