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
import json
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
    from shared.infrastructure.notifications import EmailService, SnsService
except ImportError:
    EmailService = None
    SnsService = None

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
        sns_service: Optional[SnsService] = None,
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
        self._sns_service = sns_service
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
        client_first_name: str,
        client_last_name: str,
        client_email: str,
        client_phone: Optional[str] = None,
        notes: Optional[str] = None,
        conversation_id: Optional[str] = None,
        ignore_availability: bool = False,
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
        if not ignore_availability:
            if self._availability_service:
                if not self._availability_service.is_slot_available(tenant_id, service_id, provider_id, start, end):
                    raise SlotNotAvailableError(f"Time slot {start.isoformat()} - {end.isoformat()} is not available or outside working hours")
            else:
                if not self._is_slot_available(tenant_id, provider_id, start, end):
                    raise SlotNotAvailableError(f"Time slot {start.isoformat()} - {end.isoformat()} is not available")

        # Create booking entity
        booking_id = generate_id("bkg")
        customer_id = hashlib.md5(client_email.lower().strip().encode()).hexdigest() if client_email else None
        customer_info = CustomerInfo(customer_id=customer_id, given_name=client_first_name, family_name=client_last_name, email=client_email, phone=client_phone)

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
        full_name = f"{client_first_name} {client_last_name}".strip()
        if self.google_auth_service and self._provider_integration_repo:
            self._sync_to_google_calendar(tenant_id, provider_id, booking, full_name, client_email, service.name)
        if self.microsoft_auth_service and self._provider_integration_repo:
            self._sync_to_microsoft_calendar(tenant_id, provider_id, booking, full_name, client_email, service.name)

        # Notifications
        if self._email_service and client_email:
            self._send_confirmation_email(provider, service, booking, full_name, client_email, start)
        if self._email_service and getattr(provider, "email", None):
            self._send_provider_notification_email(provider, service, booking, full_name, start)
            
        if self._sns_service and client_phone:
            # We are sending to Whatsapp only if they provided a phone
            try:
                self._send_whatsapp_notification(provider, service, booking, full_name, client_phone, start)
            except Exception as e:
                import logging
                logging.getLogger().warning(f"Failed to enqueue WhatsApp notification: {str(e)}")

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
    def _get_frontend_url(self) -> str:
        """Determina la URL del frontend basándose en las variables de entorno inyectadas via CDK"""
        return os.environ.get("FRONTEND_URL")

    def _send_confirmation_email(self, provider, service, booking, client_name, client_email, start):
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(provider.timezone or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc
            
        local_start = start.astimezone(tz)
        
        # Mapeo manual para Español seguro en Lambda
        days = {"Monday":"Lunes", "Tuesday":"Martes", "Wednesday":"Miércoles", "Thursday":"Jueves", "Friday":"Viernes", "Saturday":"Sábado", "Sunday":"Domingo"}
        months = {"January":"enero", "February":"febrero", "March":"marzo", "April":"abril", "May":"mayo", "June":"junio", "July":"julio", "August":"agosto", "September":"septiembre", "October":"octubre", "November":"noviembre", "December":"diciembre"}
        day_es = days.get(local_start.strftime('%A'), local_start.strftime('%A'))
        month_es = months.get(local_start.strftime('%B'), local_start.strftime('%B'))
        date_es = f"{day_es} {local_start.strftime('%d')} de {month_es}, {local_start.strftime('%Y')}"
        
        subject = f"Reserva Confirmada: {service.name}"
        sender = os.environ.get("SES_SENDER_EMAIL")
        body_html = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #f8f9fa; padding: 30px; border-radius: 10px; border-top: 5px solid #4A90D9; text-align: center;">
    <h1 style="color: #4A90D9; margin-top: 0;">¡Tu reserva está confirmada! 🎉</h1>
    <p style="font-size: 16px;">Hola <strong>{client_name}</strong>,</p>
    <p style="font-size: 16px;">Nos alegra confirmarte que tu reserva para <strong>{service.name}</strong> con <strong>{provider.name}</strong> ha sido agendada exitosamente.</p>
    
    <div style="background-color: #ffffff; padding: 20px; border-radius: 8px; margin: 25px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center;">
        <h3 style="margin-top: 0; color: #555; border-bottom: 1px solid #eee; padding-bottom: 10px;">📅 Detalles de tu cita</h3>
        <p style="font-size: 18px; margin: 10px 0; color: #333; text-transform: capitalize;"><strong>{date_es}</strong></p>
        <p style="font-size: 22px; color: #4A90D9; font-weight: bold; margin: 10px 0;">⏰ {local_start.strftime('%H:%M')} hrs</p>
    </div>
    
    <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; text-align: center; font-size: 12px; color: #999;">
      <p>Este es un correo enviado por el servicio de reservas con inteligencia artificial de <a href="{self._get_frontend_url()}" style="color: #4A90D9; text-decoration: none; font-weight: bold;">{self._get_frontend_url().replace("https://", "").replace("http://", "").split("/")[0]}</a>.</p>
      <p>Si no deseas recibir más notificaciones, puedes <a href="{self._get_frontend_url()}/unsubscribe?email={client_email}" style="color: #999; text-decoration: underline;">desuscribirte aquí</a>.</p>
    </div>
  </div>
</body>
</html>
"""
        self._email_service.send_email(
            source=sender, 
            to_addresses=[client_email], 
            subject=subject, 
            body_html=body_html, 
            body_text=f"¡Reserva confirmada! Hola {client_name}, te esperamos el {date_es} a las {local_start.strftime('%H:%M')} para {service.name}."
        )

    def _send_provider_notification_email(self, provider, service, booking, client_name, start):
        """Send booking notification email to the provider with a friendly time label."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(provider.timezone or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc

        local_start = start.astimezone(tz)
        today = datetime.now(tz).date()
        booking_date = local_start.date()
        days_diff = (booking_date - today).days
        
        # Mapeo manual para Español seguro en Lambda
        days = {"Monday":"Lunes", "Tuesday":"Martes", "Wednesday":"Miércoles", "Thursday":"Jueves", "Friday":"Viernes", "Saturday":"Sábado", "Sunday":"Domingo"}
        months = {"January":"enero", "February":"febrero", "March":"marzo", "April":"abril", "May":"mayo", "June":"junio", "July":"julio", "August":"agosto", "September":"septiembre", "October":"octubre", "November":"noviembre", "December":"diciembre"}
        day_es = days.get(local_start.strftime('%A'), local_start.strftime('%A'))
        month_es = months.get(local_start.strftime('%B'), local_start.strftime('%B'))
        date_es = f"{day_es} {local_start.strftime('%d')} de {month_es}, {local_start.strftime('%Y')}"

        if days_diff == 0:
            time_label = "hoy"
        elif days_diff == 1:
            time_label = "mañana"
        elif days_diff > 1:
            time_label = f"en {days_diff} días"
        else:
            time_label = local_start.strftime('%Y-%m-%d')

        sender = os.environ.get("SES_SENDER_EMAIL")
        subject = f"Nueva reserva: {service.name} – {time_label}"
        body_html = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #f3f8fe; padding: 30px; border-radius: 10px; border-top: 5px solid #28a745; text-align: left;">
    <h1 style="color: #28a745; margin-top: 0; text-align: center;">¡Tienes una nueva reserva agendada! 📅</h1>
    <p style="font-size: 16px; text-align: center;">Hola <strong>{provider.name}</strong>, el cliente <strong>{client_name}</strong> te ha agendado exitosamente.</p>
    
    <div style="background-color: #ffffff; padding: 25px; border-radius: 8px; margin: 25px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
        <h3 style="margin-top: 0; color: #555; border-bottom: 1px solid #eee; padding-bottom: 10px;">Resumen del cliente</h3>
        <table style="border-collapse:collapse; width:100%;">
          <tr><td style="padding:10px 0; font-weight:bold; color:#777; width:40%;">Servicio:</td><td style="padding:10px 0; color:#333;">{service.name}</td></tr>
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">Cliente:</td><td style="padding:10px 0; color:#333;">{client_name}</td></tr>
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">Fecha asignada:</td><td style="padding:10px 0; color:#333; font-weight:bold;">{date_es}</td></tr>
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">Hora inicio:</td><td style="padding:10px 0; color:#4A90D9; font-weight:bold; font-size:18px;">{local_start.strftime('%H:%M')} hrs</td></tr>
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">¿Cuándo es?</td><td style="padding:10px 0; color:#28a745; font-weight:bold; text-transform: uppercase;">{time_label}</td></tr>
        </table>
    </div>
    
    <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; text-align: center; font-size: 12px; color: #999;">
      <p>Este es una notificación automática enviada por el servicio de reservas con inteligencia artificial de <a href="{self._get_frontend_url()}" style="color: #4A90D9; text-decoration: none; font-weight: bold;">{self._get_frontend_url().replace("https://", "").replace("http://", "").split("/")[0]}</a>.</p>
      <p>Si no deseas recibir más notificaciones, puedes <a href="{self._get_frontend_url()}/unsubscribe?email={provider.email}" style="color: #999; text-decoration: underline;">desuscribirte aquí</a>.</p>
    </div>
  </div>
</body>
</html>"""
        body_text = f"Nueva reserva {time_label}: {service.name} con {client_name} el {date_es} a las {local_start.strftime('%H:%M')}."
        try:
            self._email_service.send_email(
                source=sender,
                to_addresses=[provider.email],
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )
        except Exception as e:
            print(f"[BookingService] Error sending provider notification: {e}")

    def _send_whatsapp_notification(self, provider, service, booking, client_name, client_phone, start):
        """Send a WhatsApp notification via SNS to the configured Sender Lambda."""
        topic_arn = os.environ.get("WHATSAPP_NOTIFICATION_TOPIC")
        if not topic_arn:
            return  # WhatsApp not configured for this environment
            
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(provider.timezone or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc

        local_start = start.astimezone(tz)
        formatted_date = local_start.strftime('%d/%m/%Y a las %H:%M')

        # Using a reliable template that matches a likely Twilio approved template, 
        # or just sending the body (the sender lambda handles Twilio integration).
        # We pass the necessary variables so the sender lambda can format the final message.
        payload = {
            "tenantId": booking.tenant_id.value,
            "bookingId": booking.booking_id,
            "destinationPhone": client_phone,
            "templateName": "booking_confirmation", # Assuming we have templates later
            "parameters": {
                "clientName": client_name,
                "serviceName": service.name,
                "providerName": provider.name,
                "dateTime": formatted_date
            }
        }
        
        # Publish the event to SNS
        self._sns_service.publish_message(
            topic_arn=topic_arn,
            message=json.dumps(payload)
        )

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
