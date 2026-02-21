"""Compatibility layer for legacy imports.

Historically tests and some modules imported services from `booking.service`.
The canonical implementation lives in `shared.application.booking_service`.
"""

from shared.application.booking_service import BookingQueryService, BookingService

__all__ = ["BookingService", "BookingQueryService"]

