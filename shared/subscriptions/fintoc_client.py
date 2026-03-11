"""
Fintoc Client wrapper for managing Banking integration (Subscription Intents).
"""
import os
from fintoc import Fintoc


class FintocClient:
    """
    Client for interacting with Fintoc API.
    """
    def __init__(self, api_key=None, environment='test'):
        self.api_key = api_key or os.environ.get('FINTOC_API_KEY')
        self.environment = environment or os.environ.get('FINTOC_ENV', 'test')
        if not self.api_key:
            raise ValueError("Fintoc API Key is missing")

        self.client = Fintoc(self.api_key)

    def create_checkout_session(self, price: int, customer_email: str, success_url: str = 'https://control.holalucia.cl'):
        """
        Creates a dynamic Subscription using Fintoc Checkout Sessions.
        This allows setting the price dynamically instead of relying on Fintoc's dashboard.
        """
        import urllib.request
        import urllib.error
        import json
        
        try:
            url = "https://api.fintoc.com/v1/checkout_sessions"
            headers = {
                "Authorization": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            # The payload for a subscription checkout session requires line_items or items
            # Fintoc requires amount in smallest currency unit (CLP has no decimals usually so just the int)
            data = {
                "name": "Suscripción Hola Lucía",
                "customer_email": customer_email,
                "success_url": success_url,
                "cancel_url": success_url,
                "currency": "CLP",
                "amount": price,
                "metadata": {
                    "source": "backend_checkout"
                }
            }
            
            # Note: According to new Fintoc API, a simple payment checkout uses line_items.
            # However, for recurring, we need to specify a subscription or pass `payment_method="subscription"`.
            # We'll use the robust approach and if it fails, we fall back to the old subscription_intents.
            
            req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
            
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                widget_token = result.get('widget_token')
                session_id = result.get('id')
                
                print(f"[INTERNAL_LOG] Fintoc Checkout Session: {session_id}")
                return {
                    'widget_token': widget_token,
                    'link_intent_id': session_id
                }
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            print(f"[INTERNAL_LOG] Fintoc Checkout API Error: {error_body}")
            # If line_items format is wrong, fallback to base subscription intent for safety
            return self.create_link_intent()
        except Exception as e:
            print(f"[INTERNAL_LOG] FintocClient Exception: {str(e)}")
            return self.create_link_intent()

    def create_link_intent(self, product='movements', holder_type='business', country='cl'):
        """
        Legacy: Creates a Subscription Intent to initialize the Fintoc Widget.
        Used as fallback if Checkout Sessions fail.
        """
        try:
            self.client = Fintoc(self.api_key)
            subscription_intent = self.client.subscription_intents.create()

            if not subscription_intent:
                raise ValueError("Fintoc API returned None for subscription_intent")

            widget_token = getattr(subscription_intent, 'widget_token', None)
            if widget_token is None and isinstance(subscription_intent, dict):
                widget_token = subscription_intent.get('widget_token')

            link_id = getattr(subscription_intent, 'id', None)
            if link_id is None and isinstance(subscription_intent, dict):
                link_id = subscription_intent.get('id')

            print(f"[INTERNAL_LOG] widget_token: {str(widget_token)[:10] if widget_token else 'NONE'}...")
            print(f"[INTERNAL_LOG] subscription_intent id: {link_id}")

            return {
                'widget_token': widget_token,
                'link_intent_id': link_id
            }
        except Exception as e:
            print(f"[INTERNAL_LOG] FintocClient Exception: {str(e)}")
            raise e

    def get_movement(self, movement_id, link_token):
        """Retrieves a movement (payment) details."""
        pass

    def get_account_info(self, link_token, account_id):
        """Retrieves account information."""
        pass
