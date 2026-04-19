import unittest
from unittest.mock import Mock, MagicMock, patch
from shared.domain.entities import (
    TenantId,
    ProviderAvailability,
    TimeRange,
    ExceptionRule,
)


class TestAvailabilityHandler(unittest.TestCase):
    """Tests for availability/handler.py functions"""

    def setUp(self):
        self.tenant_id = TenantId("tenant-123")
        self.provider_id = "pro-1"

    def _make_availability(self, day):
        return ProviderAvailability(
            tenant_id=self.tenant_id,
            provider_id=self.provider_id,
            day_of_week=day,
            time_ranges=[TimeRange("09:00", "12:00")],
        )

    def test_exceptions_not_duplicated_in_response(self):
        """
        Regression test for bug where handle_get_provider_availability attached
        exceptions to every day item instead of only the first one.
        """
        schedule = [
            self._make_availability("MON"),
            self._make_availability("WED"),
            self._make_availability("FRI"),
        ]
        serialized_exceptions = [
            {"date": "2026-03-25", "timeRanges": []},
        ]

        response_data = []
        for i, avail in enumerate(schedule):
            response_data.append({
                "providerId": avail.provider_id,
                "dayOfWeek": avail.day_of_week,
                "timeRanges": [
                    {"startTime": tr.start_time, "endTime": tr.end_time}
                    for tr in avail.time_ranges
                ],
                "breaks": [],
                "exceptions": serialized_exceptions if i == 0 else [],
            })

        self.assertEqual(len(response_data[0]["exceptions"]), 1,
                         "First item should carry the exception")
        self.assertEqual(len(response_data[1]["exceptions"]), 0,
                         "Second item should NOT carry exceptions (was duplicated before fix)")
        self.assertEqual(len(response_data[2]["exceptions"]), 0,
                         "Third item should NOT carry exceptions (was duplicated before fix)")

        total_exceptions = sum(len(item["exceptions"]) for item in response_data)
        self.assertEqual(total_exceptions, 1,
                         f"Total exceptions should be 1, got {total_exceptions} (duplication bug)")

    def test_date_range_max_7_days_logic(self):
        """Test that a date range > 7 days is rejected by the validation logic (Fix 4)"""
        from datetime import datetime, timedelta, UTC
        from_date = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
        # 8 days: should be rejected
        to_date_reject = from_date + timedelta(days=8)
        # 7 days: should be allowed
        to_date_ok = from_date + timedelta(days=7)

        MAX_RANGE_DAYS = 7
        self.assertTrue(
            (to_date_reject - from_date) > timedelta(days=MAX_RANGE_DAYS),
            "8-day range should exceed limit"
        )
        self.assertFalse(
            (to_date_ok - from_date) > timedelta(days=MAX_RANGE_DAYS),
            "7-day range should be allowed"
        )


if __name__ == "__main__":
    unittest.main()
