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
    IRoomAssignmentRepository,
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
    from shared.infrastructure.notifications import EmailService, SnsService, SmsService
except ImportError:
    EmailService = None
    SnsService = None
    SmsService = None

try:
    from shared.infrastructure.payment_factory import PaymentGatewayFactory
except ImportError:
    PaymentGatewayFactory = None

try:
    from shared.metrics import MetricsService
except ImportError:
    MetricsService = None


_WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _day_of_week(dt: datetime) -> str:
    return _WEEKDAYS[dt.weekday()]


def _booking_period(start: datetime, end: datetime, period_split: Optional[str]) -> str:
    """Derive MORNING / AFTERNOON / FULL from a time slot vs the room's split time."""
    if not period_split:
        return "FULL"
    from datetime import time
    split = time.fromisoformat(period_split)
    if end.time() <= split:
        return "MORNING"
    if start.time() >= split:
        return "AFTERNOON"
    return "FULL"


def _periods_overlap(p1: str, p2: str) -> bool:
    if p1 == "FULL" or p2 == "FULL":
        return True
    return p1 == p2


def _rule_active(rules: list, trigger: str, default: bool = True) -> bool:
    """Return whether the on_booking rule is active for the given channel rules list."""
    for r in rules:
        if r.get("trigger") == trigger:
            return bool(r.get("active", default))
    return default


class BookingService:
    def __init__(
        self,
        booking_repo: IBookingRepository,
        service_repo: IServiceRepository,
        provider_repo: IProviderRepository,
        tenant_repo: ITenantRepository,
        room_repo: Optional[IRoomRepository] = None,
        room_assignment_repo: Optional[IRoomAssignmentRepository] = None,
        provider_integration_repo: Optional[IProviderIntegrationRepository] = None,
        limit_service: Optional[TenantLimitService] = None,
        email_service: Optional[EmailService] = None,
        sns_service: Optional[SnsService] = None,
        sms_service: Optional[SmsService] = None,
        metrics_service: Optional[MetricsService] = None,
        availability_service=None,
    ):
        self._booking_repo = booking_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._tenant_repo = tenant_repo
        self._room_repo = room_repo
        self._room_assignment_repo = room_assignment_repo
        self._provider_integration_repo = provider_integration_repo
        self._limit_service = limit_service
        self._email_service = email_service
        self._sns_service = sns_service
        self._sms_service = sms_service
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
            raise ServiceNotAvailableError("SERVICE_NOT_AVAILABLE")

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
        assigned_room_id = self._check_and_assign_room(tenant_id, service, start, end, provider_id)

        # [CRITICAL FIX] Check slot availability (prevent overbooking and respect schedule)
        if not ignore_availability:
            if self._availability_service:
                if not self._availability_service.is_slot_available(tenant_id, service_id, provider_id, start, end):
                    raise SlotNotAvailableError("SLOT_OUTSIDE_WORKING_HOURS")
            else:
                if not self._is_slot_available(tenant_id, provider_id, start, end):
                    raise SlotNotAvailableError("SLOT_NOT_AVAILABLE")

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
            raise SlotNotAvailableError("SLOT_NOT_AVAILABLE")

        # Syncs
        full_name = f"{client_first_name} {client_last_name}".strip()
        if self.google_auth_service and self._provider_integration_repo:
            self._sync_to_google_calendar(tenant_id, provider_id, booking, full_name, client_email, service.name)
        if self.microsoft_auth_service and self._provider_integration_repo:
            self._sync_to_microsoft_calendar(tenant_id, provider_id, booking, full_name, client_email, service.name)

        # Load tenant notification settings (custom templates + channel config)
        tenant_settings = self._parse_tenant_settings(tenant)
        email_cfg = tenant_settings.get("email_notifications", {})
        sms_cfg = tenant_settings.get("sms_notifications", {})

        # Email notifications
        email_enabled = email_cfg.get("enabled", True)
        email_on_booking_active = _rule_active(email_cfg.get("rules", []), "on_booking", default=True)
        if self._email_service and client_email and email_enabled and email_on_booking_active:
            email_templates = email_cfg.get("templates", {})
            self._send_confirmation_email(provider, service, booking, full_name, client_email, start, email_templates)
        if self._email_service and getattr(provider, "email", None) and email_enabled and email_on_booking_active:
            email_templates = email_cfg.get("templates", {})
            self._send_provider_notification_email(provider, service, booking, full_name, start, email_templates)

        # SMS notifications
        sms_on_booking_active = _rule_active(sms_cfg.get("rules", []), "on_booking", default=True)
        if self._sms_service and client_phone and sms_cfg.get("enabled", False) and sms_on_booking_active:
            try:
                self._send_sms_notification(service, booking, full_name, client_phone, start, provider, sms_cfg)
            except Exception as e:
                import logging
                logging.getLogger().warning(f"Failed to send SMS notification: {str(e)}")

        # Publish BOOKING_CONFIRMED event for reminder schedulers (email + SMS hours_before rules)
        if self._sns_service:
            try:
                self._publish_booking_confirmed(
                    booking, full_name, client_email, client_phone, service, provider, start
                )
            except Exception as e:
                import logging
                logging.getLogger().warning(f"Failed to publish BOOKING_CONFIRMED event: {str(e)}")

        # Metrics
        if self._metrics_service:
            try:
                self._metrics_service.increment_booking(tenant_id.value, service_id, provider_id, service.name, provider.name, service.price)
                self._metrics_service.increment_funnel_step(tenant_id.value, "booking_completed")
            except Exception:
                pass

        return booking

    def _check_and_assign_room(self, tenant_id, service, start, end, provider_id=None):
        day = _day_of_week(start)

        # 1. Exclusive assignment — provider owns a room on this day/period
        if provider_id and self._room_assignment_repo and self._room_repo:
            for assignment in self._room_assignment_repo.list_by_provider(tenant_id, provider_id):
                period_for_day = assignment.day_periods.get(day)
                if not period_for_day:
                    continue
                room = self._room_repo.get_by_id(tenant_id, assignment.room_id)
                if not room:
                    continue
                booking_period = _booking_period(start, end, room.period_split)
                if _periods_overlap(booking_period, period_for_day):
                    return assignment.room_id

        # 2. Fallback — first available room from service.required_room_ids
        #    skipping rooms exclusively assigned to a different provider this day/period
        if not service.required_room_ids or not self._room_repo:
            return None
        for room_id in service.required_room_ids:
            room = self._room_repo.get_by_id(tenant_id, room_id)
            if not room:
                continue
            if self._room_assignment_repo and provider_id:
                booking_period = _booking_period(start, end, room.period_split)
                if self._is_room_blocked(tenant_id, room_id, provider_id, day, booking_period):
                    continue
            return room_id
        return None

    def _is_room_blocked(self, tenant_id, room_id, provider_id, day, booking_period):
        """True if room is exclusively assigned to a *different* provider on this day/period."""
        for assignment in self._room_assignment_repo.list_by_room(tenant_id, room_id):
            if assignment.provider_id == provider_id:
                continue
            period_for_day = assignment.day_periods.get(day)
            if period_for_day and _periods_overlap(booking_period, period_for_day):
                return True
        return False

    def _is_slot_available(self, tenant_id, provider_id, start, end, exclude_booking_id=None):
        bookings = self._booking_repo.list_by_provider(tenant_id, provider_id, start, end)
        for booking in bookings:
            if exclude_booking_id and booking.booking_id == exclude_booking_id: continue
            if booking.is_active() and not (end <= booking.start_time or start >= booking.end_time):
                return False
        return True
    def _get_frontend_url(self) -> str:
        url = os.environ.get("FRONTEND_URL")
        if not url:
            raise RuntimeError("FRONTEND_URL env var is required but not set")
        return url

    def _parse_tenant_settings(self, tenant) -> dict:
        """Safely parse tenant.settings JSON into a dict."""
        raw = getattr(tenant, "settings", None)
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _send_confirmation_email(self, provider, service, booking, client_name, client_email, start, custom_templates: dict = None):
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(provider.timezone or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc

        local_start = start.astimezone(tz)
        hora = local_start.strftime('%H:%M')

        # Mapeo manual para Español seguro en Lambda
        days = {"Monday":"Lunes", "Tuesday":"Martes", "Wednesday":"Miércoles", "Thursday":"Jueves", "Friday":"Viernes", "Saturday":"Sábado", "Sunday":"Domingo"}
        months = {"January":"enero", "February":"febrero", "March":"marzo", "April":"abril", "May":"mayo", "June":"junio", "July":"julio", "August":"agosto", "September":"septiembre", "October":"octubre", "November":"noviembre", "December":"diciembre"}
        day_es = days.get(local_start.strftime('%A'), local_start.strftime('%A'))
        month_es = months.get(local_start.strftime('%B'), local_start.strftime('%B'))
        date_es = f"{day_es} {local_start.strftime('%d')} de {month_es}, {local_start.strftime('%Y')}"

        tmpl = (custom_templates or {}).get("client_confirmation", {})
        vars_map = dict(nombre=client_name, servicio=service.name, fecha=date_es, hora=hora, profesional=provider.name)

        subject = tmpl.get("subject", "Reserva Confirmada: {servicio}").format(**vars_map)
        body_text = tmpl.get("body", "¡Reserva confirmada! Hola {nombre}, te esperamos el {fecha} a las {hora} para {servicio}.").format(**vars_map)

        frontend_url = self._get_frontend_url()
        frontend_domain = frontend_url.replace("https://", "").replace("http://", "").split("/")[0]
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
        <p style="font-size: 22px; color: #4A90D9; font-weight: bold; margin: 10px 0;">⏰ {hora} hrs</p>
    </div>

    <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; text-align: center; font-size: 12px; color: #999;">
      <p>Ref: {booking.booking_id} · Servicio de reservas de <a href="{frontend_url}" style="color: #4A90D9; text-decoration: none; font-weight: bold;">{frontend_domain}</a>.</p>
      <p>Si no deseas recibir más notificaciones, puedes <a href="{frontend_url}/unsubscribe?email={client_email}" style="color: #999; text-decoration: underline;">desuscribirte aquí</a>.</p>
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
            body_text=body_text,
        )

    def _send_provider_notification_email(self, provider, service, booking, client_name, start, custom_templates: dict = None):
        """Send booking notification email to the provider with a friendly time label."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(provider.timezone or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc

        local_start = start.astimezone(tz)
        hora = local_start.strftime('%H:%M')
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

        tmpl = (custom_templates or {}).get("provider_notification", {})
        vars_map = dict(nombre=client_name, servicio=service.name, fecha=date_es, hora=hora, profesional=provider.name, cuando=time_label)

        subject = tmpl.get("subject", "Nueva reserva: {servicio} – {cuando}").format(**vars_map)
        body_text = tmpl.get("body", "Nueva reserva {cuando}: {servicio} con {nombre} el {fecha} a las {hora}.").format(**vars_map)

        frontend_url = self._get_frontend_url()
        frontend_domain = frontend_url.replace("https://", "").replace("http://", "").split("/")[0]
        sender = os.environ.get("SES_SENDER_EMAIL")
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
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">Ref:</td><td style="padding:10px 0; color:#333;">{booking.booking_id}</td></tr>
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">Fecha asignada:</td><td style="padding:10px 0; color:#333; font-weight:bold;">{date_es}</td></tr>
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">Hora inicio:</td><td style="padding:10px 0; color:#4A90D9; font-weight:bold; font-size:18px;">{hora} hrs</td></tr>
          <tr style="border-top:1px solid #eee;"><td style="padding:10px 0; font-weight:bold; color:#777;">¿Cuándo es?</td><td style="padding:10px 0; color:#28a745; font-weight:bold; text-transform: uppercase;">{time_label}</td></tr>
        </table>
    </div>

    <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; text-align: center; font-size: 12px; color: #999;">
      <p>Notificación automática de <a href="{frontend_url}" style="color: #4A90D9; text-decoration: none; font-weight: bold;">{frontend_domain}</a>.</p>
      <p>Si no deseas recibir más notificaciones, puedes <a href="{frontend_url}/unsubscribe?email={provider.email}" style="color: #999; text-decoration: underline;">desuscribirte aquí</a>.</p>
    </div>
  </div>
</body>
</html>"""
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

    def _publish_booking_confirmed(self, booking, client_name, client_email, client_phone, service, provider, start):
        """Publish BOOKING_CONFIRMED event to SNS so schedulers can program reminders."""
        topic_arn = os.environ.get("BOOKING_CONFIRMED_TOPIC_ARN") or os.environ.get("WHATSAPP_NOTIFICATION_TOPIC")
        if not topic_arn:
            return

        payload = {
            "event_type": "BOOKING_CONFIRMED",
            "tenant_id": booking.tenant_id.value,
            "booking_id": booking.booking_id,
            "booking_start_time": start.isoformat(),
            "customer_name": client_name,
            "customer_email": client_email or "",
            "customer_phone": client_phone or "",
            "service_name": service.name,
            "provider_name": getattr(provider, "name", ""),
            "provider_timezone": getattr(provider, "timezone", "UTC") or "UTC",
        }
        self._sns_service.publish_message(
            topic_arn=topic_arn,
            message=json.dumps(payload),
            message_attributes={
                "event_type": {"DataType": "String", "StringValue": "BOOKING_CONFIRMED"},
            },
        )

    def _send_sms_notification(self, service, booking, client_name, client_phone, start, provider, sms_cfg: dict):
        """Send SMS confirmation via AWS SNS direct publish."""
        tenant = self._tenant_repo.get_by_id(booking.tenant_id)
        if not tenant or tenant.sms_quota <= 0:
            import logging
            logging.getLogger().warning(
                f"SMS quota exhausted or tenant not found for {booking.tenant_id}. Skipping SMS."
            )
            return

        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(provider.timezone or "UTC")
        except Exception:
            from datetime import timezone
            tz = timezone.utc

        local_start = start.astimezone(tz)
        hora = local_start.strftime('%H:%M')
        date_str = local_start.strftime('%d/%m/%Y')

        tmpl_text = (sms_cfg.get("templates") or {}).get(
            "on_booking",
            "Hola {nombre}, tu reserva de {servicio} está confirmada: {fecha} a las {hora}.",
        )
        vars_map = dict(nombre=client_name, servicio=service.name, fecha=date_str, hora=hora)
        message = tmpl_text.format(**vars_map)

        sent = self._sms_service.send_sms(phone_number=client_phone, message=message)
        if sent:
            self._tenant_repo.decrement_sms_quota(booking.tenant_id)

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
