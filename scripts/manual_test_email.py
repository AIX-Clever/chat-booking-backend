import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Add layer path (adjusting for parallel repo structure)
# We are in chat-booking-backend/scripts, so we need to go up two levels to repos/conversacion, 
# then down to chat-booking-layers/layer/python
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repos_root = os.path.dirname(project_root)
layer_path = os.path.join(repos_root, 'chat-booking-layers', 'layer', 'python')
# Insert first to take precedence over any local layer/python
sys.path.insert(0, layer_path)

# Add backend path
sys.path.append(project_root)

print(f"DEBUG: Layer Path: {layer_path}")
print(f"DEBUG: Project Root: {project_root}")
print(f"DEBUG: sys.path: {sys.path}")

from shared.infrastructure.notifications import EmailService
from booking.service import BookingService # Adjusted import to match backend structure
from shared.domain.entities import TenantId, Booking, BookingStatus, PaymentStatus, CustomerInfo

class TestEmailIntegration(unittest.TestCase):

    def setUp(self):
        # Mocks
        self.mock_booking_repo = MagicMock()
        self.mock_service_repo = MagicMock()
        self.mock_provider_repo = MagicMock()
        self.mock_tenant_repo = MagicMock()
        self.mock_boto_client = MagicMock()
        
        # Service under test
        with patch('boto3.client', return_value=self.mock_boto_client):
            self.email_service = EmailService()
        
        self.booking_service = BookingService(
            booking_repo=self.mock_booking_repo,
            service_repo=self.mock_service_repo,
            provider_repo=self.mock_provider_repo,
            tenant_repo=self.mock_tenant_repo,
            email_service=self.email_service
        )

    def test_email_service_sends_correct_payload(self):
        print("\n--- Testing EmailService low-level ---")
        self.email_service.send_email(
            source='sender@test.com',
            to_addresses=['recipient@test.com'],
            subject='Test Subject',
            body_html='<p>Test</p>',
            body_text='Test'
        )
        
        self.mock_boto_client.send_email.assert_called_once()
        call_args = self.mock_boto_client.send_email.call_args[1]
        self.assertEqual(call_args['Source'], 'sender@test.com')
        self.assertEqual(call_args['Destination']['ToAddresses'], ['recipient@test.com'])
        print("✅ EmailService called boto3.send_email correctly")

    def test_create_booking_triggers_email(self):
        print("\n--- Testing BookingService triggers email ---")
        
        # Setup specific mocks for create_booking flow
        tenant_id = TenantId('tenant-1')
        self.mock_tenant_repo.get_by_id.return_value.can_create_booking.return_value = True
        
        mock_service = MagicMock()
        mock_service.is_available.return_value = True
        mock_service.duration_minutes = 60
        mock_service.price = 100
        mock_service.name = "Test Service"
        self.mock_service_repo.get_by_id.return_value = mock_service
        
        mock_provider = MagicMock()
        mock_provider.can_provide_service.return_value = True
        mock_provider.name = "Dr. Test"
        self.mock_provider_repo.get_by_id.return_value = mock_provider
        
        # Mock repo list to return empty (no conflicts)
        self.mock_booking_repo.list_by_provider.return_value = []
        
        # Execute
        start = datetime.now() + timedelta(days=1)
        end = start + timedelta(minutes=60)
        
        self.booking_service.create_booking(
            tenant_id=tenant_id,
            service_id='svc-1',
            provider_id='pro-1',
            start=start,
            end=end,
            client_name='Juan Perez',
            client_email='juan@test.com'
        )
        
        # Verify
        self.mock_boto_client.send_email.assert_called()
        call_args = self.mock_boto_client.send_email.call_args[1]
        print(f"📧 Email sent to: {call_args['Destination']['ToAddresses']}")
        print(f"📧 Subject: {call_args['Message']['Subject']['Data']}")
        
        self.assertIn('juan@test.com', call_args['Destination']['ToAddresses'])
        self.assertIn('Reserva Confirmada', call_args['Message']['Subject']['Data'])
        self.assertIn('Dr. Test', call_args['Message']['Body']['Html']['Data'])
        print("✅ BookingService successfully triggered confirmation email")

if __name__ == '__main__':
    unittest.main()
