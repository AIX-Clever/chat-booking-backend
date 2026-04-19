import unittest
from datetime import datetime, time
from unittest.mock import Mock, MagicMock
from shared.domain.entities import (
    TenantId,
    Service,
    Provider,
    ProviderAvailability,
    TimeRange,
    TimeSlot,
    Booking,
)
from shared.application.availability_service import AvailabilityService


class TestAvailabilityService(unittest.TestCase):
    def setUp(self):
        self.mock_availability_repo = Mock()
        self.mock_booking_repo = Mock()
        self.mock_service_repo = Mock()
        self.mock_provider_repo = Mock()

        self.mock_provider_integration_repo = Mock()

        self.service = AvailabilityService(
            self.mock_availability_repo,
            self.mock_booking_repo,
            self.mock_service_repo,
            self.mock_provider_repo,
            self.mock_provider_integration_repo,
            slot_interval_minutes=60,  # 1 hour slots for easier testing
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
            active=True,
        )
        self.mock_service_repo.get_by_id.return_value = self.mock_service_obj

        self.mock_provider_obj = Provider(
            provider_id=self.provider_id,
            tenant_id=self.tenant_id,
            name="Test Provider",
            bio="",
            service_ids=[self.service_id],
            timezone="UTC",
            active=True,
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
            time_ranges=[TimeRange("09:00", "12:00")],
        )
        self.mock_availability_repo.get_provider_availability.return_value = [
            availability
        ]
        self.mock_availability_repo.get_provider_exceptions.return_value = (
            []
        )  # No exceptions

        # Test date: 2026-03-23 (Monday)
        from_date = datetime(2026, 3, 23, 0, 0)
        to_date = datetime(2026, 3, 23, 23, 59)

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
            time_ranges=[TimeRange("09:00", "12:00")],
        )
        self.mock_availability_repo.get_provider_availability.return_value = [
            availability
        ]

        # Exception: 2026-03-23 is OFF
        from shared.domain.entities import ExceptionRule

        self.mock_availability_repo.get_provider_exceptions.return_value = [
            ExceptionRule(date="2026-03-23", time_ranges=[])
        ]

        from_date = datetime(2026, 3, 23, 0, 0)
        to_date = datetime(2026, 3, 23, 23, 59)

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
            time_ranges=[TimeRange("09:00", "17:00")],
        )
        self.mock_availability_repo.get_provider_availability.return_value = [
            availability
        ]

        # Exception: 2026-03-23 Only work 10:00-12:00
        from shared.domain.entities import ExceptionRule

        self.mock_availability_repo.get_provider_exceptions.return_value = [
            ExceptionRule(
                date="2026-03-23",
                time_ranges=[TimeRange(start_time="10:00", end_time="12:00")],
            )
        ]

        from_date = datetime(2026, 3, 23, 0, 0)
        to_date = datetime(2026, 3, 23, 23, 59)

        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        # Standard would be 8 slots (9-17)
        # Exception override should match exception ranges: 10:00, 11:00 (2 slots)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].start.hour, 10)
        self.assertEqual(slots[1].start.hour, 11)

    def test_timezone_shift(self):
        """Test timezone-aware slot generation"""
        # Provider in Chile (UTC-3 in Jan)
        self.mock_provider_obj.timezone = "America/Santiago"

        # Availability: 09:00 - 10:00 Local
        availability = ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week="MON",
            time_ranges=[TimeRange("09:00", "10:00")],
        )
        self.mock_availability_repo.get_provider_availability.return_value = [
            availability
        ]
        self.mock_availability_repo.get_provider_exceptions.return_value = []

        # Test date: 2026-03-23 (Monday)
        from_date = datetime(2026, 3, 23, 0, 0)
        to_date = datetime(2026, 3, 23, 23, 59)

        # Note: timezone_str arg is not exposed in public get_available_slots,
        # it comes from provider entity inside the service.
        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        # 09:00 Santiago = 12:00 UTC
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].start.hour, 12)  # UTC
        self.assertEqual(slots[0].end.hour, 13)  # UTC


    def test_duplicate_time_ranges(self):
        """Test that overlapping/duplicate time ranges do not produce duplicate slots"""
        # Overlapping ranges: 09:00-11:00 and 10:00-12:00
        # Should produce: 09:00, 10:00, 11:00 (assuming 60m slots)
        # Without fix, might produce: 09:00, 10:00, 10:00, 11:00
        availability = ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week="MON",
            time_ranges=[
                TimeRange("09:00", "11:00"),
                TimeRange("10:00", "12:00"),
            ],
        )
        self.mock_availability_repo.get_provider_availability.return_value = [
            availability
        ]
        self.mock_availability_repo.get_provider_exceptions.return_value = []

        from_date = datetime(2026, 3, 23, 0, 0)
        to_date = datetime(2026, 3, 23, 23, 59)

        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        # Check for uniqueness
        start_times = [s.start.isoformat() for s in slots]
        self.assertEqual(len(start_times), len(set(start_times)), "Found duplicate slots")
        
        # Should be 3 slots: 09:00, 10:00, 11:00
        self.assertEqual(len(slots), 3)

    def test_breaks_excluded_from_slots(self):
        """Test that break periods are not offered as available slots"""
        # Mon 09:00-17:00 with lunch break 12:00-13:00
        from shared.domain.entities import ProviderAvailability, TimeRange
        availability = ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week="MON",
            time_ranges=[TimeRange("09:00", "17:00")],
            breaks=[TimeRange("12:00", "13:00")],
        )
        self.mock_availability_repo.get_provider_availability.return_value = [availability]
        self.mock_availability_repo.get_provider_exceptions.return_value = []

        # 2026-03-23 is a Monday
        from_date = datetime(2026, 3, 23, 0, 0)
        to_date = datetime(2026, 3, 23, 23, 59)

        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        slot_hours = [s.start.hour for s in slots]
        # 12:00 UTC should NOT appear (break)
        self.assertNotIn(12, slot_hours, "Break time slot at 12:00 should not be available")
        # 11:00 and 13:00 UTC should appear (adjacent to break)
        self.assertIn(11, slot_hours, "Slot at 11:00 should be available")
        self.assertIn(13, slot_hours, "Slot at 13:00 should be available")
        # Total: 9,10,11 + 13,14,15,16 = 7 slots (not 8)
        self.assertEqual(len(slots), 7, f"Expected 7 slots (break excluded), got {len(slots)}: {slot_hours}")

    def test_breaks_with_timezone(self):
        """Test that break exclusion respects provider timezone"""
        # Provider in Santiago (UTC-3 in March)
        self.mock_provider_obj.timezone = "America/Santiago"

        # Mon 09:00-12:00 local with break 10:00-11:00 local
        availability = ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week="MON",
            time_ranges=[TimeRange("09:00", "12:00")],
            breaks=[TimeRange("10:00", "11:00")],
        )
        self.mock_availability_repo.get_provider_availability.return_value = [availability]
        self.mock_availability_repo.get_provider_exceptions.return_value = []

        from_date = datetime(2026, 3, 23, 0, 0)
        to_date = datetime(2026, 3, 23, 23, 59)

        slots = self.service.get_available_slots(
            self.tenant_id, self.service_id, self.provider_id, from_date, to_date
        )

        # 09:00 Santiago = 12:00 UTC  → available
        # 10:00 Santiago = 13:00 UTC  → break, should NOT appear
        # 11:00 Santiago = 14:00 UTC  → available
        slot_utc_hours = [s.start.hour for s in slots]
        self.assertNotIn(13, slot_utc_hours, "Break at local 10:00 (UTC 13:00) should not be available")
        self.assertIn(12, slot_utc_hours, "Slot at local 09:00 (UTC 12:00) should be available")
        self.assertIn(14, slot_utc_hours, "Slot at local 11:00 (UTC 14:00) should be available")
        self.assertEqual(len(slots), 2, f"Expected 2 slots (break excluded), got {len(slots)}: {slot_utc_hours}")


if __name__ == "__main__":
    unittest.main()
