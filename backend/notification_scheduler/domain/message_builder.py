"""
Domain Layer — Message Builder for Email and SMS reminders.

Pure functions: no I/O, no AWS SDK.
"""
from datetime import datetime
from typing import Optional

from .models import BookingEvent, NotificationRule, ReminderPayload, Channel


DEFAULT_EMAIL_SUBJECT = "Recordatorio: tu cita de {servicio} es pronto"
DEFAULT_EMAIL_BODY = (
    "Hola {nombre},\n\n"
    "Te recordamos que tienes una cita de {servicio} con {profesional} el {fecha} a las {hora}.\n\n"
    "¡Te esperamos!"
)
DEFAULT_SMS_TEMPLATE = (
    "Recordatorio: {nombre}, tu cita de {servicio} con {profesional} "
    "es el {fecha} a las {hora}."
)


def build_email_reminder(
    rule: NotificationRule,
    event: BookingEvent,
    local_start: datetime,
    email_templates: Optional[dict] = None,
) -> tuple[str, str, str]:
    """Returns (subject, body_text, body_html) for an email reminder."""
    fecha = local_start.strftime("%d/%m/%Y")
    hora = local_start.strftime("%H:%M")
    vars_map = dict(
        nombre=event.customer_name,
        servicio=event.service_name,
        profesional=event.provider_name,
        fecha=fecha,
        hora=hora,
    )

    templates = email_templates or {}
    key = f"remind_{rule.hours_before}h" if rule.hours_before else rule.id

    subject_tmpl = templates.get(key, {}).get("subject") or DEFAULT_EMAIL_SUBJECT
    body_tmpl = templates.get(key, {}).get("body") or DEFAULT_EMAIL_BODY

    subject = subject_tmpl.format(**vars_map)
    body_text = body_tmpl.format(**vars_map)
    body_html = body_text.replace("\n", "<br>")
    return subject, body_text, body_html


def build_sms_reminder(
    rule: NotificationRule,
    event: BookingEvent,
    local_start: datetime,
    sms_templates: Optional[dict] = None,
) -> str:
    """Returns the SMS message for a reminder."""
    fecha = local_start.strftime("%d/%m/%Y")
    hora = local_start.strftime("%H:%M")
    vars_map = dict(
        nombre=event.customer_name,
        servicio=event.service_name,
        profesional=event.provider_name,
        fecha=fecha,
        hora=hora,
    )

    templates = sms_templates or {}
    key = f"remind_{rule.hours_before}h" if rule.hours_before else rule.id
    tmpl = templates.get(key) or DEFAULT_SMS_TEMPLATE
    return tmpl.format(**vars_map)


def _localize(dt: datetime, timezone_str: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo(timezone_str or "UTC"))
    except Exception:
        return dt


def build_reminder_payload(
    channel: str,
    rule: NotificationRule,
    event: BookingEvent,
    fire_at: datetime,
    email_templates: Optional[dict] = None,
    sms_templates: Optional[dict] = None,
    sender_email: str = "",
) -> ReminderPayload:
    """Build the full ReminderPayload that will be stored in EventBridge and sent later."""
    local_start = _localize(event.booking_start_time, event.provider_timezone)

    if channel == Channel.EMAIL:
        subject, body_text, body_html = build_email_reminder(rule, event, local_start, email_templates)
        return ReminderPayload(
            channel=channel,
            tenant_id=event.tenant_id,
            booking_id=event.booking_id,
            rule_id=rule.id,
            to_address=event.customer_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )
    else:  # SMS
        message = build_sms_reminder(rule, event, local_start, sms_templates)
        return ReminderPayload(
            channel=channel,
            tenant_id=event.tenant_id,
            booking_id=event.booking_id,
            rule_id=rule.id,
            phone_number=event.customer_phone,
            message=message,
        )
