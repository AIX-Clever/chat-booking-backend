import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

# Add layer path (adjusting for parallel repo structure)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repos_root = os.path.dirname(project_root)
layer_path = os.path.join(repos_root, 'chat-booking-layers', 'layer', 'python')
# Insert first to take precedence
sys.path.insert(0, layer_path)
sys.path.append(project_root)

# Mock stripe before importing adapter
sys.modules['stripe'] = MagicMock()

# Import dependencies after fixing path
from shared.domain.entities import TenantId, Tenant, BookingStatus, PaymentStatus, Service
from booking.service import BookingService
from shared.infrastructure.payment_factory import PaymentGatewayFactory

class TestPaymentIntegration(unittest.TestCase):

    def setUp(self):
        self.mock_booking_repo = MagicMock()
        self.mock_service_repo = MagicMock()
        self.mock_provider_repo = MagicMock()
        self.mock_tenant_repo = MagicMock()
        self.mock_email_service = MagicMock()
        
        # Mock Factory
        self.mock_gateway = MagicMock()
        self.mock_gateway.create_payment_intent.return_value = {
            'payment_id': 'pi_12345',
            'client_secret': 'secret_abcde',
            'status': 'requires_payment_method'
        }
        
        # Build Service under test
        with patch.object(PaymentGatewayFactory, 'get_gateway', return_value=self.mock_gateway):
            self.booking_service = BookingService(
                booking_repo=self.mock_booking_repo,
                service_repo=self.mock_service_repo,
                provider_repo=self.mock_provider_repo,
                tenant_repo=self.mock_tenant_repo,
                email_service=self.mock_email_service
            )

    @patch('booking.service.PaymentGatewayFactory')
    def test_create_booking_initiates_payment(self, MockFactory):
        print("\n--- Testing Payment Integration ---")
        
        # Setup Mocks
        MockFactory.get_gateway.return_value = self.mock_gateway
        
        # Tenant
        tenant_id = TenantId('tenant-1')
        self.mock_tenant_repo.get_by_id.return_value.can_create_booking.return_value = True
        
        # Service with Price
        mock_service = MagicMock(spec=Service)
        mock_service.is_available.return_value = True
        mock_service.duration_minutes = 60
        mock_service.price = 50.0  # Paid service
        mock_service.currency = 'USD'
        mock_service.name = "Consultation"
        self.mock_service_repo.get_by_id.return_value = mock_service
        
        # Provider
        mock_provider = MagicMock()
        mock_provider.can_provide_service.return_value = True
        mock_provider.name = "Dr. Stripe"
        self.mock_provider_repo.get_by_id.return_value = mock_provider
        
        # No conflicts
        self.mock_booking_repo.list_by_provider.return_value = []
        
        # Execute
        start = datetime.now(timezone.utc) + timedelta(days=2)
        end = start + timedelta(minutes=60)
        
        booking = self.booking_service.create_booking(
            tenant_id=tenant_id,
            service_id='svc-paid',
            provider_id='pro-1',
            start=start,
            end=end,
            client_name='Rich Client',
            client_email='rich@client.com'
        )
        
        # Verify
        self.mock_gateway.create_payment_intent.assert_called_once()
        call_args = self.mock_gateway.create_payment_intent.call_args[1]
        
        print(f"💰 Amount: {call_args['amount']}")
        print(f"💱 Currency: {call_args['currency']}")
        print(f"🆔 PaymentIntent ID: {booking.payment_intent_id}")
        
        self.assertEqual(call_args['amount'], 50.0)
        self.assertEqual(booking.payment_intent_id, 'pi_12345')
        self.assertEqual(booking.payment_client_secret, 'secret_abcde')
        self.assertEqual(booking.status, BookingStatus.PENDING)
        
        print("✅ BookingService successfully initiated Payment Intent")

if __name__ == '__main__':
    unittest.main()
