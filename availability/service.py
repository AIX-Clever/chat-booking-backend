"""
Slot Calculation Service (Application Layer)

Generates available time slots based on provider availability and existing bookings
"""

from typing import List, Dict
from datetime import datetime, timedelta, time
from shared.domain.entities import TenantId, TimeSlot, ProviderAvailability, Booking
from shared.domain.repositories import (
    IAvailabilityRepository,
    IBookingRepository,
    IServiceRepository,
    IProviderRepository
)
from shared.domain.exceptions import (
    EntityNotFoundError,
    ServiceNotAvailableError,
    ProviderNotAvailableError
)
from shared.utils import Logger


class AvailabilityService:
    """
    Service for calculating available time slots
    Single Responsibility: slot generation logic
    """

    def __init__(
        self,
        availability_repo: IAvailabilityRepository,
        booking_repo: IBookingRepository,
        service_repo: IServiceRepository,
        provider_repo: IProviderRepository,
        slot_interval_minutes: int = 15
    ):
        """
        Dependency Injection
        
        Args:
            slot_interval_minutes: Interval between slot start times (default 15 min)
        """
        self.availability_repo = availability_repo
        self.booking_repo = booking_repo
        self.service_repo = service_repo
        self.provider_repo = provider_repo
        self.slot_interval_minutes = slot_interval_minutes
        self.logger = Logger()

    def get_available_slots(
        self,
        tenant_id: TenantId,
        service_id: str,
        provider_id: str,
        from_date: datetime,
        to_date: datetime
    ) -> List[TimeSlot]:
        """
        Calculate available time slots
        
        Args:
            tenant_id: Tenant identifier
            service_id: Service identifier
            provider_id: Provider identifier
            from_date: Start of date range (inclusive)
            to_date: End of date range (exclusive)
            
        Returns:
            List of available TimeSlot objects
            
        Raises:
            EntityNotFoundError: Service or provider doesn't exist
            ServiceNotAvailableError: Service is not active
            ProviderNotAvailableError: Provider doesn't offer the service
        """
        self.logger.info(
            "Calculating available slots",
            tenant_id=str(tenant_id),
            service_id=service_id,
            provider_id=provider_id,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat()
        )

        # Validate entities exist and are available
        service = self.service_repo.get_by_id(tenant_id, service_id)
        if not service:
            raise EntityNotFoundError("Service", service_id)
        
        if not service.is_available():
            raise ServiceNotAvailableError(service_id)

        provider = self.provider_repo.get_by_id(tenant_id, provider_id)
        if not provider:
            raise EntityNotFoundError("Provider", provider_id)
        
        if not provider.can_provide_service(service_id):
            raise ProviderNotAvailableError(provider_id, service_id)

        # Get provider's weekly availability
        availability_schedule = self.availability_repo.get_provider_availability(
            tenant_id,
            provider_id
        )

        # Build availability map by day of week
        availability_map = {
            avail.day_of_week: avail
            for avail in availability_schedule
        }
        
        # Get provider-level exceptions (now stored separately)
        provider_exceptions = self.availability_repo.get_provider_exceptions(
            tenant_id,
            provider_id
        )

        # Get existing bookings in date range
        existing_bookings = self.booking_repo.list_by_provider(
            tenant_id,
            provider_id,
            from_date,
            to_date
        )

        # Generate candidate slots
        candidate_slots = self._generate_candidate_slots(
            from_date,
            to_date,
            service.duration_minutes,
            availability_map,
            provider_exceptions
        )

        # Filter out occupied slots
        available_slots = self._filter_occupied_slots(
            candidate_slots,
            existing_bookings
        )

        self.logger.info(
            "Slots calculated",
            tenant_id=str(tenant_id),
            candidate_count=len(candidate_slots),
            available_count=len(available_slots)
        )

        return available_slots

    def _generate_candidate_slots(
        self,
        from_date: datetime,
        to_date: datetime,
        duration_minutes: int,
        availability_map: Dict[str, ProviderAvailability],
        exceptions: List[str] = None
    ) -> List[TimeSlot]:
        """
        Generate all possible slots based on provider availability
        
        Args:
            exceptions: Provider-level exception dates (YYYY-MM-DD format)
        
        Returns slots at regular intervals (slot_interval_minutes)
        within provider's working hours
        """
        if exceptions is None:
            exceptions = []
            
        slots = []
        current_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)

        while current_date < to_date:
            day_name = current_date.strftime('%a').upper()  # MON, TUE, etc.
            
            # Check if date is in exceptions list (provider-level)
            date_str = current_date.date().isoformat()
            if date_str in exceptions:
                current_date += timedelta(days=1)
                continue
            
            if day_name in availability_map:
                availability = availability_map[day_name]

                # Generate slots for each time range
                for time_range in availability.time_ranges:
                    slots.extend(
                        self._generate_slots_in_range(
                            current_date,
                            time_range,
                            duration_minutes,
                            availability.breaks
                        )
                    )

            current_date += timedelta(days=1)

        return slots

        return slots

    def _generate_slots_in_range(
        self,
        date: datetime,
        time_range,
        duration_minutes: int,
        breaks: List
    ) -> List[TimeSlot]:
        """
        Generate slots within a specific time range, avoiding breaks
        """
        try:
            from datetime import timezone
            UTC = timezone.utc
        except ImportError:
            import pytz
            UTC = pytz.UTC

        slots = []
        
        # Parse start and end times
        start_parts = time_range.start_time.split(':')
        start_time = time(int(start_parts[0]), int(start_parts[1]))
        
        end_parts = time_range.end_time.split(':')
        end_time = time(int(end_parts[0]), int(end_parts[1]))

        # Create datetime objects
        current_slot_start = datetime.combine(date.date(), start_time)
        range_end = datetime.combine(date.date(), end_time)

        # Apply timezone from date if present to ensure slots are timezone-aware
        if date.tzinfo:
            current_slot_start = current_slot_start.replace(tzinfo=date.tzinfo)
            range_end = range_end.replace(tzinfo=date.tzinfo)
        elif not current_slot_start.tzinfo:
             # If naive, assume UTC for comparison safety (though ideally strictly typed)
             current_slot_start = current_slot_start.replace(tzinfo=UTC)
             range_end = range_end.replace(tzinfo=UTC)

        # Generate slots at regular intervals
        while current_slot_start + timedelta(minutes=duration_minutes) <= range_end:
            slot_end = current_slot_start + timedelta(minutes=duration_minutes)

            # Check if slot is in the past
            # Add a small buffer (e.g. 5 mins) or strict comparison
            if current_slot_start < datetime.now(UTC):
                 current_slot_start += timedelta(minutes=self.slot_interval_minutes)
                 continue

            # Check if slot overlaps with any break
            overlaps_break = False
            for break_range in breaks:
                break_start_parts = break_range.start_time.split(':')
                break_start = time(int(break_start_parts[0]), int(break_start_parts[1]))
                break_start_dt = datetime.combine(date.date(), break_start)
                
                break_end_parts = break_range.end_time.split(':')
                break_end = time(int(break_end_parts[0]), int(break_end_parts[1]))
                break_end_dt = datetime.combine(date.date(), break_end)

                # Ensure break datetimes are also aware if needed
                if current_slot_start.tzinfo:
                    break_start_dt = break_start_dt.replace(tzinfo=current_slot_start.tzinfo)
                    break_end_dt = break_end_dt.replace(tzinfo=current_slot_start.tzinfo)

                # Check overlap
                if not (slot_end <= break_start_dt or current_slot_start >= break_end_dt):
                    overlaps_break = True
                    break

            if not overlaps_break:
                slots.append(TimeSlot(
                    provider_id="",  # Will be set later
                    service_id="",   # Will be set later
                    start=current_slot_start,
                    end=slot_end,
                    is_available=True
                ))

            # Move to next slot
            current_slot_start += timedelta(minutes=self.slot_interval_minutes)

        return slots

    def _filter_occupied_slots(
        self,
        candidate_slots: List[TimeSlot],
        existing_bookings: List[Booking]
    ) -> List[TimeSlot]:
        """
        Filter out slots that overlap with existing bookings
        
        Only includes active bookings (PENDING or CONFIRMED)
        """
        available_slots = []

        for slot in candidate_slots:
            is_available = True

            for booking in existing_bookings:
                # Only check active bookings
                if not booking.is_active():
                    continue

                # Check if slot overlaps with booking
                if not (slot.end <= booking.start_time or slot.start >= booking.end_time):
                    is_available = False
                    break

            if is_available:
                available_slots.append(slot)

        return available_slots


class AvailabilityManagementService:
    """
    Service for managing provider availability schedules (admin)
    Open/Closed Principle: separated from read-only availability service
    """

    def __init__(self, availability_repo: IAvailabilityRepository):
        self.availability_repo = availability_repo
        self.logger = Logger()

    def set_provider_availability(
        self,
        tenant_id: TenantId,
        provider_id: str,
        day_of_week: str,
        time_ranges: List[Dict[str, str]],
        breaks: List[Dict[str, str]] = None,
        exceptions: List[str] = None
    ) -> ProviderAvailability:
        """
        Set availability schedule for a specific day
        
        Args:
            tenant_id: Tenant identifier
            provider_id: Provider identifier
            day_of_week: Day name (MON, TUE, WED, THU, FRI, SAT, SUN)
            time_ranges: List of {startTime, endTime} dicts
            breaks: Optional list of break periods
            exceptions: Optional list of exception dates (ISO format)
        """
        self.logger.info(
            "Setting provider availability",
            tenant_id=str(tenant_id),
            provider_id=provider_id,
            day_of_week=day_of_week,
            exceptions_count=len(exceptions) if exceptions else 0
        )

        from shared.domain.entities import TimeRange

        # Convert to TimeRange objects
        time_range_objects = [
            TimeRange(tr['startTime'], tr['endTime'])
            for tr in time_ranges
        ]

        break_objects = []
        if breaks:
            break_objects = [
                TimeRange(br['startTime'], br['endTime'])
                for br in breaks
            ]

        # Create entity
        availability = ProviderAvailability(
            tenant_id=tenant_id,
            provider_id=provider_id,
            day_of_week=day_of_week.upper(),
            time_ranges=time_range_objects,
            breaks=break_objects,
            exceptions=exceptions or []
        )

        # Persist
        self.availability_repo.save_availability(availability)

        self.logger.info(
            "Provider availability set",
            tenant_id=str(tenant_id),
            provider_id=provider_id,
            day_of_week=day_of_week
        )

        return availability
