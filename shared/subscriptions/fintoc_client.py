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
            # SDK Wrapper for link_intents seems missing in this version, using raw request
            response = self.client._client.request(
                path="link_intents",
                method="post",
                json={
                    "product": product,
                    "holder_type": holder_type,
                    "country": country
                }
            )
            return {
                'widget_token': response['widget_token'],
                'link_intent_id': response['id']
            }
        except Exception as e:
            print(f"Error creating link intent: {str(e)}")
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
