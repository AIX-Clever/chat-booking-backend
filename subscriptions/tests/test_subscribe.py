
import unittest
from unittest.mock import MagicMock, patch
import os
import json
from subscriptions.handlers.subscribe import lambda_handler

class TestSubscribe(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {
            'WORKER_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:worker',
            'SCHEDULER_ROLE_ARN': 'arn:aws:iam::123456789012:role/scheduler-role',
            'WEBHOOK_URL': 'https://api.example.com/webhook',
            'MP_ACCESS_TOKEN': 'test_token',
            'FINTOC_API_KEY': 'test_fintoc_key'
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @patch('subscriptions.handlers.subscribe.fintoc_client')
    @patch('subscriptions.handlers.subscribe.mp_client')
    @patch('subscriptions.handlers.subscribe.subscription_service')
    @patch('subscriptions.handlers.subscribe.SUBSCRIPTIONS_TABLE')
    @patch('subscriptions.handlers.subscribe.scheduler')
    @patch('subscriptions.handlers.subscribe.mercadopago.SDK')
    def test_fintoc_flow(self, mock_mp_sdk, mock_scheduler, mock_table, mock_service, mock_mp_client, mock_fintoc_client):
        # Setup
        event = {
            'identity': {'claims': {'custom:tenantId': 'tenant-123'}},
            'arguments': {
                'email': 'test@example.com',
                'planId': 'lite',
                'paymentMethod': 'fintoc'
            }
        }
        
        # Mock Fintoc response
        # The FintocClient now calls self.client._client.request
        mock_fintoc_instance = MagicMock()
        mock_fintoc_client.return_value = mock_fintoc_instance # This mocks the FintocClient() constructor return
        
        # However, subscribe.py imports FintocClient class and instantiates it.
        # But we are mocking 'subscriptions.handlers.subscribe.fintoc_client' which is arguably the Instance or the Module?
        # In subscribe.py: fintoc_client = FintocClient() (GLOBAL)
        # So mocking 'subscriptions.handlers.subscribe.fintoc_client' mocks the INSTANCE directly if we patch the right name.
        # But 'fintoc_client' is a variable name.
        
        # Actually @patch('subscriptions.handlers.subscribe.fintoc_client') mocks the OBJECT 'fintoc_client' in that module.
        # So mock_fintoc_client IS the mock object.
        
        mock_fintoc_client.create_link_intent.return_value = {
            'widget_token': 'wt_123',
            'link_intent_id': 'li_123'
        }

        # Execute
        response = lambda_handler(event, None)

        # Verify
        mock_fintoc_client.create_link_intent.assert_called_once()
        self.assertEqual(response['subscriptionId'], 'li_123')
        self.assertEqual(response['initPoint'], 'wt_123')
        
        # Verify Persistence
        mock_table.put_item.assert_called()

    @patch('subscriptions.handlers.subscribe.fintoc_client')
    @patch('subscriptions.handlers.subscribe.mp_client')
    @patch('subscriptions.handlers.subscribe.subscription_service')
    @patch('subscriptions.handlers.subscribe.SUBSCRIPTIONS_TABLE')
    @patch('subscriptions.handlers.subscribe.scheduler')
    @patch('subscriptions.handlers.subscribe.mercadopago.SDK')
    def test_mercadopago_flow(self, mock_mp_sdk, mock_scheduler, mock_table, mock_service, mock_mp_client, mock_fintoc_client):
         # Setup
        event = {
            'identity': {'claims': {'custom:tenantId': 'tenant-123'}},
            'arguments': {
                'email': 'test@example.com',
                'planId': 'lite',
                'paymentMethod': 'mercadopago'
            }
        }
        
        # Mock MP Response
        mock_sdk_instance = MagicMock()
        mock_mp_sdk.return_value = mock_sdk_instance
        mock_sdk_instance.preapproval().create.return_value = {
            "status": 201,
            "response": {
                "id": "mp_123",
                "init_point": "https://mp.com/init"
            }
        }

        # Execute
        response = lambda_handler(event, None)

        # Verify
        mock_sdk_instance.preapproval().create.assert_called_once()
        self.assertEqual(response['subscriptionId'], 'mp_123')
        self.assertEqual(response['initPoint'], 'https://mp.com/init')
