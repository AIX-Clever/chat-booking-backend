import json
import os
import boto3
from datetime import datetime, timedelta
from shared.utils import lambda_response, error_response, success_response, extract_tenant_id
from shared.decorators import require_tenant_context
from shared.subscriptions.mercadopago_client import MercadoPagoClient
from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.entities import Subscription, SubscriptionStatus, PlanType

# Initialize clients
dynamodb = boto3.resource('dynamodb')
scheduler = boto3.client('scheduler')
mp_client = MercadoPagoClient()

SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)
WORKER_ARN = os.getenv('WORKER_ARN', '') # To be passed by CDK
SCHEDULER_ROLE_ARN = os.getenv('SCHEDULER_ROLE_ARN', '') # To be passed by CDK

@require_tenant_context
def lambda_handler(event, context):
    try:
        tenant_id = event['tenant_id']
        body = json.loads(event.get('body', '{}'))
        
        plan_id_str = body.get('planId', 'lite')
        payer_email = body.get('email')
        back_url = body.get('backUrl', 'https://admin.holalucia.cl') # Default or from body
        
        # Validate inputs
        if not payer_email:
            return lambda_response(400, {'message': 'Missing email'})
            
        try:
            plan_enum = PlanType(plan_id_str)
        except ValueError:
            return lambda_response(400, {'message': 'Invalid planId'})

        # Business Logic
        # 1. Determine Price (Promo logic: first 3 months $1 if new?)
        # For simplicity, we apply promo price if configured
        price = SubscriptionConfig.PROMO_PRICE
        full_price = SubscriptionConfig.PLAN_PRICES.get(plan_id_str, 9.00)
        
        # 2. Create Preapproval in MP
        try:
            preapproval = mp_client.create_preapproval(
                payer_email=payer_email,
                plan_id=plan_id_str,
                external_reference=tenant_id,
                back_url=back_url,
                price=price
            )
        except Exception as e:
            print(f"MP Error: {str(e)}")
            return lambda_response(500, {'message': 'Payment Provider Error'})

        preapproval_id = preapproval['id']
        init_point = preapproval['init_point'] # URL for frontend redirect
        
        # 3. Schedule Promo Removal (if applicable)
        scheduler_arn = None
        if price < full_price:
            end_promo_date = datetime.utcnow() + timedelta(days=30 * SubscriptionConfig.PROMO_DURATION_MONTHS)
            schedule_name = f"PromoEnd_{tenant_id}_{preapproval_id}"
            
            try:
                # Format: yyyy-mm-ddThh:mm:ss (at() expects format without Z usually, check docs, better simple)
                at_expression = f"at({end_promo_date.strftime('%Y-%m-%dT%H:%M:%S')})"
                
                response = scheduler.create_schedule(
                    Name=schedule_name,
                    ScheduleExpression=at_expression,
                    Target={
                        'Arn': WORKER_ARN,
                        'RoleArn': SCHEDULER_ROLE_ARN,
                        'Input': json.dumps({
                            'action': 'REMOVE_PROMO',
                            'tenant_id': tenant_id,
                            'subscription_id': preapproval_id, # Using preapproval ID as sub ID for simplicity
                            'target_price': full_price
                        })
                    },
                    FlexibleTimeWindow={'Mode': 'OFF'}
                )
                scheduler_arn = response['ScheduleArn']
            except Exception as e:
                print(f"Scheduler Error: {str(e)}")
                # Continue, don't block subscription, but log error (manual fix needed)

        # 4. Persistence
        sub = Subscription(
            tenant_id=tenant_id,
            subscription_id=preapproval_id, # Using MP ID as PK component
            status=SubscriptionStatus.PENDING, # Pending until webhook confirms payment/auth
            plan_id=plan_enum,
            current_price=price,
            mp_preapproval_id=preapproval_id,
            is_promo_active=True,
            promo_scheduler_arn=scheduler_arn
        )
        
        SUBSCRIPTIONS_TABLE.put_item(Item=sub.to_item())

        return lambda_response(200, {
            'subscriptionId': preapproval_id,
            'initPoint': init_point,
            'message': 'Subscription initialized'
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return lambda_response(500, {'message': 'Internal Server Error'})
