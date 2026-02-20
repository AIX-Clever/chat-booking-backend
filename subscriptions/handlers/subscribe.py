
# Initialize resource at top level (AWS SDK is usually safe and handled by Lambda runtime)
import boto3
dynamodb = boto3.resource('dynamodb')
scheduler = boto3.client('scheduler')

def lambda_handler(event, _context):
    """
    Handles subscription creation requests with extreme logging and safe imports.
    """
    import json
    import os
    import mercadopago
    from datetime import datetime, timedelta
    
    print(f"[INTERNAL_LOG] Starting subscribe handler. Event: {json.dumps(event)}")
    
    try:
        # ABSOLUTELY ALL IMPORTS INSIDE HANDLER FOR DEBUGGING
        print("[INTERNAL_LOG] Executing late-bound imports...")
        from shared.utils import extract_tenant_id
        from shared.subscriptions.config import SubscriptionConfig
        from shared.subscriptions.entities import Subscription, SubscriptionStatus, PlanType
        
        # Extract tenant_id from AppSync event
        tenant_id = extract_tenant_id(event)
        if not tenant_id:
            print("[INTERNAL_LOG] Error: Missing tenantId")
            return {
                'subscriptionId': 'ERROR',
                'initPoint': '',
                'message': 'Missing tenantId in request context'
            }

        # Extract arguments from AppSync event
        args = event.get('arguments', {})
        plan_id_str = args.get('planId', 'lite')
        payer_email = args.get('email')
        payment_method = args.get("paymentMethod", "mercadopago")
        back_url = args.get('backUrl', 'https://control.holalucia.cl')
        
        print(f"[INTERNAL_LOG] Params: tenant={tenant_id}, method={payment_method}, plan={plan_id_str}, email={payer_email}")

        # Validate inputs
        if not payer_email:
             return {
                'subscriptionId': 'ERROR',
                'initPoint': '',
                'message': 'Missing email'
            }

        try:
            plan_enum = PlanType(plan_id_str)
        except ValueError as exc:
            print(f"[INTERNAL_LOG] Error: Invalid plan {plan_id_str}")
            return {
                'subscriptionId': 'ERROR',
                'initPoint': '',
                'message': f'Invalid planId: {plan_id_str}'
            }

        # Determine Price
        full_price = SubscriptionConfig.PLAN_PRICES.get(plan_id_str, 15000)
        price = SubscriptionConfig.PROMO_PRICE if plan_id_str == 'lite' else full_price

        preapproval_id = None
        init_point = None

        if payment_method == 'fintoc':
            print("[INTERNAL_LOG] Flow: Fintoc")
            try:
                # SEPARATED INIT: Only import Fintoc if needed
                from shared.subscriptions.fintoc_client import FintocClient
                fintoc_client = FintocClient()
                
                fintoc_env = os.environ.get('FINTOC_ENV', 'live')
                fintoc_client.environment = fintoc_env
                
                print(f"[INTERNAL_LOG] Calling fintoc_client.create_link_intent() in {fintoc_env}")
                result = fintoc_client.create_link_intent()
                print(f"[INTERNAL_LOG] Fintoc Result: {result}")
                
                if not result or 'widget_token' not in result or 'link_intent_id' not in result:
                    print(f"[INTERNAL_LOG] Error: Fintoc invalid result format: {result}")
                    return {
                        'subscriptionId': 'ERROR',
                        'initPoint': '',
                        'message': f"Fintoc returned an invalid response format: {result}"
                    }

                preapproval_id = result['link_intent_id']
                init_point = result['widget_token']
                print(f"[INTERNAL_LOG] Fintoc ID: {preapproval_id}")

            except Exception as e:
                print(f"[INTERNAL_LOG] Fintoc Exception: {str(e)}")
                return {
                        'subscriptionId': 'ERROR',
                        'initPoint': '',
                        'message': f"Fintoc Error: {str(e)}"
                }

        else:
            print("[INTERNAL_LOG] Flow: MercadoPago")
            try:
                # SEPARATED INIT: Only import MP if needed
                from shared.subscriptions.mercadopago_client import MercadoPagoClient
                import mercadopago
                
                mp_client = MercadoPagoClient()
                webhook_url = os.environ.get('WEBHOOK_URL')
                mp_access_token = os.environ.get('MP_ACCESS_TOKEN')

                if not mp_access_token:
                    print("[INTERNAL_LOG] Error: Missing MP_ACCESS_TOKEN")
                    return {
                        'subscriptionId': 'ERROR',
                        'initPoint': '',
                        'message': "MercadoPago configuration missing"
                    }

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
                    return {
                        'subscriptionId': 'ERROR',
                        'initPoint': '',
                        'message': f"Failed to create MP preapproval: {error_msg}"
                    }

            except Exception as e:
                print(f"[INTERNAL_LOG] MP Exception: {str(e)}")
                return {
                        'subscriptionId': 'ERROR',
                        'initPoint': '',
                        'message': f"MercadoPago Error: {str(e)}"
                }

        # Final check before persistence
        if not preapproval_id or not init_point:
            print(f"[INTERNAL_LOG] Error: Resulting IDs are null. subId={preapproval_id}, init={init_point}")
             return {
                    'subscriptionId': 'ERROR',
                    'initPoint': '',
                    'message': "Internal Error: Gateway response incomplete"
            }

        # 4. Persistence
        print("[INTERNAL_LOG] Persisting subscription to DynamoDB...")
        try:
            from shared.subscriptions.config import SubscriptionConfig
            SUBSCRIPTIONS_TABLE_NAME = SubscriptionConfig.SUBSCRIPTIONS_TABLE
            table = dynamodb.Table(SUBSCRIPTIONS_TABLE_NAME)
            
            sub = Subscription(
                tenant_id=tenant_id,
                subscription_id=preapproval_id,
                status=SubscriptionStatus.PENDING,
                plan_id=plan_enum,
                current_price=price,
                mp_preapproval_id=preapproval_id,
                is_promo_active=True
            )
            table.put_item(Item=sub.to_item())
            
            # Create 'CURRENT' pointer
            sub_current = Subscription(
                tenant_id=tenant_id,
                subscription_id='CURRENT',
                status=SubscriptionStatus.PENDING,
                plan_id=plan_enum,
                current_price=price,
                mp_preapproval_id=preapproval_id,
                is_promo_active=True
            )
            table.put_item(Item=sub_current.to_item())
        except Exception as e:
            print(f"[INTERNAL_LOG] DynamoDB Persistence Exception: {str(e)}")
            # Even if persistence fails, we might want to return the initPoint so the user can pay?
            # No, better fail and ask to try again to avoid sync issues.
             return {
                    'subscriptionId': 'ERROR',
                    'initPoint': '',
                    'message': f"Database Error: {str(e)}"
            }

        print(f"[INTERNAL_LOG] Handler finished successfully for {tenant_id}")
        return {
            'subscriptionId': str(preapproval_id),
            'initPoint': str(init_point),
            'message': 'Subscription initialized'
        }

    except Exception as e:
        print(f"[INTERNAL_LOG] UNHANDLED EXCEPTION: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'subscriptionId': 'CRITICAL_ERROR',
            'initPoint': '',
            'message': f'Internal Server Error: {str(e)}'
        }

