import sys
import os
import unittest
import json
from unittest.mock import MagicMock, patch

os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Add layer path 
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repos_root = os.path.dirname(project_root)
layer_path = os.path.join(repos_root, 'chat-booking-layers', 'layer', 'python')

sys.path.insert(0, layer_path)
sys.path.append(project_root)

# Mock stripe
sys.modules['stripe'] = MagicMock()

from payment.webhook_handler import lambda_handler
from shared.domain.entities import TenantId, Booking, PaymentStatus, BookingStatus
from shared.infrastructure.payment_factory import PaymentGatewayFactory

class TestWebhookHandler(unittest.TestCase):

    def setUp(self):
        self.mock_repo = MagicMock()
        
        # Patch dependencies
        self.repo_patcher = patch('payment.webhook_handler.booking_repo', self.mock_repo)
        self.repo_patcher.start()
        
        self.email_patcher = patch('payment.webhook_handler.email_service')
        self.email_patcher.start()
        
    def tearDown(self):
        self.repo_patcher.stop()
        self.email_patcher.stop()

    @patch('payment.webhook_handler.boto3.client')
    @patch('shared.infrastructure.payment_factory.PaymentGatewayFactory.get_gateway_by_name')
    def test_stripe_webhook_success(self, mock_get_gateway, mock_boto3_client):
        print("\n--- Testing Webhook Handler (Stripe + SQS) ---")
        
        # 1. Setup Mock Gateway
        mock_gateway = MagicMock()
        mock_get_gateway.return_value = mock_gateway
        
        # 2. Setup Mock SQS
        mock_sqs = MagicMock()
        mock_boto3_client.return_value = mock_sqs
        os.environ['DTE_QUEUE_URL'] = 'http://mock-queue'
        
        # Mock payload verification
        mock_gateway.verify_webhook_signature.return_value = {
            'type': 'payment_intent.succeeded',
            'data': {
                'object': {
                    'id': 'pi_123',
                    'metadata': {
                        'booking_id': 'bkg_1',
                        'tenant_id': 'tenant-A'
                    }
                }
            }
        }
        
        # 3. Setup Mock Booking
        mock_booking = MagicMock()
        mock_booking.booking_id = 'bkg_1'
        mock_booking.tenant_id = TenantId('tenant-A')
        mock_booking.total_amount = 25000
        mock_booking.customer_info.name = "Juan"
        mock_booking.customer_info.email = "juan@example.com"
        mock_booking.customer_info.phone = "+56912345678"
        mock_booking.payment_status = PaymentStatus.PENDING
        mock_booking.status = BookingStatus.PENDING
        self.mock_repo.get_by_id.return_value = mock_booking
        
        # 4. Simulate Event
        event = {
            'headers': {
                'stripe-signature': 'sig_123'
            },
            'body': '{"dummy": "payload"}'
        }
        
        # 5. Execute
        response = lambda_handler(event, {})
        
        # 6. Verify
        self.assertEqual(response['statusCode'], 200)
        
        # Verify Booking Update
        self.mock_repo.get_by_id.assert_called_with(TenantId('tenant-A'), 'bkg_1')
        self.mock_repo.update.assert_called_once()
        
        # Verify SQS Enqueued
        mock_sqs.send_message.assert_called_once()
        call_args = mock_sqs.send_message.call_args[1]
        self.assertEqual(call_args['QueueUrl'], 'http://mock-queue')
        payload = json.loads(call_args['MessageBody'])
        self.assertEqual(payload['bookingId'], 'bkg_1')
        self.assertEqual(payload['amount'], 25000)
        
        print("✅ Webhook correctly flagged booking as PAID and ENQUEUED DTE task")

if __name__ == '__main__':
    unittest.main()
