import unittest
from datetime import datetime, time
from unittest.mock import Mock, MagicMock
from shared.domain.entities import (
    TenantId, Service, Provider, ProviderAvailability, TimeRange, 
    TimeSlot, Booking
)
from availability.service import AvailabilityService

class TestAvailabilityService(unittest.TestCase):
    def setUp(self):
        self.mock_availability_repo = Mock()
        self.mock_booking_repo = Mock()
        self.mock_service_repo = Mock()
        self.mock_provider_repo = Mock()
        
        self.service = AvailabilityService(
            self.mock_availability_repo,
            self.mock_booking_repo,
            self.mock_service_repo,
            self.mock_provider_repo,
            slot_interval_minutes=60 # 1 hour slots for easier testing
        )
        
        self.tenant_id = TenantId("tenant-123")
        self.service_id = "svc-1"
        self.provider_id = "pro-1"

        # Setup default entities
        self.mock_service_obj = Service(
            service_id=self.service_id,
            tenant_id=self.tenant_id,
            name="Test Service",
            description="",
            category="cat-1",
            duration_minutes=60,
            price=100,
            active=True
        )
        self.mock_service_repo.get_by_id.return_value = self.mock_service_obj

        self.mock_provider_obj = Provider(
            provider_id=self.provider_id,
            tenant_id=self.tenant_id,
            name="Test Provider",
            bio="",
            service_ids=[self.service_id],
            timezone="UTC",
            active=True
        )
        self.mock_provider_repo.get_by_id.return_value = self.mock_provider_obj
        
        # Default: No bookings
        self.mock_booking_repo.list_by_provider.return_value = []

    def test_standard_availability(self):
        """Test standard weekly availability generation"""
        # Mon 9-17
        availability = ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week="MON",
            time_ranges=[TimeRange("09:00", "12:00")]
        )
        self.mock_availability_repo.get_provider_availability.return_value = [availability]
        self.mock_availability_repo.get_provider_exceptions.return_value = [] # No exceptions

        # Test date: 2026-01-19 (Monday)
        from_date = datetime(2026, 1, 19, 0, 0)
        to_date = datetime(2026, 1, 19, 23, 59)

        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        # Expect 09:00, 10:00, 11:00 (3 slots)
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0].start.hour, 9)
        self.assertEqual(slots[-1].start.hour, 11)

    def test_full_day_exception(self):
        """Test exception causing full day off (empty ranges)"""
        # Standard: Work Mon 9-12
        availability = ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week="MON",
            time_ranges=[TimeRange("09:00", "12:00")]
        )
        self.mock_availability_repo.get_provider_availability.return_value = [availability]
        
        # Exception: 2026-01-19 is OFF
        from shared.domain.entities import ExceptionRule
        self.mock_availability_repo.get_provider_exceptions.return_value = [
            ExceptionRule(date='2026-01-19', time_ranges=[])
        ]

        from_date = datetime(2026, 1, 19, 0, 0)
        to_date = datetime(2026, 1, 19, 23, 59)

        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        # Expect 0 slots (Blocked)
        self.assertEqual(len(slots), 0)

    def test_partial_day_exception(self):
        """Test exception overriding standard hours with partial hours"""
        # Standard: Work Mon 09-17
        availability = ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week="MON",
            time_ranges=[TimeRange("09:00", "17:00")]
        )
        self.mock_availability_repo.get_provider_availability.return_value = [availability]
        
        # Exception: 2026-01-19 Only work 10:00-12:00
        from shared.domain.entities import ExceptionRule
        self.mock_availability_repo.get_provider_exceptions.return_value = [
            ExceptionRule(date='2026-01-19', time_ranges=[TimeRange(start_time='10:00', end_time='12:00')])
        ]

        from_date = datetime(2026, 1, 19, 0, 0)
        to_date = datetime(2026, 1, 19, 23, 59)

        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        # Standard would be 8 slots (9-17)
        # Exception override should match exception ranges: 10:00, 11:00 (2 slots)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].start.hour, 10)
        self.assertEqual(slots[1].start.hour, 11)

if __name__ == '__main__':
    unittest.main()
