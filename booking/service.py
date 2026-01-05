"""
Booking Application Services (Application Layer)

Use cases for booking management with overbooking prevention
"""

from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc
import hashlib
from typing import Optional
from shared.domain.entities import (
    TenantId,
    Booking,
    BookingStatus,
    PaymentStatus,
    TimeSlot,
    CustomerInfo
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
try:
    from shared.limit_service import TenantLimitService
except ImportError:
    TenantLimitService = None

try:
    from shared.infrastructure.notifications import EmailService
except ImportError:
    EmailService = None

try:
    from shared.infrastructure.payment_factory import PaymentGatewayFactory
except ImportError:
    PaymentGatewayFactory = None


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
        tenant_repo: ITenantRepository,
        limit_service: Optional[TenantLimitService] = None,
        email_service: Optional[EmailService] = None
    ):
        self._booking_repo = booking_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._tenant_repo = tenant_repo
        self._limit_service = limit_service
        self._email_service = email_service
    
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
            raise EntityNotFoundError("Tenant", tenant_id.value)
        
        if not tenant.can_create_booking():
            raise TenantNotActiveError(
                f"Tenant {tenant_id.value} cannot create bookings. "
                f"Status: {tenant.status.value}"
            )
        
        # Check Booking Limits
        if self._limit_service:
            if not self._limit_service.check_can_create_booking(tenant_id):
                 raise ValidationError("Has excedido el límite de reservas de tu plan actual.")

        # Validate service
        service = self._service_repo.get_by_id(tenant_id, service_id)
        if not service:
            raise EntityNotFoundError("Service", service_id)
        
        if not service.is_available():
            raise ServiceNotAvailableError(f"Service {service_id} is not available")
        
        # Validate provider
        provider = self._provider_repo.get_by_id(tenant_id, provider_id)
        if not provider:
            raise EntityNotFoundError("Provider", provider_id)
        
        if not provider.can_provide_service(service_id):
            raise ProviderNotAvailableError(provider_id, service_id)
        
        # Validate booking duration matches service duration
        booking_duration = int((end - start).total_seconds() / 60)
        if booking_duration != service.duration_minutes:
            raise ValidationError(
                f"Booking duration ({booking_duration} min) must match "
                f"service duration ({service.duration_minutes} min)"
            )
        
        # Validate time slot is not in the past
        if start < datetime.now(UTC):
            raise ValidationError("Cannot create booking in the past")
        
        # Check slot availability (prevent overbooking)
        if not self._is_slot_available(tenant_id, provider_id, start, end):
            raise SlotNotAvailableError(
                f"Time slot {start.isoformat()} - {end.isoformat()} is not available"
            )
        
        # Create booking entity
        booking_id = generate_id('bkg')
        
        # Determine customer_id (generate hash if provided)
        customer_id = None
        if client_email:
             # Deterministic ID for customer based on email
             customer_id = hashlib.md5(client_email.lower().strip().encode()).hexdigest()

        # Create customer info value object
        customer_info = CustomerInfo(
            customer_id=customer_id,
            name=client_name,
            email=client_email,
            phone=client_phone
        )
        
        booking = Booking(
            booking_id=booking_id,
            tenant_id=tenant_id,
            service_id=service_id,
            provider_id=provider_id,
            customer_info=customer_info,
            start_time=start,
            end_time=end,
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
            conversation_id=conversation_id,
            notes=notes,
            total_amount=service.price
        )

        # Process Payment Intent (Strategy Pattern)
        if PaymentGatewayFactory and service.price > 0:
            try:
                # Resolve gateway based on tenant (could be country-based)
                # For now using default or checking tenant attributes if available
                gateway = PaymentGatewayFactory.get_gateway()
                
                payment_metadata = {
                    "booking_id": booking_id,
                    "tenant_id": tenant_id.value,
                    "service_name": service.name
                }
                
                # Create Intent
                intent_data = gateway.create_payment_intent(
                    amount=service.price,
                    currency=service.currency, # Assuming Service entity has currency
                    metadata=payment_metadata
                )
                
                booking.payment_intent_id = intent_data.get('payment_id')
                booking.payment_client_secret = intent_data.get('client_secret')
                
            except Exception as e:
                # If payment initialization fails, we might want to block booking creation
                # or create it as PENDING_APPROVAL. For now, log and proceed (booking is PENDING payment)
                print(f"Failed to initialize payment: {e}")
        
        # Save with conditional expression to prevent race conditions
        # The repository will use a condition to ensure no overlapping bookings
        try:
            self._booking_repo.save(booking)
        except ConflictError:
            # Another booking was created in the meantime
            raise SlotNotAvailableError(
                f"Time slot {start.isoformat()} - {end.isoformat()} was just booked"
            )
        
        # Send confirmation email
        if self._email_service and client_email:
            try:
                subject = f"Reserva Confirmada: {service.name}"
                body_text = f"Hola {client_name},\n\nTu reserva para {service.name} con {provider.name} ha sido confirmada para el {start.strftime('%Y-%m-%d %H:%M')}.\n\nGracias!"
                body_html = f"""
                <html>
                    <body>
                        <h2>¡Reserva Confirmada!</h2>
                        <p>Hola <strong>{client_name}</strong>,</p>
                        <p>Tu reserva ha sido confirmada con éxito.</p>
                        <ul>
                            <li><strong>Servicio:</strong> {service.name}</li>
                            <li><strong>Profesional:</strong> {provider.name}</li>
                            <li><strong>Fecha:</strong> {start.strftime('%Y-%m-%d')}</li>
                            <li><strong>Hora:</strong> {start.strftime('%H:%M')}</li>
                        </ul>
                        <p>Gracias por confiar en nosotros.</p>
                    </body>
                </html>
                """
                # We use a default sender or configured one. 
                # For now using a placeholder that should be overridden by env var in infrastructure
                # or passed by the handler.
                # Actually, EmailService needs a 'source'. 
                # We can use a noreply address from the tenant domain if valid, or a verified single sender.
                sender = "noreply@antigravity.com" # TODO: Configure in env
                
                self._email_service.send_email(
                    source=sender,
                    to_addresses=[client_email],
                    subject=subject,
                    body_html=body_html,
                    body_text=body_text
                )
            except Exception as e:
                # Log but don't fail the booking
                print(f"Failed to send confirmation email: {e}")

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
        bookings = self._booking_repo.list_by_provider(
            tenant_id,
            provider_id,
            start,
            end
        )
        
        # Check for overlaps with active bookings
        for booking in bookings:
            # Skip the booking being updated
            if exclude_booking_id and booking.booking_id == exclude_booking_id:
                continue
            
            # Only consider active bookings (not cancelled/completed)
            if booking.is_active():
                # Check if time ranges overlap
                if not (end <= booking.start_time or start >= booking.end_time):
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
            raise EntityNotFoundError("Booking", booking_id)
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
        self._booking_repo.update(booking)
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
        
        # TODO: Store cancellation reason in a separate CancellationReason value object
        # or in booking metadata if needed
        
        self._booking_repo.update(booking)
        return booking

    def mark_as_no_show(self, tenant_id: TenantId, booking_id: str) -> Booking:
        """
        Mark a booking as no show
        
        Args:
            tenant_id: Tenant identifier
            booking_id: Booking identifier
        
        Returns:
            Updated Booking entity
        
        Raises:
            EntityNotFoundError: If booking not found
            ValidationError: If booking cannot be marked as no show
        """
        booking = self.get_booking(tenant_id, booking_id)
        booking.mark_as_no_show()
        self._booking_repo.update(booking)
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
            raise EntityNotFoundError("Booking", booking_id)
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
        return self._booking_repo.list_by_provider(
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
        return self._booking_repo.list_by_customer_email(tenant_id, client_email)
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
        # 1. Get conversation to find booking_id
        conversation = self._conversation_repo.get_by_id(tenant_id, conversation_id)
        if not conversation or not conversation.booking_id:
            return None
            
        # 2. Get booking by ID
        return self._booking_repo.get_by_id(tenant_id, conversation.booking_id)
    
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
        bookings = self._booking_repo.list_by_provider(
            tenant_id,
            provider_id,
            start,
            end
        )
        
        # Check for overlaps with active bookings
        for booking in bookings:
            # Skip the booking being updated
            if exclude_booking_id and booking.booking_id == exclude_booking_id:
                continue
            
            # Only consider active bookings (not cancelled/completed)
            if booking.is_active():
                # Check if time ranges overlap
                if not (end <= booking.start_time or start >= booking.end_time):
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
            raise EntityNotFoundError("Booking", booking_id)
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
        self._booking_repo.update(booking)
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
        
        # TODO: Store cancellation reason in a separate CancellationReason value object
        # or in booking metadata if needed
        
        self._booking_repo.update(booking)
        return booking

    def mark_as_no_show(self, tenant_id: TenantId, booking_id: str) -> Booking:
        """
        Mark a booking as no show
        
        Args:
            tenant_id: Tenant identifier
            booking_id: Booking identifier
        
        Returns:
            Updated Booking entity
        
        Raises:
            EntityNotFoundError: If booking not found
            ValidationError: If booking cannot be marked as no show
        """
        booking = self.get_booking(tenant_id, booking_id)
        booking.mark_as_no_show()
        self._booking_repo.update(booking)
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
            raise EntityNotFoundError("Booking", booking_id)
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
        return self._booking_repo.list_by_provider(
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
        return self._booking_repo.list_by_customer_email(tenant_id, client_email)
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
        # 1. Get conversation to find booking_id
        conversation = self._conversation_repo.get_by_id(tenant_id, conversation_id)
        if not conversation or not conversation.booking_id:
            return None
            
        # 2. Get booking by ID
        return self._booking_repo.get_by_id(tenant_id, conversation.booking_id)
