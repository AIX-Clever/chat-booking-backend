import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from booking.service import BookingService
from shared.domain.entities import TenantId
from shared.domain.exceptions import ValidationError

class TestBookingServiceValidation(unittest.TestCase):
    def setUp(self):
        self.service = BookingService(
            booking_repo=MagicMock(),
            service_repo=MagicMock(),
            provider_repo=MagicMock(),
            tenant_repo=MagicMock(),
            room_repo=MagicMock(),
            provider_integration_repo=MagicMock(),
            email_service=MagicMock(),
            metrics_service=MagicMock()
        )
        self.tenant_id = TenantId("test-tenant")

    def test_create_booking_in_past_fails(self):
        # Setup
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        # Mock repositories to return valid objects so we hit the date check
        service_mock = MagicMock(name="Service", price=100)
        service_mock.duration_minutes = 30
        self.service._service_repo.get_by_id.return_value = service_mock
        
        self.service._provider_repo.get_by_id.return_value = MagicMock(
            name="Provider",
            can_provide_service=MagicMock(return_value=True)
        )
        self.service._tenant_repo.get_by_id.return_value = MagicMock()
        
        # Mock business hours check to pass (we want to test the date check specifically)
        self.service._check_business_hours = MagicMock(return_value=True)

        # Execute
        # Execute & Verify
        with self.assertRaises(ValidationError) as cm:
            self.service.create_booking(
                tenant_id=self.tenant_id,
                service_id="svc-1",
                provider_id="prov-1",
                start=past_time,
                end=past_time + timedelta(minutes=30),
                client_name="Test User",
                client_email="test@example.com"
            )
        
        self.assertIn("No se pueden crear reservas en el pasado", str(cm.exception))

if __name__ == '__main__':
    unittest.main()
