import json
import os
import boto3
from datetime import datetime, timedelta
from shared.utils import lambda_response, error_response, success_response, extract_tenant_id, parse_iso_datetime
from shared.decorators import require_tenant_context
from shared.subscriptions.mercadopago_client import MercadoPagoClient
from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.entities import Subscription, SubscriptionStatus, PlanType

dynamodb = boto3.resource('dynamodb')
scheduler = boto3.client('scheduler')
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)
WORKER_ARN = os.getenv('WORKER_ARN', '')
SCHEDULER_ROLE_ARN = os.getenv('SCHEDULER_ROLE_ARN', '')

@require_tenant_context
def lambda_handler(event, context):
    try:
        tenant_id = event['tenant_id']
        body = json.loads(event.get('body', '{}'))
        
        target_plan = body.get('targetPlan')
        subscription_id = body.get('subscriptionId') # In frontend we should know this
        
        if not target_plan or not subscription_id:
            return lambda_response(400, {'message': 'Missing targetPlan or subscriptionId'})

        # 1. Fetch current subscription
        resp = SUBSCRIPTIONS_TABLE.get_item(Key={'tenantId': tenant_id, 'subscriptionId': subscription_id})
        if 'Item' not in resp:
            return lambda_response(404, {'message': 'Subscription not found'})
            
        sub_data = resp['Item']
        
        # 2. Calculate Effective Date (Next Billing Date)
        next_billing_str = sub_data.get('nextBillingDate')
        if not next_billing_str:
             # Fallback: if no date, apply in 30 days or fail? 
             # For MVP, assume immediate downgrade or +30 days if corrupt.
             # Better: fetch from MP
             return lambda_response(400, {'message': 'Cannot determine next billing date'})
             
        next_billing_dt = parse_iso_datetime(next_billing_str)
        
        # Trigger 1 hour before billing to allow MP update processing
        trigger_dt = next_billing_dt - timedelta(hours=1)
        if trigger_dt < datetime.utcnow():
            # If too close, maybe schedule for next month? or +1 hour from now
            trigger_dt = datetime.utcnow() + timedelta(minutes=5)

        # 3. Schedule Downgrade
        target_price = SubscriptionConfig.PLAN_PRICES.get(target_plan, 9.00)
        
        schedule_name = f"Downgrade_{tenant_id}_{subscription_id}_{int(datetime.utcnow().timestamp())}"
        at_expression = f"at({trigger_dt.strftime('%Y-%m-%dT%H:%M:%S')})"
        
        schedule_resp = scheduler.create_schedule(
            Name=schedule_name,
            ScheduleExpression=at_expression,
            Target={
                'Arn': WORKER_ARN,
                'RoleArn': SCHEDULER_ROLE_ARN,
                'Input': json.dumps({
                    'action': 'APPLY_DOWNGRADE',
                    'tenant_id': tenant_id,
                    'subscription_id': subscription_id,
                    'target_plan': target_plan,
                    'target_price': target_price
                })
            },
            FlexibleTimeWindow={'Mode': 'OFF'}
        )
        
        # 4. Update DynamoDB
        pending_change = {
            'targetPlan': target_plan,
            'targetPrice': str(target_price),
            'effectiveDate': trigger_dt.isoformat(),
            'schedulerArn': schedule_resp['ScheduleArn']
        }
        
        SUBSCRIPTIONS_TABLE.update_item(
            Key={'tenantId': tenant_id, 'subscriptionId': subscription_id},
            UpdateExpression="set pendingChange = :pc",
            ExpressionAttributeValues={':pc': pending_change}
        )
        
        return lambda_response(200, {'message': 'Downgrade scheduled', 'effectiveDate': trigger_dt.isoformat()})

    except Exception as e:
        print(f"Error: {str(e)}")
        return lambda_response(500, {'message': 'Internal Server Error'})
