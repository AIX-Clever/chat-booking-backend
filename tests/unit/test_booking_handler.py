import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

# Credenciales mock ANTES de importar el handler para evitar NoRegionError
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import booking.handler as handler  # noqa: E402
from shared.domain.entities import (  # noqa: E402
    Booking,
    BookingStatus,
    PaymentStatus,
    CustomerInfo,
    TenantId,
)


def _make_booking() -> Booking:
    return Booking(
        booking_id="bk-test-001",
        tenant_id=TenantId("tenant-123"),
        service_id="svc-1",
        provider_id="pro-1",
        customer_info=CustomerInfo(
            customer_id=None,
            given_name="Ana",
            family_name="Torres",
            email="ana@example.com",
            phone="+56912345678",
        ),
        start_time=datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 6, 10, 11, 0, tzinfo=timezone.utc),
        status=BookingStatus.PENDING,
        payment_status=PaymentStatus.NONE,
        total_amount=0.0,
    )


def _public_event(extra_identity=None) -> dict:
    """Evento AppSync para reserva pública (API Key): identity=None."""
    return {
        "info": {"fieldName": "createBooking"},
        "identity": extra_identity,  # None simula la petición pública
        "arguments": {
            "input": {
                "tenantId": "tenant-123",
                "serviceId": "svc-1",
                "providerId": "pro-1",
                "start": "2026-06-10T10:00:00Z",
                "end": "2026-06-10T11:00:00Z",
                "clientFirstName": "Ana",
                "clientLastName": "Torres",
                "clientEmail": "ana@example.com",
                "clientPhone": "+56912345678",
            }
        },
    }


def _cognito_event() -> dict:
    """Evento AppSync para reserva autenticada con Cognito (JWT)."""
    return {
        "info": {"fieldName": "createBooking"},
        "identity": {
            "claims": {
                "custom:tenantId": "tenant-123",
                "sub": "user-sub-001",
            }
        },
        "arguments": {
            "input": {
                "serviceId": "svc-1",
                "providerId": "pro-1",
                "start": "2026-06-10T10:00:00Z",
                "end": "2026-06-10T11:00:00Z",
                "clientFirstName": "Ana",
                "clientLastName": "Torres",
                "clientEmail": "ana@example.com",
            }
        },
    }


class TestBookingHandlerIdentityRouting(unittest.TestCase):
    """
    Verifica que lambda_handler enruta createBooking correctamente
    tanto para peticiones públicas (identity=None) como Cognito (JWT).

    Regresión para el bug: event.get("identity", {}) devuelve None
    cuando la clave existe con valor None, causando AttributeError.
    Fix: (event.get("identity") or {}).get(...)
    """

    def setUp(self):
        self.mock_booking = _make_booking()
        handler.booking_service.create_booking = Mock(return_value=self.mock_booking)
        handler.metrics_service.increment_booking = Mock()
        handler.metrics_service.update_booking_status = Mock()

    def test_create_booking_public_identity_none_no_crash(self):
        """identity=None (API Key) no debe causar AttributeError ni crash silencioso."""
        event = _public_event(extra_identity=None)

        with patch.object(handler, "enforce_not_readonly"):
            result = handler.lambda_handler(event, None)

        # success_response devuelve el dict directamente (AppSync Direct Resolver)
        self.assertIn("bookingId", result)
        self.assertEqual(result["bookingId"], "bk-test-001")
        handler.booking_service.create_booking.assert_called_once()

    def test_create_booking_public_uses_recaptcha_check(self):
        """Petición pública (identity=None) debe pasar skip_recaptcha=False."""
        event = _public_event(extra_identity=None)
        # Sin RECAPTCHA_SECRET_KEY en env, el check se omite; solo verificamos el flag
        captured = {}

        original = handler.handle_create_booking

        def spy(tenant_id, input_data, skip_recaptcha=False):
            captured["skip_recaptcha"] = skip_recaptcha
            return original(tenant_id, input_data, skip_recaptcha=skip_recaptcha)

        with patch.object(handler, "enforce_not_readonly"):
            with patch("booking.handler.handle_create_booking", side_effect=spy):
                handler.lambda_handler(event, None)

        self.assertFalse(captured.get("skip_recaptcha"), "API Key debe usar skip_recaptcha=False")

    def test_create_booking_cognito_skips_recaptcha(self):
        """Petición autenticada con Cognito (JWT) debe pasar skip_recaptcha=True."""
        event = _cognito_event()
        captured = {}

        original = handler.handle_create_booking

        def spy(tenant_id, input_data, skip_recaptcha=False):
            captured["skip_recaptcha"] = skip_recaptcha
            return original(tenant_id, input_data, skip_recaptcha=skip_recaptcha)

        with patch.object(handler, "enforce_not_readonly"):
            with patch("booking.handler.handle_create_booking", side_effect=spy):
                handler.lambda_handler(event, None)

        self.assertTrue(captured.get("skip_recaptcha"), "Cognito debe usar skip_recaptcha=True")

    def test_create_booking_public_explicit_none_identity_key(self):
        """
        Caso exacto del bug: el dict contiene 'identity' con valor None
        (no ausente). event.get("identity", {}) devuelve None → AttributeError.
        Con el fix (or {}) debe continuar sin crash.
        """
        event = _public_event(extra_identity=None)
        # Confirmar que la clave realmente existe en el evento
        self.assertIn("identity", event)
        self.assertIsNone(event["identity"])

        with patch.object(handler, "enforce_not_readonly"):
            result = handler.lambda_handler(event, None)

        # Si hubo crash en el fix, lambda_handler lanzaría excepción; si llega aquí es correcto
        self.assertIn("bookingId", result)
        self.assertEqual(result["bookingId"], "bk-test-001")


if __name__ == "__main__":
    unittest.main()
