import os
import boto3
import logging
import json
from typing import Dict, Any

from shared.subscriptions.mercadopago_client import MercadoPagoClient
from shared.subscriptions.entities import SubscriptionStatus, PaymentAudit
from shared.subscriptions.config import SubscriptionConfig
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.domain.entities import TenantPlan, TenantStatus


logger = logging.getLogger()
logger.setLevel(logging.INFO)

# DynamoDB Resources
dynamodb = boto3.resource('dynamodb')
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)


def lambda_handler(event, context):
    """
    Args:
        event (dict): {'arguments': {'tenantId': '...'}} (AppSync)
    """
    logger.info(f"CheckPaymentStatus Event: {event}")

    tenant_id = event.get('arguments', {}).get('tenantId')
    if not tenant_id:
        return {'status': 'FAILED', 'message': 'Missing tenantId'}

    mps = MercadoPagoClient()

    # 1. Check current subscription status
    try:
        sub_resp = SUBSCRIPTIONS_TABLE.get_item(
            Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'}
        )
        sub_item = sub_resp.get('Item')

        # If already AUTHORIZED/ACTIVE, return PAID
        if sub_item and sub_item.get('status') == SubscriptionStatus.AUTHORIZED.value:
            return {'status': 'PAID', 'message': 'Subscription is already active'}

    except Exception as e:
        logger.error(f"DB Error: {e}")
        return {'status': 'FAILED', 'message': 'Database error'}

    # 2. Search in Mercado Pago
    try:
        search_result = mps.search_payments(tenant_id, limit=5)
        results = search_result.get('results', [])

        if not results:
            return {'status': 'NONE', 'message': 'No payments found'}

        # Filter for approved
        # We need the LATEST approved one. Results are desc by date_created.
        latest_approved = None
        for p in results:
            if p.get('status') == 'approved':
                latest_approved = p
                break

        if not latest_approved:
            # Check if any is pending?
            latest_pending = next(
                (p for p in results if p.get('status') in ['pending', 'in_process']),
                None
            )
            if latest_pending:
                return {'status': 'PENDING', 'message': 'Payment is pending'}
            return {'status': 'NONE', 'message': 'No valid payments found'}

        # 3. We found an approved payment. Check if we processed it.
        payment_id = str(latest_approved['id'])
        amount = float(latest_approved.get('transaction_amount', 0))

        # Check Audit
        audit_resp = SUBSCRIPTIONS_TABLE.get_item(
            Key={'tenantId': tenant_id, 'paymentId': payment_id}
        )
        if audit_resp.get('Item'):
            logger.info(
                f"Payment {payment_id} already audited. Re-verifying activation."
            )
            # If audited, we assume processed, but continue to ensure tenant is active
        else:
            logger.info(
                f"Payment {payment_id} NOT audited. Processing missing payment."
            )

        # 4. Trigger Activation / Self-Heal
        # Amount Validation again!
        plan_id = sub_item.get('planId', 'lite') if sub_item else 'lite'

        if plan_id == 'lite':
            target_price = SubscriptionConfig.PROMO_PRICE
        else:
            target_price = SubscriptionConfig.PLAN_PRICES.get(plan_id, 999999)

        if amount < (target_price - 100):
            logger.warning(
                f"Payment {payment_id} amount mismatch. "
                f"Paid {amount} vs {target_price}"
            )
            return {'status': 'FAILED', 'message': 'Payment amount mismatch'}

        # ACTIVATE
        # Update Subscription
        SUBSCRIPTIONS_TABLE.update_item(
            Key={'tenantId': tenant_id, 'subscriptionId': 'CURRENT'},
            UpdateExpression="set #s = :s",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':s': SubscriptionStatus.AUTHORIZED.value
            }
        )

        # Audit (Create if missing)
        if not audit_resp.get('Item'):
            audit_item = PaymentAudit(
                tenant_id=tenant_id,
                payment_id=payment_id,
                amount=amount,
                status='approved',
                processed_at=latest_approved.get('date_approved'),
                raw_data=json.dumps(latest_approved)
            ).to_item()
            SUBSCRIPTIONS_TABLE.put_item(Item=audit_item)

        # Update Tenant
        repo = DynamoDBTenantRepository()
        tenant = repo.get_by_id(tenant_id)
        if tenant:
            if plan_id.upper() in TenantPlan._member_names_:
                tenant.plan = TenantPlan[plan_id.upper()]
                tenant.status = TenantStatus.ACTIVE
                repo.save(tenant)
                logger.info(f"Re-activated tenant {tenant_id}")

        return {'status': 'PAID', 'message': 'Payment confirmed and processed'}

    except Exception as e:
        logger.error(f"Reconciliation Error: {e}")
        return {'status': 'FAILED', 'message': str(e)}
