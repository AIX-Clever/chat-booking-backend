import os
import json
from fintoc import Client

class FintocClient:
    def __init__(self, api_key=None, environment='test'):
        self.api_key = api_key or os.environ.get('FINTOC_API_KEY')
        self.environment = environment or os.environ.get('FINTOC_ENV', 'test')
        if not self.api_key:
            raise Exception("Fintoc API Key is missing")
        
        self.client = Client(self.api_key, type_of_environment=self.environment)

    def create_link_intent(self, product='movements', holder_type='business', country='cl'):
        """
        Creates a Link Intent to initialize the Fintoc Widget.
        """
        try:
            link_intent = self.client.link_intents.create(
                product=product,
                holder_type=holder_type,
                country=country
            )
            return {
                'widget_token': link_intent.widget_token,
                'link_intent_id': link_intent.id
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
        pass
