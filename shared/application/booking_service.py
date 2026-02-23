"""
Booking Application Services (Application Layer)
Shared logic for booking management with overbooking prevention
"""

from datetime import datetime, timedelta
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc
import hashlib
import os
from typing import Optional, List
from shared.domain.entities import (
    TenantId,
    Service,
    Booking,
    BookingStatus,
    PaymentStatus,
    CustomerInfo,
)
from shared.domain.repositories import (
    IBookingRepository,
    IServiceRepository,
    IProviderRepository,
    ITenantRepository,
    IRoomRepository,
    IProviderIntegrationRepository,
    IConversationRepository,
)
from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError,
    TenantNotActiveError,
    ServiceNotAvailableError,
    ProviderNotAvailableError,
    SlotNotAvailableError,
    ConflictError,
)
from shared.utils import generate_id
from shared.infrastructure.google_auth_service import GoogleAuthService
from shared.infrastructure.microsoft_auth_service import MicrosoftAuthService

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

try:
    from shared.metrics import MetricsService
except ImportError:
    MetricsService = None


class BookingService:
    def __init__(
        self,
        booking_repo: IBookingRepository,
        service_repo: IServiceRepository,
        provider_repo: IProviderRepository,
        tenant_repo: ITenantRepository,
        room_repo: Optional[IRoomRepository] = None,
        provider_integration_repo: Optional[IProviderIntegrationRepository] = None,
        limit_service: Optional[TenantLimitService] = None,
        email_service: Optional[EmailService] = None,
        metrics_service: Optional[MetricsService] = None,
        availability_service=None,
    ):
        self._booking_repo = booking_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._tenant_repo = tenant_repo
        self._room_repo = room_repo
        self._provider_integration_repo = provider_integration_repo
        self._limit_service = limit_service
        self._email_service = email_service
        self._availability_service = availability_service
        self._metrics_service = metrics_service or (
            MetricsService() if MetricsService else None
        )

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
        conversation_id: Optional[str] = None,
    ) -> Booking:
        # Validate tenant
        tenant = self._tenant_repo.get_by_id(tenant_id)
        if not tenant:
            raise EntityNotFoundError("Tenant", tenant_id.value)

        if not tenant.can_create_booking():
            raise TenantNotActiveError(f"Tenant {tenant_id.value} cannot create bookings.")

        # Check Limits
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

        # Validate duration
        booking_duration = int((end - start).total_seconds() / 60)
        if booking_duration != service.duration_minutes:
            raise ValidationError(f"Booking duration ({booking_duration} min) must match service duration ({service.duration_minutes} min)")

        # Validate past date
        if start < datetime.now(UTC):
            raise ValidationError("No se pueden crear reservas en el pasado")

        # Validate max advance booking window (default 180 days, configurable per-env)
        max_advance_days = int(os.environ.get("MAX_BOOKING_ADVANCE_DAYS", "180"))
        if start > datetime.now(UTC) + timedelta(days=max_advance_days):
            raise ValidationError(
                f"No se pueden crear reservas con más de {max_advance_days} días de anticipación"
            )

        # Check Room
        assigned_room_id = None
        if service.required_room_ids and self._room_repo:
            assigned_room_id = self._check_and_assign_room(tenant_id, service, start, end)

        # [CRITICAL FIX] Check slot availability (prevent overbooking and respect schedule)
        if self._availability_service:
            if not self._availability_service.is_slot_available(tenant_id, service_id, provider_id, start, end):
                raise SlotNotAvailableError(f"Time slot {start.isoformat()} - {end.isoformat()} is not available or outside working hours")
        else:
            if not self._is_slot_available(tenant_id, provider_id, start, end):
                raise SlotNotAvailableError(f"Time slot {start.isoformat()} - {end.isoformat()} is not available")

        # Create booking entity
        booking_id = generate_id("bkg")
        customer_id = hashlib.md5(client_email.lower().strip().encode()).hexdigest() if client_email else None
        customer_info = CustomerInfo(customer_id=customer_id, name=client_name, email=client_email, phone=client_phone)

        status = BookingStatus.CONFIRMED if not service.price or service.price <= 0 else BookingStatus.PENDING
        payment_status = PaymentStatus.NONE if not service.price or service.price <= 0 else PaymentStatus.PENDING

        booking = Booking(
            booking_id=booking_id,
            tenant_id=tenant_id,
            service_id=service_id,
            provider_id=provider_id,
            customer_info=customer_info,
            start_time=start,
            end_time=end,
            status=status,
            payment_status=payment_status,
            conversation_id=conversation_id,
            notes=notes,
            total_amount=service.price,
            room_id=assigned_room_id,
        )

        # Payment Initialization (simplified for move)
        if PaymentGatewayFactory and service.price > 0:
            try:
                gateway = PaymentGatewayFactory.get_gateway()
                intent_data = gateway.create_payment_intent(
                    amount=service.price,
                    currency=service.currency,
                    metadata={"booking_id": booking_id, "tenant_id": tenant_id.value, "service_name": service.name},
                )
                booking.payment_intent_id = intent_data.get("payment_id")
                booking.payment_client_secret = intent_data.get("client_secret")
            except Exception as e:
                print(f"Payment init failed: {e}")

        # Save
        try:
            self._booking_repo.save(booking)
        except ConflictError:
            raise SlotNotAvailableError(f"Time slot {start.isoformat()} was just booked")

        # Syncs
        if self.google_auth_service and self._provider_integration_repo:
            self._sync_to_google_calendar(tenant_id, provider_id, booking, client_name, client_email, service.name)
        if self.microsoft_auth_service and self._provider_integration_repo:
            self._sync_to_microsoft_calendar(tenant_id, provider_id, booking, client_name, client_email, service.name)

        # Notifications
        if self._email_service and client_email:
            self._send_confirmation_email(provider, service, booking, client_name, client_email, start)

        # Metrics
        if self._metrics_service:
            try:
                self._metrics_service.increment_booking(tenant_id.value, service_id, provider_id, service.name, provider.name, service.price)
                self._metrics_service.increment_funnel_step(tenant_id.value, "booking_completed")
            except Exception:
                pass

        return booking

    def _check_and_assign_room(self, tenant_id, service, start, end):
        if not service.required_room_ids or not self._room_repo:
            return None
        for room_id in service.required_room_ids:
            room = self._room_repo.get_by_id(tenant_id, room_id)
            if room: return room_id
        return None

    def _is_slot_available(self, tenant_id, provider_id, start, end, exclude_booking_id=None):
        bookings = self._booking_repo.list_by_provider(tenant_id, provider_id, start, end)
        for booking in bookings:
            if exclude_booking_id and booking.booking_id == exclude_booking_id: continue
            if booking.is_active() and not (end <= booking.start_time or start >= booking.end_time):
                return False
        return True

    def _send_confirmation_email(self, provider, service, booking, client_name, client_email, start):
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(provider.timezone or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc
            
        local_start = start.astimezone(tz)
        subject = f"Reserva Confirmada: {service.name}"
        sender = os.environ.get("SES_SENDER_EMAIL", "noreply@antigravity.com")
        body_html = f"<html><body><h2>¡Reserva Confirmada!</h2><p>Hola {client_name}, tu reserva para {service.name} con {provider.name} ha sido confirmada para el {local_start.strftime('%Y-%m-%d %H:%M')}.</p></body></html>"
        self._email_service.send_email(source=sender, to_addresses=[client_email], subject=subject, body_html=body_html, body_text=f"Reserva confirmada para {local_start.strftime('%Y-%m-%d %H:%M')}")

    def _sync_to_google_calendar(self, tenant_id, provider_id, booking, client_name, client_email, service_name):
        try:
            creds = self._provider_integration_repo.get_google_creds(tenant_id, provider_id)
            if not creds: return
            service = self.google_auth_service.get_calendar_service(creds.get("access_token"), creds.get("refresh_token"))
            event_body = {
                "summary": f"{service_name} - {client_name}",
                "description": f"Cliente: {client_name}\nEmail: {client_email}",
                "start": {"dateTime": booking.start_time.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": booking.end_time.isoformat(), "timeZone": "UTC"},
                "attendees": [{"email": client_email}] if client_email else [],
            }
            created_event = service.events().insert(calendarId="primary", body=event_body).execute()
            booking.google_event_id = created_event.get("id")
            self._booking_repo.update(booking)
        except Exception as e: print(f"Google Sync Error: {e}")

    def _sync_to_microsoft_calendar(self, tenant_id, provider_id, booking, client_name, client_email, service_name):
        try:
            creds = self._provider_integration_repo.get_microsoft_creds(tenant_id, provider_id)
            if not (creds and self.microsoft_auth_service): return
            created_event = self.microsoft_auth_service.create_event(creds.get("access_token"), f"{service_name} - {client_name}", f"Cliente: {client_name}", booking.start_time.isoformat(), booking.end_time.isoformat(), "UTC")
            booking.microsoft_event_id = created_event.get("id")
            self._booking_repo.update(booking)
        except Exception as e: print(f"MS Sync Error: {e}")

    def confirm_booking(self, tenant_id, booking_id):
        booking = self._booking_repo.get_by_id(tenant_id, booking_id)
        if not booking: raise EntityNotFoundError("Booking", booking_id)
        booking.confirm()
        self._booking_repo.update(booking)
        return booking

    def cancel_booking(self, tenant_id, booking_id, reason=None):
        booking = self._booking_repo.get_by_id(tenant_id, booking_id)
        if not booking: raise EntityNotFoundError("Booking", booking_id)
        booking.cancel()
        self._booking_repo.update(booking)
        return booking

    def mark_as_no_show(self, tenant_id, booking_id):
        booking = self._booking_repo.get_by_id(tenant_id, booking_id)
        if not booking: raise EntityNotFoundError("Booking", booking_id)
        booking.mark_as_no_show()
        self._booking_repo.update(booking)
        return booking


class BookingQueryService:
    def __init__(self, booking_repo: IBookingRepository, conversation_repo: IConversationRepository):
        self._booking_repo = booking_repo
        self._conversation_repo = conversation_repo

    def get_booking(self, tenant_id, booking_id):
        booking = self._booking_repo.get_by_id(tenant_id, booking_id)
        if not booking: raise EntityNotFoundError("Booking", booking_id)
        return booking

    def list_by_provider(self, tenant_id, provider_id, start_date, end_date):
        return self._booking_repo.list_by_provider(tenant_id, provider_id, start_date, end_date)

    def list_by_client(self, tenant_id, client_email):
        return self._booking_repo.list_by_customer_email(tenant_id, client_email)

    def get_booking_by_conversation(self, tenant_id, conversation_id):
        conversation = self._conversation_repo.get_by_id(tenant_id, conversation_id)
        if not conversation or not conversation.booking_id: return None
        return self._booking_repo.get_by_id(tenant_id, conversation.booking_id)
