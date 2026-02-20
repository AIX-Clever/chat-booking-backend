"""
Fintoc Client wrapper for managing Banking integration.
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

        # Fintoc v2 SDK uses api_key primarily
        self.client = Fintoc(self.api_key)

    def create_link_intent(self, product='movements', holder_type='business', country='cl'):
        """
        Creates a Link Intent to initialize the Fintoc Widget.
        """
        import fintoc
        print(f"[INTERNAL_LOG] Fintoc SDK Version: {getattr(fintoc, '__version__', 'UNKNOWN')}")
        print(f"[INTERNAL_LOG] Fintoc Module Location: {getattr(fintoc, '__file__', 'UNKNOWN')}")
        print(f"[INTERNAL_LOG] FintocClient.create_link_intent called. Product: {product}, Key: {self.api_key[:10]}...")
        try:
            # Re-initialize client if api_key changed
            self.client = Fintoc(self.api_key)
            print(f"[INTERNAL_LOG] Fintoc SDK Client initialized. Object: {self.client}")
            print(f"[INTERNAL_LOG] Available attributes on Fintoc object: {dir(self.client)}")

            # Use SDK manager for link_intents
            if not hasattr(self.client, 'link_intents'):
                 print("[INTERNAL_LOG] CRITICAL ERROR: 'link_intents' attribute missing even after version pin.")
                 if hasattr(self.client, 'links'):
                     print("[INTERNAL_LOG] FOUND 'links' manager version 0.x workaround?")
            
            print(f"[INTERNAL_LOG] Executing self.client.link_intents.create(product='{product}', ...)")
            link_intent = self.client.link_intents.create(
                product=product,
                holder_type=holder_type,
                country=country
            )
            
            print(f"[INTERNAL_LOG] Link Intent creation result type: {type(link_intent)}")
            
            if not link_intent:
                print("[INTERNAL_LOG] Error: Fintoc SDK returned None")
                raise ValueError("Fintoc API returned None (Possible timeout or network issue)")

            # Check for attributes (Python SDK objects have attributes)
            widget_token = getattr(link_intent, 'widget_token', None)
            link_id = getattr(link_intent, 'id', None)
            
            print(f"[INTERNAL_LOG] Extracted widget_token: {widget_token[:10] if widget_token else 'NONE'}...")
            print(f"[INTERNAL_LOG] Extracted link_id: {link_id}")

            if not widget_token or not link_id:
                # Try dictionary access as fallback if it's a dict
                if isinstance(link_intent, dict):
                    widget_token = link_intent.get('widget_token')
                    link_id = link_intent.get('id')
                
                if not widget_token or not link_id:
                    print(f"[INTERNAL_LOG] Error: Missing mandatory fields in link_intent: {link_intent}")
                    raise ValueError(f"Fintoc API result missing fields. Result: {link_intent}")

            return {
                'widget_token': widget_token,
                'link_intent_id': link_id
            }
        except Exception as e:
            print(f"[INTERNAL_LOG] FintocClient Exception: {str(e)}")
            raise e

    def get_movement(self, movement_id, link_token):
        """
        Retrieves a movement (payment) details.
        Requires the link_token associated with the account.
        """
        # Note: Fintoc SDK structure might vary, this is a simplified abstraction
        # In reality, you get movements from an account, which comes from a link.
        pass

    def get_account_info(self, link_token, account_id):
        """
        Retrieves account information.
        """
        pass
