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

    def create_link_intent(self, product='movements', holder_type='business', country='cl'):
        """
        Creates a Subscription Intent to initialize the Fintoc Widget.

        NOTE: The `link_intents` manager does not exist in the Fintoc Python SDK.
        The correct resource for subscriptions is `subscription_intents`.
        """
        import fintoc as fintoc_module
        print(f"[INTERNAL_LOG] Fintoc SDK Version: {getattr(fintoc_module, '__version__', 'UNKNOWN')}")
        print(f"[INTERNAL_LOG] FintocClient.create_link_intent called. Using: subscription_intents")
        try:
            self.client = Fintoc(self.api_key)
            print(f"[INTERNAL_LOG] Available managers: {[a for a in dir(self.client) if not a.startswith('_')]}")

            print(f"[INTERNAL_LOG] Calling self.client.subscription_intents.create()")
            subscription_intent = self.client.subscription_intents.create()

            print(f"[INTERNAL_LOG] subscription_intent type: {type(subscription_intent)}")
            print(f"[INTERNAL_LOG] subscription_intent attrs: {dir(subscription_intent)}")

            if not subscription_intent:
                raise ValueError("Fintoc API returned None for subscription_intent")

            # Extract widget_token and id
            widget_token = getattr(subscription_intent, 'widget_token', None)
            if widget_token is None and isinstance(subscription_intent, dict):
                widget_token = subscription_intent.get('widget_token')

            link_id = getattr(subscription_intent, 'id', None)
            if link_id is None and isinstance(subscription_intent, dict):
                link_id = subscription_intent.get('id')

            print(f"[INTERNAL_LOG] widget_token: {str(widget_token)[:10] if widget_token else 'NONE'}...")
            print(f"[INTERNAL_LOG] subscription_intent id: {link_id}")

            if not widget_token or not link_id:
                raise ValueError(
                    f"Fintoc subscription_intent missing mandatory fields. "
                    f"Got: widget_token={widget_token}, id={link_id}"
                )

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
