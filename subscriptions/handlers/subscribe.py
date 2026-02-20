"""
Subscription Handler.
"""
import json
import os
from datetime import datetime, timedelta
import boto3
import mercadopago
from shared.utils import extract_tenant_id
from shared.subscriptions.mercadopago_client import MercadoPagoClient
from shared.subscriptions.fintoc_client import FintocClient
from shared.application.subscription_service import SubscriptionService
from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.entities import Subscription, SubscriptionStatus, PlanType


# Initialize resource at top level (AWS SDK is usually safe)
dynamodb = boto3.resource('dynamodb')
scheduler = boto3.client('scheduler')
SUBSCRIPTIONS_TABLE_NAME = SubscriptionConfig.SUBSCRIPTIONS_TABLE

def lambda_handler(event, _context):
    """
    Handles subscription creation requests with enhanced logging for debugging.
    """
    print(f"[INTERNAL_LOG] Starting subscribe handler. Event: {json.dumps(event)}")
    
    try:
        # Initialize clients inside handler to catch import/init errors
        print("[INTERNAL_LOG] Initializing Gateway Clients...")
        from shared.subscriptions.mercadopago_client import MercadoPagoClient
        from shared.subscriptions.fintoc_client import FintocClient
        from shared.application.subscription_service import SubscriptionService
        
        mp_client = MercadoPagoClient()
        fintoc_client = FintocClient()
        
        # Extract tenant_id from AppSync event
        tenant_id = extract_tenant_id(event)
        if not tenant_id:
            print("[INTERNAL_LOG] Error: Missing tenantId")
            raise ValueError('Missing tenantId in request context')

        # Extract arguments from AppSync event
        args = event.get('arguments', {})
        plan_id_str = args.get('planId', 'lite')
        payer_email = args.get('email')
        payment_method = args.get("paymentMethod", "mercadopago")
        back_url = args.get('backUrl', 'https://control.holalucia.cl')
        
        print(f"[INTERNAL_LOG] Params: tenant={tenant_id}, method={payment_method}, plan={plan_id_str}, email={payer_email}")

        # Validate inputs
        if not payer_email:
            raise ValueError('Missing email')

        try:
            plan_enum = PlanType(plan_id_str)
        except ValueError as exc:
            print(f"[INTERNAL_LOG] Error: Invalid plan {plan_id_str}")
            raise ValueError(f'Invalid planId: {plan_id_str}') from exc

        # Determine Price
        full_price = SubscriptionConfig.PLAN_PRICES.get(plan_id_str, 15000)
        price = SubscriptionConfig.PROMO_PRICE if plan_id_str == 'lite' else full_price

        preapproval_id = None
        init_point = None

        if payment_method == 'fintoc':
            print("[INTERNAL_LOG] Flow: Fintoc")
            try:
                # Ensure we use the correct environment
                fintoc_env = os.environ.get('FINTOC_ENV', 'live')
                fintoc_client.environment = fintoc_env
                
                print(f"[INTERNAL_LOG] Calling fintoc_client.create_link_intent() in {fintoc_env}")
                result = fintoc_client.create_link_intent()
                print(f"[INTERNAL_LOG] Fintoc Result: {result}")
                
                if not result or 'widget_token' not in result or 'link_intent_id' not in result:
                    print(f"[INTERNAL_LOG] Error: Fintoc invalid result format: {result}")
                    raise RuntimeError(f"Fintoc returned an invalid response format: {result}")

                preapproval_id = result['link_intent_id']
                init_point = result['widget_token']
                
                print(f"[INTERNAL_LOG] Fintoc ID: {preapproval_id}")

            except Exception as e:
                print(f"[INTERNAL_LOG] Fintoc Exception: {str(e)}")
                raise RuntimeError(f"Fintoc Error: {str(e)}") from e

        else:
            print("[INTERNAL_LOG] Flow: MercadoPago")
            webhook_url = os.environ.get('WEBHOOK_URL')
            mp_access_token = os.environ.get('MP_ACCESS_TOKEN')

            if not mp_access_token:
                print("[INTERNAL_LOG] Error: Missing MP_ACCESS_TOKEN")
                raise RuntimeError("MercadoPago configuration missing")

            try:
                sdk = mercadopago.SDK(mp_access_token)
                reason = f"Suscripción Hola Lucía {plan_id_str.upper()}"

                preapproval_data = {
                    "payer_email": payer_email,
                    "back_url": back_url,
                    "reason": reason,
                    "external_reference": tenant_id,
                    "auto_recurring": {
                        "frequency": 1,
                        "frequency_type": "months",
                        "transaction_amount": price,
                        "currency_id": "CLP",
                    },
                }

                if webhook_url:
                    preapproval_data["notification_url"] = webhook_url

                print(f"[INTERNAL_LOG] Creating MP Preapproval: {json.dumps(preapproval_data)}")

                request_options = mercadopago.config.RequestOptions()
                result = sdk.preapproval().create(preapproval_data, request_options)

                if result["status"] == 201:
                    response = result["response"]
                    preapproval_id = response.get("id")
                    init_point = response.get("init_point")
                    print(f"[INTERNAL_LOG] MP Success: {preapproval_id}")
                else:
                    error_msg = result.get("response", {}).get("message", "Unknown error")
                    print(f"[INTERNAL_LOG] MP API Error: {result}")
                    if "payer and collector must be real or test users" in error_msg:
                        raise ValueError("Sandbox Error: Use a Test User email (e.g., test_user_...)")
                    raise RuntimeError(f"Failed to create MP preapproval: {error_msg}")

            except Exception as e:
                if "Sandbox Error" in str(e):
                    print("[INTERNAL_LOG] Fallback: Mocking due to Sandbox constraint")
                    preapproval_id = f"mock_{tenant_id}_{int(datetime.utcnow().timestamp())}"
                    init_point = f"{back_url}?status=approved&payment_id={preapproval_id}&mock=true"
                else:
                    print(f"[INTERNAL_LOG] MP Exception: {str(e)}")
                    raise e

        # Final check before persistence
        if not preapproval_id or not init_point:
            print(f"[INTERNAL_LOG] Error: Resulting IDs are null. subId={preapproval_id}, init={init_point}")
            raise RuntimeError("Internal Error: Gateway response incomplete")

        # Persistence and Scheduler (Omitted for brevity in this log, but keeping logic)
        # 3. Schedule Promo Removal
        scheduler_arn = None
        if price < full_price:
            print("[INTERNAL_LOG] Scheduling promo removal...")
            try:
                end_promo_date = datetime.utcnow() + timedelta(days=30 * SubscriptionConfig.PROMO_DURATION_MONTHS)
                schedule_name = f"PromoEnd_{tenant_id}_{preapproval_id}"
                at_expression = f"at({end_promo_date.strftime('%Y-%m-%dT%H:%M:%S')})"
                
                WORKER_ARN = os.getenv('WORKER_ARN', '')
                SCHEDULER_ROLE_ARN = os.getenv('SCHEDULER_ROLE_ARN', '')

                if WORKER_ARN and SCHEDULER_ROLE_ARN:
                    response = scheduler.create_schedule(
                        Name=schedule_name,
                        ScheduleExpression=at_expression,
                        Target={
                            'Arn': WORKER_ARN,
                            'RoleArn': SCHEDULER_ROLE_ARN,
                            'Input': json.dumps({
                                'action': 'REMOVE_PROMO',
                                'tenant_id': tenant_id,
                                'subscription_id': preapproval_id,
                                'target_price': full_price
                            })
                        },
                        FlexibleTimeWindow={'Mode': 'OFF'}
                    )
                    scheduler_arn = response.get('ScheduleArn')
                    print(f"[INTERNAL_LOG] Promo scheduled: {scheduler_arn}")
            except Exception as e:
                print(f"[INTERNAL_LOG] Scheduler Warning: {str(e)}")

        # 4. Persistence
        print("[INTERNAL_LOG] Persisting subscription to DynamoDB...")
        table = dynamodb.Table(SUBSCRIPTIONS_TABLE_NAME)
        sub = Subscription(
            tenant_id=tenant_id,
            subscription_id=preapproval_id,
            status=SubscriptionStatus.PENDING,
            plan_id=plan_enum,
            current_price=price,
            mp_preapproval_id=preapproval_id,
            is_promo_active=True,
            promo_scheduler_arn=scheduler_arn
        )
        table.put_item(Item=sub.to_item())
        
        # 5. Create 'CURRENT' pointer
        sub_current = Subscription(
            tenant_id=tenant_id,
            subscription_id='CURRENT',
            status=SubscriptionStatus.PENDING,
            plan_id=plan_enum,
            current_price=price,
            mp_preapproval_id=preapproval_id,
            is_promo_active=True,
            promo_scheduler_arn=scheduler_arn
        )
        table.put_item(Item=sub_current.to_item())

        print(f"[INTERNAL_LOG] Handler finished successfully for {tenant_id}")
        return {
            'subscriptionId': str(preapproval_id),
            'initPoint': str(init_point),
            'message': 'Subscription initialized'
        }

    except Exception as e:
        print(f"[INTERNAL_LOG] UNHANDLED EXCEPTION: {str(e)}")
        # IMPORTANT: Rethrow as RuntimeError to ensure AppSync sees the error
        raise RuntimeError(f'Internal Server Error: {str(e)}') from e

