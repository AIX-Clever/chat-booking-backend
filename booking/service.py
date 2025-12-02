"""
Booking Application Services (Application Layer)

Use cases for booking management with overbooking prevention
"""

from datetime import datetime
from typing import Optional
from shared.domain.entities import (
    TenantId,
    Booking,
    BookingStatus,
    PaymentStatus,
    TimeSlot
)
from shared.domain.repositories import (
    IBookingRepository,
    IServiceRepository,
    IProviderRepository,
    ITenantRepository,
    IConversationRepository
)
from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError,
    TenantNotActiveError,
    ServiceNotAvailableError,
    ProviderNotAvailableError,
    SlotNotAvailableError,
    ConflictError
)
from shared.utils import generate_id


class BookingService:
    """
    Service for creating and managing bookings
    
    Responsibilities:
    - Create bookings with slot validation
    - Check slot availability (prevent overbooking)
    - Confirm bookings
    - Cancel bookings
    - Get booking details
    
    SOLID:
    - SRP: Only handles booking operations
    - OCP: Extensible for new booking types
    - LSP: Uses repository interfaces
    - ISP: Depends only on needed repositories
    - DIP: Depends on abstractions (interfaces)
    """
    
    def __init__(
        self,
        booking_repo: IBookingRepository,
        service_repo: IServiceRepository,
        provider_repo: IProviderRepository,
        tenant_repo: ITenantRepository
    ):
        self._booking_repo = booking_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._tenant_repo = tenant_repo
    
    def create_booking(
        self,
        tenant_id: TenantId,
        service_id: str,
        provider_id: str,
        start: datetime,
        end: datetime,
        client_name: str,
        client_email: str,
        client_phone: Optional[str] = None,
        notes: Optional[str] = None,
        conversation_id: Optional[str] = None
    ) -> Booking:
        """
        Create a new booking with validation
        
        Business rules:
        1. Tenant must be active and able to create bookings
        2. Service must exist and be available
        3. Provider must exist and can provide the service
        4. Time slot must not overlap with existing active bookings
        5. Booking duration must match service duration
        
        Args:
            tenant_id: Tenant identifier
            service_id: Service identifier
            provider_id: Provider identifier
            start: Booking start datetime
            end: Booking end datetime
            client_name: Client full name
            client_email: Client email
            client_phone: Client phone (optional)
            notes: Additional notes (optional)
            conversation_id: Associated conversation ID (optional)
        
        Returns:
            Created Booking entity
        
        Raises:
            EntityNotFoundError: If tenant/service/provider not found
            TenantNotActiveError: If tenant cannot create bookings
            ServiceNotAvailableError: If service is not available
            ProviderNotAvailableError: If provider cannot provide service
            SlotNotAvailableError: If time slot conflicts with existing booking
            ValidationError: If input validation fails
        """
        # Validate tenant
        tenant = self._tenant_repo.get_by_id(tenant_id)
        if not tenant:
            raise EntityNotFoundError(f"Tenant not found: {tenant_id.value}")
        
        if not tenant.can_create_booking():
            raise TenantNotActiveError(
                f"Tenant {tenant_id.value} cannot create bookings. "
                f"Status: {tenant.status.value}"
            )
        
        # Validate service
        service = self._service_repo.get_by_id(tenant_id, service_id)
        if not service:
            raise EntityNotFoundError(f"Service not found: {service_id}")
        
        if not service.is_available():
            raise ServiceNotAvailableError(f"Service {service_id} is not available")
        
        # Validate provider
        provider = self._provider_repo.get_by_id(tenant_id, provider_id)
        if not provider:
            raise EntityNotFoundError(f"Provider not found: {provider_id}")
        
        if not provider.can_provide_service(service_id):
            raise ProviderNotAvailableError(
                f"Provider {provider_id} cannot provide service {service_id}"
            )
        
        # Validate booking duration matches service duration
        booking_duration = int((end - start).total_seconds() / 60)
        if booking_duration != service.duration_minutes:
            raise ValidationError(
                f"Booking duration ({booking_duration} min) must match "
                f"service duration ({service.duration_minutes} min)"
            )
        
        # Validate time slot is not in the past
        if start < datetime.utcnow():
            raise ValidationError("Cannot create booking in the past")
        
        # Check slot availability (prevent overbooking)
        if not self._is_slot_available(tenant_id, provider_id, start, end):
            raise SlotNotAvailableError(
                f"Time slot {start.isoformat()} - {end.isoformat()} is not available"
            )
        
        # Create booking entity
        booking_id = generate_id('bkg')
        booking = Booking(
            booking_id=booking_id,
            tenant_id=tenant_id,
            service_id=service_id,
            provider_id=provider_id,
            start=start,
            end=end,
            status=BookingStatus.PENDING,
            client_name=client_name,
            client_email=client_email,
            client_phone=client_phone,
            notes=notes,
            conversation_id=conversation_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            payment_status=PaymentStatus.PENDING,
            total_amount=service.price
        )
        
        # Save with conditional expression to prevent race conditions
        # The repository will use a condition to ensure no overlapping bookings
        try:
            self._booking_repo.save(booking)
        except ConflictError:
            # Another booking was created in the meantime
            raise SlotNotAvailableError(
                f"Time slot {start.isoformat()} - {end.isoformat()} was just booked"
            )
        
        return booking
    
    def _is_slot_available(
        self,
        tenant_id: TenantId,
        provider_id: str,
        start: datetime,
        end: datetime,
        exclude_booking_id: Optional[str] = None
    ) -> bool:
        """
        Check if time slot is available
        
        Args:
            tenant_id: Tenant identifier
            provider_id: Provider identifier
            start: Slot start datetime
            end: Slot end datetime
            exclude_booking_id: Booking ID to exclude from check (for updates)
        
        Returns:
            True if slot is available, False otherwise
        """
        # Get existing bookings for provider in date range
        bookings = self._booking_repo.list_by_provider_and_dates(
            tenant_id,
            provider_id,
            start,
            end
        )
        
        # Check for overlaps with active bookings
        new_slot = TimeSlot(start=start, end=end)
        for booking in bookings:
            # Skip the booking being updated
            if exclude_booking_id and booking.booking_id == exclude_booking_id:
                continue
            
            # Only consider active bookings (not cancelled/completed)
            if booking.is_active():
                if booking.overlaps_with(new_slot):
                    return False
        
        return True
    
    def get_booking(self, tenant_id: TenantId, booking_id: str) -> Booking:
        """
        Get booking by ID
        
        Args:
            tenant_id: Tenant identifier
            booking_id: Booking identifier
        
        Returns:
            Booking entity
        
        Raises:
            EntityNotFoundError: If booking not found
        """
        booking = self._booking_repo.get_by_id(tenant_id, booking_id)
        if not booking:
            raise EntityNotFoundError(f"Booking not found: {booking_id}")
        return booking
    
    def confirm_booking(self, tenant_id: TenantId, booking_id: str) -> Booking:
        """
        Confirm a pending booking
        
        Args:
            tenant_id: Tenant identifier
            booking_id: Booking identifier
        
        Returns:
            Updated Booking entity
        
        Raises:
            EntityNotFoundError: If booking not found
            ValidationError: If booking cannot be confirmed
        """
        booking = self.get_booking(tenant_id, booking_id)
        booking.confirm()
        self._booking_repo.save(booking)
        return booking
    
    def cancel_booking(
        self,
        tenant_id: TenantId,
        booking_id: str,
        reason: Optional[str] = None
    ) -> Booking:
        """
        Cancel a booking
        
        Args:
            tenant_id: Tenant identifier
            booking_id: Booking identifier
            reason: Cancellation reason (optional)
        
        Returns:
            Updated Booking entity
        
        Raises:
            EntityNotFoundError: If booking not found
            ValidationError: If booking cannot be cancelled
        """
        booking = self.get_booking(tenant_id, booking_id)
        booking.cancel()
        
        # Add cancellation reason to notes
        if reason:
            current_notes = booking.notes or ""
            booking.notes = f"{current_notes}\n[CANCELLED] {reason}".strip()
        
        self._booking_repo.save(booking)
        return booking


class BookingQueryService:
    """
    Service for querying bookings
    
    Responsibilities:
    - List bookings with filters
    - Get booking details
    - Check booking status
    
    SOLID:
    - SRP: Only handles booking queries (read-only)
    - OCP: Extensible for new query filters
    - LSP: Uses repository interfaces
    - ISP: Depends only on booking repository
    - DIP: Depends on abstractions
    """
    
    def __init__(
        self,
        booking_repo: IBookingRepository,
        conversation_repo: IConversationRepository
    ):
        self._booking_repo = booking_repo
        self._conversation_repo = conversation_repo
    
    def get_booking(self, tenant_id: TenantId, booking_id: str) -> Booking:
        """Get booking by ID"""
        booking = self._booking_repo.get_by_id(tenant_id, booking_id)
        if not booking:
            raise EntityNotFoundError(f"Booking not found: {booking_id}")
        return booking
    
    def list_by_provider(
        self,
        tenant_id: TenantId,
        provider_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> list[Booking]:
        """
        List bookings for a provider in date range
        
        Args:
            tenant_id: Tenant identifier
            provider_id: Provider identifier
            start_date: Range start
            end_date: Range end
        
        Returns:
            List of bookings
        """
        return self._booking_repo.list_by_provider_and_dates(
            tenant_id,
            provider_id,
            start_date,
            end_date
        )
    
    def list_by_client(
        self,
        tenant_id: TenantId,
        client_email: str
    ) -> list[Booking]:
        """
        List bookings for a client
        
        Args:
            tenant_id: Tenant identifier
            client_email: Client email
        
        Returns:
            List of bookings
        """
        return self._booking_repo.list_by_client(tenant_id, client_email)
    
    def get_booking_by_conversation(
        self,
        tenant_id: TenantId,
        conversation_id: str
    ) -> Optional[Booking]:
        """
        Get booking associated with a conversation
        
        Args:
            tenant_id: Tenant identifier
            conversation_id: Conversation identifier
        
        Returns:
            Booking entity or None
        """
        return self._booking_repo.get_by_conversation(tenant_id, conversation_id)
