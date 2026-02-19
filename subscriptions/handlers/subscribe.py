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


# Initialize clients
dynamodb = boto3.resource('dynamodb')
scheduler = boto3.client('scheduler')
# We still initialize these for other potential uses or legacy consistency,
# but we will bypass them for creation to support notification_url hotfix.
mp_client = MercadoPagoClient()
fintoc_client = FintocClient()
subscription_service = SubscriptionService(mp_client)


SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)
WORKER_ARN = os.getenv('WORKER_ARN', '')
SCHEDULER_ROLE_ARN = os.getenv('SCHEDULER_ROLE_ARN', '')

def lambda_handler(event, _context):
    """
    Handles subscription creation requests.
    """
    try:
        # Extract tenant_id from AppSync event
        tenant_id = extract_tenant_id(event)
        if not tenant_id:
            raise ValueError('Missing tenantId in request context')

        # Extract arguments from AppSync event
        args = event.get('arguments', {})
        plan_id_str = args.get('planId', 'lite')
        payer_email = args.get('email')
        payment_method = args.get('paymentMethod', 'mercadopago') # Default to MP
        back_url = args.get('backUrl', 'https://control.holalucia.cl')


        # Validate inputs
        if not payer_email:
            raise ValueError('Missing email')

        try:
            plan_enum = PlanType(plan_id_str)
        except ValueError as exc:
            raise ValueError('Invalid planId') from exc

        # Business Logic
        # Determine Price
        full_price = SubscriptionConfig.PLAN_PRICES.get(plan_id_str, 15000)
        price = SubscriptionConfig.PROMO_PRICE if plan_id_str == 'lite' else full_price

        preapproval_id = None
        init_point = None

        if payment_method == 'fintoc':
            # --- FINTOC LOGIC ---
            print(f"Initializing Fintoc for {payer_email}")
            try:
                # Create Link Intent for Widget
                result = fintoc_client.create_link_intent()
                # We use the widget_token as the 'initPoint' for the frontend to open
                # We use the link_intent_id as the temporary 'subscription_id'

                preapproval_id = result['link_intent_id']
                init_point = result['widget_token']

                print(f"Fintoc Intent Created: {preapproval_id}")

            except Exception as e:
                print(f"Fintoc Error: {e}")
                raise RuntimeError(f"Failed to initialize Fintoc: {str(e)}") from e

        else:
            # --- MERCADOPAGO LOGIC (Existing) ---
            # 2. Create Preapproval - HOTFIX: Direct SDK usage to support notification_url
            # (Bypassing shared layer to avoid deployment sync issues)
            webhook_url = os.environ.get('WEBHOOK_URL')
            mp_access_token = os.environ.get('MP_ACCESS_TOKEN')

            try:
                # Direct SDK Call
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

                print(f"Creating Preapproval with data: {json.dumps(preapproval_data)}")

                request_options = mercadopago.config.RequestOptions()
                result = sdk.preapproval().create(preapproval_data, request_options)

                if result["status"] == 201:
                    response = result["response"]
                    preapproval_id = response.get("id")
                    init_point = response.get("init_point")
                else:
                    error_msg = result.get("response", {}).get("message", "Unknown error")
                    print(f"MP Create Error: {result}")

                     # Check for Sandbox collision (Real vs Test users)
                    if "payer and collector must be real or test users" in error_msg:
                        raise ValueError("Sandbox Error: Use a Test User email (e.g., test_user_...)")

                    raise RuntimeError(f"Failed to create preapproval: {error_msg}")

            except Exception as e:
                # Fallback for Development/Sandbox Friction
                if "Sandbox Error" in str(e):
                    print("WARNING: Using Mock Subscription due to Sandbox Constraint")
                    price = SubscriptionConfig.PROMO_PRICE if plan_id_str == 'lite' else 15000
                    full_price = 15000
                    preapproval_id = f"mock_{tenant_id}_{int(datetime.utcnow().timestamp())}"
                    init_point = f"{back_url}?status=approved&payment_id={preapproval_id}&mock=true"
                else:
                    raise e


        # 3. Schedule Promo Removal (if applicable)
        scheduler_arn = None
        if price < full_price:
            end_promo_date = datetime.utcnow() + timedelta(days=30 * SubscriptionConfig.PROMO_DURATION_MONTHS)
            schedule_name = f"PromoEnd_{tenant_id}_{preapproval_id}"

            try:
                # Format: yyyy-mm-ddThh:mm:ss
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
                            'subscription_id': preapproval_id,
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

        # 5. Create 'CURRENT' pointer for Webhook Processing
        # This ensures the webhook processor can find the active subscription easily
        sub_current = Subscription(
            tenant_id=tenant_id,
            subscription_id='CURRENT',  # Fixed ID for active sub lookup
            status=SubscriptionStatus.PENDING,
            plan_id=plan_enum,
            current_price=price,
            mp_preapproval_id=preapproval_id,  # Link to real ID
            is_promo_active=True,
            promo_scheduler_arn=scheduler_arn
        )
        SUBSCRIPTIONS_TABLE.put_item(Item=sub_current.to_item())

        # Return data directly for AppSync (not wrapped in HTTP response)
        return {
            'subscriptionId': preapproval_id,
            'initPoint': init_point,
            'message': 'Subscription initialized'
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        raise RuntimeError(f'Internal Server Error: {str(e)}') from e

