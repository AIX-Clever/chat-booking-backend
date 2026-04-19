import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import os

# Set environment variables for testing
os.environ['DTE_QUEUE_URL'] = 'https://sqs.us-east-1.amazonaws.com/12345/dte-queue'
os.environ['MP_ACCESS_TOKEN_PROD'] = 'test-token'

from payment.webhook_handler import _issue_dte
from subscriptions.handlers.webhook_processor import _issue_subscription_dte
from shared.domain.entities import TenantId, CustomerInfo, Booking, BookingStatus, PaymentStatus

class TestDynamicDteIntegration(unittest.TestCase):

    @patch('boto3.client')
    def test_issue_dte_booking_sends_boleta_39(self, mock_boto):
        # Setup
        mock_sqs = MagicMock()
        mock_boto.return_value = mock_sqs
        
        booking = MagicMock()
        booking.booking_id = "bkg-123"
        booking.tenant_id = TenantId("tenant-abc")
        booking.total_amount = 10000
        booking.customer_info = CustomerInfo(
            customer_id="cust-1",
            given_name="John",
            family_name="Doe",
            email="john@example.com",
            phone="+56912345678"
        )
        
        # Execute
        _issue_dte(booking, "pay-123")
        
        # Verify
        mock_sqs.send_message.assert_called_once()
        args, kwargs = mock_sqs.send_message.call_args
        payload = json.loads(kwargs['MessageBody'])
        
        self.assertEqual(payload['tipoDte'], 39)
        self.assertEqual(payload['bookingId'], "bkg-123")
        self.assertEqual(payload['tenantId'], "tenant-abc")

    @patch('boto3.client')
    def test_issue_subscription_dte_sends_factura_33_if_billing_present(self, mock_boto):
        # Setup
        mock_sqs = MagicMock()
        mock_boto.return_value = mock_sqs
        
        tenant = MagicMock()
        tenant.tenant_id = TenantId("tenant-paying")
        tenant.name = "My Company"
        tenant.billing_email = "billing@company.com"
        tenant.settings = {
            'billing': {
                'rut': '12.345.678-9',
                'name': 'My Company Inc',
                'address': 'Calle Falsa 123',
                'comuna': 'Santiago'
            }
        }
        
        # Execute
        _issue_subscription_dte(tenant, "pay-sub-123", 29990.0)
        
        # Verify
        mock_sqs.send_message.assert_called_once()
        args, kwargs = mock_sqs.send_message.call_args
        payload = json.loads(kwargs['MessageBody'])
        
        self.assertEqual(payload['tipoDte'], 33)
        self.assertEqual(payload['tenantId'], 'holalucia') # Emisor is Hola Lucia
        self.assertEqual(payload['customer']['rut'], '12.345.678-9')
        self.assertEqual(payload['subscription_tenant_id'], 'tenant-paying')

    @patch('boto3.client')
    def test_issue_subscription_dte_sends_boleta_39_if_no_billing_rut(self, mock_boto):
        # Setup
        mock_sqs = MagicMock()
        mock_boto.return_value = mock_sqs
        
        tenant = MagicMock()
        tenant.tenant_id = TenantId("tenant-lite")
        tenant.name = "Sole Professional"
        tenant.billing_email = "sole@pro.com"
        tenant.settings = {} # No billing info
        
        # Execute
        _issue_subscription_dte(tenant, "pay-sub-456", 9990.0)
        
        # Verify
        mock_sqs.send_message.assert_called_once()
        args, kwargs = mock_sqs.send_message.call_args
        payload = json.loads(kwargs['MessageBody'])
        
        self.assertEqual(payload['tipoDte'], 39)
        self.assertEqual(payload['tenantId'], 'holalucia')
        self.assertEqual(payload['customer']['name'], "Sole Professional")

if __name__ == '__main__':
    unittest.main()
