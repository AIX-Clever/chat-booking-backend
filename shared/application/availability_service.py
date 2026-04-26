"""
Availability Application Services (Application Layer)
Calculates available slots and manages provider availability rules
"""

from datetime import datetime, date, timedelta, time
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback for Python < 3.9
    from backports.zoneinfo import ZoneInfo
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc
from typing import List, Optional, Dict
from shared.domain.entities import (
    TenantId,
    ProviderAvailability,
    TimeRange,
    ExceptionRule,
    TimeSlot,
    Provider,
)
from shared.domain.repositories import (
    IAvailabilityRepository,
    IBookingRepository,
    IServiceRepository,
    IProviderRepository,
    IProviderIntegrationRepository,
)
from shared.infrastructure.google_auth_service import GoogleAuthService
from shared.infrastructure.microsoft_auth_service import MicrosoftAuthService
import os


class AvailabilityService:
    def __init__(
        self,
        availability_repo: IAvailabilityRepository,
        booking_repo: IBookingRepository,
        service_repo: IServiceRepository,
        provider_repo: Optional[IProviderRepository] = None,
        provider_integration_repo: Optional[IProviderIntegrationRepository] = None,
        slot_interval_minutes: int = 15,
    ):
        self._availability_repo = availability_repo
        self._booking_repo = booking_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._provider_integration_repo = provider_integration_repo
        self._slot_interval_minutes = slot_interval_minutes

        # Centralized Auth Services for external calendars
        self.google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
        self.google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        self.google_auth_service = (
            GoogleAuthService(self.google_client_id, self.google_client_secret, "")
            if self.google_client_id
            else None
        )

        self.microsoft_client_id = os.environ.get("MICROSOFT_CLIENT_ID")
        self.microsoft_client_secret = os.environ.get("MICROSOFT_CLIENT_SECRET")
        self.microsoft_auth_service = (
            MicrosoftAuthService(self.microsoft_client_id, self.microsoft_client_secret, "")
            if self.microsoft_client_id
            else None
        )

    def get_available_slots(
        self,
        tenant_id: TenantId,
        service_id: str,
        provider_id: str,
        from_date: datetime,
        to_date: datetime,
    ) -> List[TimeSlot]:
        """
        Main logic for calculating available slots for a provider and service.
        Considers:
        1. Provider working hours (schedule)
        2. Existing bookings (local)
        3. Exceptions (e.g. holidays, breaks)
        4. External calendars (Google/Microsoft)
        """
        # Validate service
        service = self._service_repo.get_by_id(tenant_id, service_id)
        if not service:
            raise EntityNotFoundError("Service", service_id)

        # Validate provider
        provider = None
        if self._provider_repo:
            provider = self._provider_repo.get_by_id(tenant_id, provider_id)
            if not provider:
                raise EntityNotFoundError("Provider", provider_id)

        # 1. Get Base Availability (Working Hours)
        availability_rules = self._availability_repo.get_provider_availability(tenant_id, provider_id)
        
        # 2. Get Exceptions
        exceptions_data = self._availability_repo.get_provider_exceptions(tenant_id, provider_id)
        
        # Convert dicts from repo to ExceptionRule entities if they are dicts
        exceptions = []
        for ex in exceptions_data:
            if isinstance(ex, dict):
                # Map dict to ExceptionRule entity
                time_ranges = [
                    TimeRange(tr.get("startTime") or tr.get("start_time"), tr.get("endTime") or tr.get("end_time"))
                    for tr in ex.get("timeRanges", [])
                ]
                exceptions.append(ExceptionRule(date=ex.get("date"), time_ranges=time_ranges))
            else:
                exceptions.append(ex)
        
        # 3. Get Existing Bookings
        bookings = self._booking_repo.list_by_provider(tenant_id, provider_id, from_date, to_date)
        
        # 4. Get External Calendar Busy Slots (if integrated)
        external_busy_slots = []
        if self._provider_integration_repo:
            external_busy_slots = self._get_external_busy_slots(tenant_id, provider_id, from_date, to_date)

        # 5. Calculation Logic
        provider_tz = provider.timezone if provider else "UTC"
        available_slots = []
        current_date = from_date.date()
        end_date = to_date.date()

        while current_date <= end_date:
            day_slots = self._calculate_day_slots(
                tenant_id,
                current_date,
                provider_id,
                service,
                availability_rules,
                exceptions,
                bookings,
                external_busy_slots,
                provider_tz,
            )
            available_slots.extend(day_slots)
            current_date += timedelta(days=1)

        # Deduplicate slots by start time (in case of overlapping ranges)
        unique_slots = {}
        for slot in available_slots:
            slot_key = slot.start.isoformat()
            if slot_key not in unique_slots:
                unique_slots[slot_key] = slot
        
        return sorted(unique_slots.values(), key=lambda x: x.start)

    def is_slot_available(
        self,
        tenant_id: TenantId,
        service_id: str,
        provider_id: str,
        start: datetime,
        end: datetime,
    ) -> bool:
        """
        Validates if a specific time slot is available.
        Useful for final booking creation checks.
        """
        # We check the full day of the requested slot to ensure we catch all constraints
        # It's more thorough than checking just one slot.
        day_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        available_slots = self.get_available_slots(tenant_id, service_id, provider_id, day_start, day_end)

        # Check if requested range Exactly matches or fits within any available slot
        for slot in available_slots:
            if slot.is_available and slot.start == start and slot.end == end:
                return True
        return False

    def _calculate_day_slots(
        self,
        tenant_id: TenantId,
        day: date,
        provider_id: str,
        service,
        availability_rules,
        exceptions: List[ExceptionRule],
        bookings,
        external_busy_slots,
        timezone_str: str = "UTC",
    ) -> List[TimeSlot]:
        weekday = day.strftime("%a").upper()  # MON, TUE...
        day_rules = [r for r in availability_rules if r.day_of_week == weekday]

        # Get exceptions for this specific day
        day_str = day.isoformat()
        day_exceptions = [ex for ex in exceptions if ex.date == day_str]

        if not day_rules and not day_exceptions:
            return []

        # If there's an exception with NO time ranges, it's a full day off
        for ex in day_exceptions:
            if not ex.time_ranges:
                return []

        slots = []
        duration = timedelta(minutes=service.duration_minutes)
        tz = ZoneInfo(timezone_str)

        # Rules to use: If there's a day exception with ranges, it OVERRIDES the standard rules
        effective_ranges = []
        if day_exceptions:
            for ex in day_exceptions:
                effective_ranges.extend(ex.time_ranges)
        else:
            for rule in day_rules:
                effective_ranges.extend(rule.time_ranges)

        if not effective_ranges:
            return []

        # Collect breaks for the day from standard rules (exceptions don't carry breaks)
        day_breaks = []
        for rule in day_rules:
            day_breaks.extend(rule.breaks)

        for time_range in effective_ranges:
            start_h, start_m = map(int, time_range.start_time.split(":"))
            end_h, end_m = map(int, time_range.end_time.split(":"))

            # Create local times first
            current_local = datetime.combine(day, time(start_h, start_m)).replace(tzinfo=tz)
            end_local_limit = datetime.combine(day, time(end_h, end_m)).replace(tzinfo=tz)

            while current_local + duration <= end_local_limit:
                slot_end_local = current_local + duration

                # Convert to UTC for external checks (bookings, external calendars)
                current_utc = current_local.astimezone(UTC)
                slot_end_utc = slot_end_local.astimezone(UTC)

                # Skip slots that fall within a break period
                in_break = self._is_in_break(current_utc, slot_end_utc, day_breaks, day, tz)

                if not in_break and not self._is_busy(current_utc, slot_end_utc, bookings, external_busy_slots):
                    slots.append(TimeSlot(
                        provider_id=provider_id,
                        service_id=service.service_id,
                        start=current_utc,
                        end=slot_end_utc,
                        is_available=True
                    ))

                # Use provided interval if set, otherwise default to service duration
                interval = timedelta(minutes=self._slot_interval_minutes) if self._slot_interval_minutes else duration
                current_local += interval

        return slots

    def _is_in_break(self, start_utc: datetime, end_utc: datetime, breaks: list, day: date, tz) -> bool:
        """
        Check if a UTC slot overlaps with any break period.
        Breaks are expressed in provider local time (HH:MM), so we convert them to UTC for comparison.
        """
        for br in breaks:
            try:
                br_start_h, br_start_m = map(int, br.start_time.split(":"))
                br_end_h, br_end_m = map(int, br.end_time.split(":"))
                br_start_utc = datetime.combine(day, time(br_start_h, br_start_m)).replace(tzinfo=tz).astimezone(UTC)
                br_end_utc = datetime.combine(day, time(br_end_h, br_end_m)).replace(tzinfo=tz).astimezone(UTC)
                # Overlap: slot starts before break ends AND slot ends after break starts
                if not (end_utc <= br_start_utc or start_utc >= br_end_utc):
                    return True
            except (ValueError, AttributeError):
                continue
        return False

    def _is_busy(self, start, end, bookings, external_busy_slots):
        # 1. Check Bookings
        for b in bookings:
            if b.is_active() and not (end <= b.start_time or start >= b.end_time):
                return True
        # 2. Check External Calendars
        for e_busy in external_busy_slots:
            if not (end <= e_busy["start"] or start >= e_busy["end"]):
                return True
        return False

    def _get_external_busy_slots(self, tenant_id, provider_id, start, end):
        busy_slots = []
        # Google
        if self.google_auth_service:
            try:
                creds = self._provider_integration_repo.get_google_creds(tenant_id, provider_id)
                if creds:
                    token = creds.get("access_token")
                    refresh = creds.get("refresh_token")
                    g_service = self.google_auth_service.get_calendar_service(token, refresh)
                    body = {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": "primary"}]}
                    resp = g_service.freebusy().query(body=body).execute()
                    for cal in resp.get("calendars", {}).values():
                        for b in cal.get("busy", []):
                            busy_slots.append({"start": datetime.fromisoformat(b["start"].replace("Z", "+00:00")), "end": datetime.fromisoformat(b["end"].replace("Z", "+00:00"))})
            except Exception as e: print(f"Google freebusy error: {e}")
            
        # Microsoft
        if self.microsoft_auth_service:
            try:
                creds = self._provider_integration_repo.get_microsoft_creds(tenant_id, provider_id)
                if creds:
                    ms_busy = self.microsoft_auth_service.get_free_busy(creds.get("access_token"), start.isoformat(), end.isoformat())
                    for b in ms_busy:
                        busy_slots.append({"start": datetime.fromisoformat(b["start"]), "end": datetime.fromisoformat(b["end"])})
            except Exception as e: print(f"Microsoft freebusy error: {e}")
            
        return busy_slots


class AvailabilityManagementService:
    def __init__(self, availability_repo: IAvailabilityRepository):
        self._availability_repo = availability_repo

    def set_provider_availability(self, tenant_id, provider_id, day_of_week, time_ranges, breaks, exceptions=None):
        time_ranges_obj = [TimeRange(tr["startTime"], tr["endTime"]) for tr in time_ranges]
        breaks_obj = [TimeRange(br["startTime"], br["endTime"]) for br in breaks]
        
        availability = ProviderAvailability(
            tenant_id=tenant_id,
            provider_id=provider_id,
            day_of_week=day_of_week,
            time_ranges=time_ranges_obj,
            breaks=breaks_obj,
            exceptions=exceptions or []
        )
        self._availability_repo.save_availability(availability)
        return availability

    def get_provider_exceptions(self, tenant_id, provider_id):
        return self._availability_repo.get_provider_exceptions(tenant_id, provider_id)

    def set_provider_exceptions(self, tenant_id, provider_id, exceptions: list):
        self._availability_repo.save_provider_exceptions(tenant_id, provider_id, exceptions)
        return exceptions
