import os
import json
import boto3
from fintoc import Client

def lambda_handler(event, context):
    try:
        # 1. Initialize Fintoc Client (Test Mode)
        api_key = os.environ.get('FINTOC_API_KEY')
        client = Client(api_key, type_of_environment='test') # 'live' for prod

        # 2. Create Link Intent
        # This generates the URL/Token for the frontend widget
        link_intent = client.link_intents.create(
            product='movements',
            holder_type='business', # or 'individual'
            country='cl'
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'widget_token': link_intent.widget_token,
                'link_intent_id': link_intent.id
            })
        }

    except Exception as e:
        print(f"Error creating Fintoc Link Intent: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
