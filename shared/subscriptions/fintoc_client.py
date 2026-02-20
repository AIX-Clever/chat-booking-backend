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
        try:
            # Re-initialize client if api_key changed
            self.client = Fintoc(self.api_key)

            # Use SDK manager for link_intents
            link_intent = self.client.link_intents.create(
                product=product,
                holder_type=holder_type,
                country=country
            )
            
            if not link_intent or not hasattr(link_intent, 'widget_token'):
                print(f"Fintoc SDK result error: {link_intent}")
                raise ValueError(f"Fintoc API returned unexpected result: {link_intent}")

            return {
                'widget_token': link_intent.widget_token,
                'link_intent_id': link_intent.id
            }
        except Exception as e:
            print(f"Fintoc SDK Error in create_link_intent: {str(e)}")
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
