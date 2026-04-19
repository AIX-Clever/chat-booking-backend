"""
Domain Layer — Message Builder

Pure functions for building WhatsApp notification message text.
No dependencies on infrastructure or frameworks.
"""
from datetime import datetime
from typing import Optional

from .models import NotificationRule, BookingEvent, TriggerType


def build_message(rule: NotificationRule, event: BookingEvent) -> str:
    """
    Returns the WhatsApp message body for a given rule and booking event.
    This is pure domain logic — no I/O.
    """
    name_part = f"Hola {event.customer_name}" if event.customer_name else "Hola,"
    time_part = _format_datetime(event.booking_start_time)

    if rule.is_on_booking():
        return (
            f"{name_part}, tu reserva de {event.service_name} ha sido confirmada "
            f"para el {time_part}. ¡Te esperamos! 🗓️"
        )

    if rule.is_hours_before():
        hours = rule.hours_before or 0
        time_label = _hours_label(hours)
        return (
            f"{name_part}, te recordamos que tienes {event.service_name} en {time_label}. "
            f"📅 {time_part}. ¡Te esperamos!"
        )

    return f"{name_part}, tienes una cita próximamente: {event.service_name}."


def _format_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return "la fecha agendada"
    try:
        return dt.strftime("%-d de %B a las %H:%M")
    except ValueError:
        return dt.strftime("%d de %B a las %H:%M")


def _hours_label(hours: int) -> str:
    if hours >= 48:
        return f"{hours // 24} días"
    if hours >= 24:
        return "1 día"
    if hours == 1:
        return "1 hora"
    return f"{hours} horas"
