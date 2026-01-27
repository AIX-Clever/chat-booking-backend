
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

from shared.domain.entities import TenantId, Booking, BookingStatus, Service, Provider, CustomerInfo, PaymentStatus
from booking.service import BookingService
from shared.metrics import MetricsService

class TestBookingServiceMetrics(unittest.TestCase):
    def setUp(self):
        self.booking_repo = MagicMock()
        self.service_repo = MagicMock()
        self.provider_repo = MagicMock()
        self.tenant_repo = MagicMock()
        self.metrics_service = MagicMock(spec=MetricsService)
        
        self.service = BookingService(
            booking_repo=self.booking_repo,
            service_repo=self.service_repo,
            provider_repo=self.provider_repo,
            tenant_repo=self.tenant_repo,
            metrics_service=self.metrics_service
        )

    def test_create_booking_metrics(self):
        # Setup mocks
        tenant_id = TenantId("tenant1")
        service_id = "svc1"
        provider_id = "prov1"
        start = datetime.now(UTC) + timedelta(hours=1)
        end = start + timedelta(minutes=60)
        
        self.tenant_repo.get_by_id.return_value.can_create_booking.return_value = True
        
        service = MagicMock(spec=Service)
        service.duration_minutes = 60
        service.is_available.return_value = True
        service.price = 100.0
        service.name = "Test Service"
        service.currency = "USD"
        service.required_room_ids = []
        self.service_repo.get_by_id.return_value = service
        
        provider = MagicMock(spec=Provider)
        provider.can_provide_service.return_value = True
        provider.name = "Test Provider"
        provider.timezone = "UTC"
        self.provider_repo.get_by_id.return_value = provider
        
        # Act
        self.service.create_booking(
            tenant_id=tenant_id,
            service_id=service_id,
            provider_id=provider_id,
            start=start,
            end=end,
            client_name="John Doe",
            client_email="john@example.com"
        )
        
        # Assert
        self.metrics_service.increment_booking.assert_called_once()
        call_args = self.metrics_service.increment_booking.call_args[1]
        self.assertEqual(call_args['tenant_id'], "tenant1")
        self.assertEqual(call_args['service_id'], "svc1")
        self.assertEqual(call_args['amount'], 100.0)
        
        self.metrics_service.increment_funnel_step.assert_called_with(
            "tenant1", "booking_completed"
        )

    def test_confirm_booking_metrics(self):
        tenant_id = TenantId("tenant1")
        booking_id = "bkg1"
        
        booking = MagicMock(spec=Booking)
        booking.status = BookingStatus.PENDING
        booking.tenant_id = tenant_id
        
        self.booking_repo.get_by_id.return_value = booking
        
        self.service.confirm_booking(tenant_id, booking_id)
        
        booking.confirm.assert_called_once()
        self.metrics_service.update_booking_status.assert_called_with(
            "tenant1", "PENDING", "CONFIRMED"
        )

    def test_cancel_booking_metrics(self):
        tenant_id = TenantId("tenant1")
        booking_id = "bkg1"
        
        booking = MagicMock(spec=Booking)
        booking.status = BookingStatus.CONFIRMED # Assumption
        booking.tenant_id = tenant_id
        
        self.booking_repo.get_by_id.return_value = booking
        
        self.service.cancel_booking(tenant_id, booking_id)
        
        booking.cancel.assert_called_once()
        self.metrics_service.update_booking_status.assert_called_with(
            "tenant1", "CONFIRMED", "CANCELLED"
        )

if __name__ == '__main__':
    unittest.main()
