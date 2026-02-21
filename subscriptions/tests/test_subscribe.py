
import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import types

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

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

    @patch('subscriptions.handlers.subscribe.dynamodb')
    def test_fintoc_flow(self, mock_dynamodb):
        # Setup
        event = {
            'identity': {'claims': {'custom:tenantId': 'tenant-123'}},
            'arguments': {
                'email': 'test@example.com',
                'planId': 'lite',
                'paymentMethod': 'fintoc'
            }
        }

        mock_fintoc = MagicMock()
        mock_fintoc.create_link_intent.return_value = {
            'widget_token': 'wt_123',
            'link_intent_id': 'li_123'
        }
        fake_fintoc_module = types.ModuleType('shared.subscriptions.fintoc_client')
        fake_fintoc_module.FintocClient = MagicMock(return_value=mock_fintoc)

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        # Execute
        with patch.dict(sys.modules, {'shared.subscriptions.fintoc_client': fake_fintoc_module}):
            response = lambda_handler(event, None)

        # Verify
        mock_fintoc.create_link_intent.assert_called_once()
        self.assertEqual(response['subscriptionId'], 'li_123')
        self.assertEqual(response['initPoint'], 'wt_123')
        self.assertEqual(mock_table.put_item.call_count, 2)

    @patch('subscriptions.handlers.subscribe.dynamodb')
    def test_mercadopago_flow(self, mock_dynamodb):
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
        mock_sdk_ctor = MagicMock(return_value=mock_sdk_instance)
        mock_sdk_instance.preapproval().create.return_value = {
            "status": 201,
            "response": {
                "id": "mp_123",
                "init_point": "https://mp.com/init"
            }
        }
        fake_mp_module = types.ModuleType('mercadopago')
        fake_mp_module.SDK = mock_sdk_ctor
        fake_mp_module.config = types.SimpleNamespace(
            RequestOptions=MagicMock(return_value=MagicMock())
        )

        fake_mp_client_module = types.ModuleType(
            'shared.subscriptions.mercadopago_client'
        )
        fake_mp_client_module.MercadoPagoClient = MagicMock(
            return_value=MagicMock()
        )

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        # Execute
        with patch.dict(
            sys.modules,
            {
                'mercadopago': fake_mp_module,
                'shared.subscriptions.mercadopago_client': fake_mp_client_module,
            },
        ):
            response = lambda_handler(event, None)

        # Verify
        mock_sdk_instance.preapproval().create.assert_called_once()
        self.assertEqual(response['subscriptionId'], 'mp_123')
        self.assertEqual(response['initPoint'], 'https://mp.com/init')
        self.assertEqual(mock_table.put_item.call_count, 2)
