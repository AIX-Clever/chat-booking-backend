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
            # Check top-level SQS body first (added by Ingestor)
            if 'id' in body:
                resource_id = body['id']
            elif 'data' in msg_body and 'id' in msg_body['data']:
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


    # 3. Handle Pending/In Process
    if status in ['pending', 'in_process']:
        print(f"Payment {payment_id} is pending/in_process. Updating status to PENDING.")
        SUBSCRIPTIONS_TABLE.update_item(
            Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': SubscriptionStatus.PENDING.value}
        )
        return

    # 4. Update Subscription Status if Approved
    if status == 'approved':
        # Fetch Subscription FIRST to Validate Amount and get Plan
        sub_resp = SUBSCRIPTIONS_TABLE.get_item(
            Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'}
        )
        sub_item = sub_resp.get('Item')

        if not sub_item:
            print(f"No subscription found for tenant {tenant_id}")
            return

        # --- AMOUNT VALIDATION ---
        plan_id = sub_item.get('planId', 'lite')

        # Logic: If plan is LITE, we currently offer it at PROMO_PRICE
        if plan_id == 'lite':
            target_price = SubscriptionConfig.PROMO_PRICE
        else:
            # Default high safety
            target_price = SubscriptionConfig.PLAN_PRICES.get(plan_id, 999999)

        # Tolerance check (allow small diff for tax/rounding)
        # Using 100 CLP numeric tolerance
        if amount < (target_price - 100):
            print(
                f"SECURITY ALERT: Amount Mismatch for {tenant_id}. "
                f"Paid {amount}, Expected {target_price} for plan {plan_id}. "
                "Logic: REJECT."
            )
            return

        print(
            f"Amount validated: {amount} matches expected {target_price} "
            f"for {plan_id}"
        )
        # -------------------------

        # Extend validity / Unpause
        SUBSCRIPTIONS_TABLE.update_item(
            Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':s': SubscriptionStatus.AUTHORIZED.value
            }
        )

        # 4.5 Update Original Subscription Record (History)
        original_sub_id = sub_item.get('mpPreapprovalId')
        if original_sub_id and original_sub_id != 'CURRENT':
            try:
                print(f"Syncing status to original subscription {original_sub_id}")
                SUBSCRIPTIONS_TABLE.update_item(
                    Key={'tenantId': tenant_id, 'subscriptionId': original_sub_id},
                    UpdateExpression="set #s = :s",
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={
                        ':s': SubscriptionStatus.AUTHORIZED.value
                    }
                )
            except Exception as e:
                print(f"Failed to sync original subscription: {e}")

        # 5. Sync Plan and Activate Tenant Entity
        try:
            from shared.infrastructure.dynamodb_repositories import (
                DynamoDBTenantRepository
            )
            from shared.domain.entities import TenantPlan, TenantStatus

            # Using plan_id fetched above
            if plan_id:
                new_plan_str = plan_id

                # Update Tenant
                repo = DynamoDBTenantRepository()
                tenant = repo.get_by_id(tenant_id)
                if tenant:
                    # Update local entity
                    if new_plan_str.upper() in TenantPlan._member_names_:
                        tenant.plan = TenantPlan[new_plan_str.upper()]
                        tenant.status = TenantStatus.ACTIVE  # ACTIVATE TENANT
                        repo.save(tenant)
                        print(
                            f"Updated tenant {tenant_id} plan to {tenant.plan} "
                            "and status to ACTIVE"
                        )
                    else:
                        print(f"Warning: Unknown plan {new_plan_str}")
        except Exception as e:
            print(f"Failed to sync tenant plan: {e}")

    elif status == 'rejected' or status == 'cancelled':
        print(f"Payment {payment_id} rejected/cancelled. Not activating plan.")
    elif status == 'refunded' or status == 'charged_back':
        print(f"Payment {payment_id} was {status}. Downgrading tenant to LITE.")
        try:
            from shared.infrastructure.dynamodb_repositories import (
                DynamoDBTenantRepository
            )
            from shared.domain.entities import TenantPlan

            tenant_repo = DynamoDBTenantRepository()
            tenant = tenant_repo.get_by_id(tenant_id)
            if tenant:
                tenant.plan = TenantPlan.LITE
                tenant_repo.save(tenant)
                print(
                    f"Downgraded tenant {tenant_id} to LITE (Reason: {status})"
                )
            else:
                print(f"Tenant {tenant_id} not found for {status} payment.")
        except Exception as e:
            print(f"Failed to process {status} payment: {e}")



def process_subscription_update(preapproval_id):
    # Logic to sync status if subscription is cancelled/paused in MP dashboard
    print(f"Processing subscription update for {preapproval_id}")
    try:
        # 1. Fetch current status from MP
        preapproval_info = mp_client.get_preapproval(preapproval_id)
        status = preapproval_info.get('status')
        tenant_id = preapproval_info.get('external_reference')

        print(
            f"Subscription {preapproval_id} status: {status} "
            f"for tenant {tenant_id}"
        )
        print(f"DEBUG: Processing status '{status}' (type: {type(status)})")

        if not tenant_id:
            print("No tenant_id found in preapproval.")
            return

        # 2. Handle Cancelled/Paused Status
        if status in ['cancelled', 'paused']:
            # Downgrade Logic
            print(f"Downgrading tenant {tenant_id} due to status: {status}")

            # Map status to Enum
            new_sub_status = (
                SubscriptionStatus.CANCELLED.value
                if status == 'cancelled'
                else SubscriptionStatus.PAUSED.value
            )

            # Update Subscription
            SUBSCRIPTIONS_TABLE.update_item(
                Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'},
                UpdateExpression="set #s = :s",
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':s': new_sub_status}
            )

            # Update Tenant to LITE
            try:
                from shared.infrastructure.dynamodb_repositories import (
                    DynamoDBTenantRepository
                )
                from shared.domain.entities import TenantPlan

                repo = DynamoDBTenantRepository()
                tenant = repo.get_by_id(tenant_id)
                if tenant:
                    tenant.plan = TenantPlan.LITE
                    repo.save(tenant)
                    print(
                        f"Downgraded tenant {tenant_id} to LITE "
                        f"(Reason: {status})"
                    )
            except Exception as e:
                print(f"Failed to downgrade tenant: {e}")
                
        elif status == 'authorized':
             # Activate Subscription
            print(f"Activating tenant {tenant_id} due to status: {status}")
            
            # Update Subscription
            SUBSCRIPTIONS_TABLE.update_item(
                Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'},
                UpdateExpression="set #s = :s",
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':s': SubscriptionStatus.AUTHORIZED.value}
            )
            
            # Activate Tenant (Sync Plan)
            # Fetch plan from subscription first to know what to activate
            sub_resp = SUBSCRIPTIONS_TABLE.get_item(
                Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'}
            )
            sub_item = sub_resp.get('Item')
            plan_id = sub_item.get('planId', 'pro') if sub_item else 'pro' # Default to pro if missing
            
            try:
                from shared.infrastructure.dynamodb_repositories import (
                    DynamoDBTenantRepository
                )
                from shared.domain.entities import TenantPlan, TenantStatus

                print(f"Syncing tenant {tenant_id} plan to {plan_id.upper()}")
                repo = DynamoDBTenantRepository()
                tenant = repo.get_by_id(tenant_id)
                if tenant:
                    if plan_id.upper() in TenantPlan._member_names_:
                        tenant.plan = TenantPlan[plan_id.upper()]
                        tenant.status = TenantStatus.ACTIVE
                        repo.save(tenant)
                        print(f"Activated tenant {tenant_id} with plan {tenant.plan}")
                    else:
                        print(f"Invalid plan name {plan_id} for tenant {tenant_id}")
                else:
                    print(f"Tenant {tenant_id} not found for activation")
            except Exception as e:
                print(f"Failed to activate tenant entity: {str(e)}")
                import traceback
                traceback.print_exc()

        elif status in ['rejected', 'cancelled', 'paused']:
            # Fallback for other statuses to prevent silent failure
            print(f"Subscription status {status} handled as inactive.")

    except Exception as e:
        print(f"Error processing subscription update: {e}")
