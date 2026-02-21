import unittest
from datetime import datetime, timedelta, UTC
from unittest.mock import Mock, patch
from shared.domain.entities import (
    TenantId,
    Booking,
    BookingStatus,
    PaymentStatus,
    CustomerInfo,
    Service,
)
from shared.application.booking_service import BookingService
from shared.domain.exceptions import SlotNotAvailableError

class TestBookingService(unittest.TestCase):
    def setUp(self):
        self.mock_booking_repo = Mock()
        self.mock_service_repo = Mock()
        self.mock_provider_repo = Mock()
        self.mock_tenant_repo = Mock()
        self.mock_availability_service = Mock()
        
        self.service = BookingService(
            booking_repo=self.mock_booking_repo,
            service_repo=self.mock_service_repo,
            provider_repo=self.mock_provider_repo,
            tenant_repo=self.mock_tenant_repo,
            availability_service=self.mock_availability_service
        )
        
        self.tenant_id = TenantId("tenant-123")
        self.service_id = "svc-1"
        self.provider_id = "pro-1"
        
        # Mock active tenant
        self.mock_tenant = Mock()
        self.mock_tenant.is_active.return_value = True
        self.mock_tenant_repo.get_by_id.return_value = self.mock_tenant

        # Mock service
        self.mock_service = Mock(spec=Service)
        self.mock_service.service_id = self.service_id
        self.mock_service.name = "Test Service"
        self.mock_service.duration_minutes = 60
        self.mock_service.price = 100.0
        self.mock_service_repo.get_by_id.return_value = self.mock_service

    def test_create_booking_success_paid(self):
        """Test successful booking creation when slot is available for PAID service"""
        # 1. Setup mocks
        self.mock_availability_service.is_slot_available.return_value = True
        self.mock_service.price = 100.0
        
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        end = start + timedelta(minutes=60)
        
        # 2. Execute
        booking = self.service.create_booking(
            tenant_id=self.tenant_id,
            service_id=self.service_id,
            provider_id=self.provider_id,
            start=start,
            end=end,
            client_name="Test Client",
            client_email="test@example.com"
        )
        
        # 3. Verify
        self.assertEqual(booking.status, BookingStatus.PENDING)
        self.assertEqual(booking.payment_status, PaymentStatus.PENDING)
        self.mock_booking_repo.save.assert_called_once()

    def test_create_booking_success_free(self):
        """Test successful booking creation when slot is available for FREE service"""
        # 1. Setup mocks
        self.mock_availability_service.is_slot_available.return_value = True
        self.mock_service.price = 0
        
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
        end = start + timedelta(minutes=60)
        
        # 2. Execute
        booking = self.service.create_booking(
            tenant_id=self.tenant_id,
            service_id=self.service_id,
            provider_id=self.provider_id,
            start=start,
            end=end,
            client_name="Test Client",
            client_email="test@example.com"
        )
        
        # 3. Verify
        self.assertEqual(booking.status, BookingStatus.CONFIRMED)
        self.assertEqual(booking.payment_status, PaymentStatus.NONE)
        self.mock_booking_repo.save.assert_called_once()

    def test_create_booking_slot_unavailable(self):
        """Test booking failure when slot is NOT available"""
        # 1. Setup mocks
        self.mock_availability_service.is_slot_available.return_value = False
        
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        end = start + timedelta(minutes=60)
        
        # 2. Execute & Verify Exception
        with self.assertRaises(SlotNotAvailableError):
            self.service.create_booking(
                tenant_id=self.tenant_id,
                service_id=self.service_id,
                provider_id=self.provider_id,
                start=start,
                end=end,
                client_name="Test Client",
                client_email="test@example.com"
            )
        
        self.mock_booking_repo.save.assert_not_called()

if __name__ == "__main__":
    unittest.main()
