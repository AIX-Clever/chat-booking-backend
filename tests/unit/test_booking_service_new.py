import unittest
import os
from datetime import datetime, timedelta, UTC
from unittest.mock import Mock, patch, MagicMock

# Prevent boto3/botocore NoRegionError during unit test imports
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

from shared.domain.entities import (
    TenantId,
    Booking,
    BookingStatus,
    PaymentStatus,
    CustomerInfo,
    Service,
)
from shared.application.booking_service import BookingService
from shared.domain.exceptions import SlotNotAvailableError


class TestBookingService(unittest.TestCase):
    def setUp(self):
        self.mock_booking_repo = Mock()
        self.mock_service_repo = Mock()
        self.mock_provider_repo = Mock()
        self.mock_tenant_repo = Mock()
        self.mock_availability_service = Mock()

        self.service = BookingService(
            booking_repo=self.mock_booking_repo,
            service_repo=self.mock_service_repo,
            provider_repo=self.mock_provider_repo,
            tenant_repo=self.mock_tenant_repo,
            availability_service=self.mock_availability_service
        )
        
        self.tenant_id = TenantId("tenant-123")
        self.service_id = "svc-1"
        self.provider_id = "pro-1"
        
        # Mock active tenant
        self.mock_tenant = Mock()
        self.mock_tenant.is_active.return_value = True
        self.mock_tenant_repo.get_by_id.return_value = self.mock_tenant

        # Mock service
        self.mock_service = Mock(spec=Service)
        self.mock_service.service_id = self.service_id
        self.mock_service.name = "Test Service"
        self.mock_service.duration_minutes = 60
        self.mock_service.price = 100.0
        self.mock_service_repo.get_by_id.return_value = self.mock_service

    def test_create_booking_success_paid(self):
        """Test successful booking creation when slot is available for PAID service"""
        # 1. Setup mocks
        self.mock_availability_service.is_slot_available.return_value = True
        self.mock_service.price = 100.0
        
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        end = start + timedelta(minutes=60)
        
        # 2. Execute
        booking = self.service.create_booking(
            tenant_id=self.tenant_id,
            service_id=self.service_id,
            provider_id=self.provider_id,
            start=start,
            end=end,
            client_first_name="Test",
            client_last_name="Client",
            client_email="test@example.com"
        )
        
        # 3. Verify
        self.assertEqual(booking.status, BookingStatus.PENDING)
        self.assertEqual(booking.payment_status, PaymentStatus.PENDING)
        self.mock_booking_repo.save.assert_called_once()

    def test_create_booking_success_free(self):
        """Test successful booking creation when slot is available for FREE service"""
        # 1. Setup mocks
        self.mock_availability_service.is_slot_available.return_value = True
        self.mock_service.price = 0
        
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
        end = start + timedelta(minutes=60)
        
        # 2. Execute
        booking = self.service.create_booking(
            tenant_id=self.tenant_id,
            service_id=self.service_id,
            provider_id=self.provider_id,
            start=start,
            end=end,
            client_first_name="Test",
            client_last_name="Client",
            client_email="test@example.com"
        )
        
        # 3. Verify
        self.assertEqual(booking.status, BookingStatus.CONFIRMED)
        self.assertEqual(booking.payment_status, PaymentStatus.NONE)
        self.mock_booking_repo.save.assert_called_once()

    def test_create_booking_slot_unavailable(self):
        """Test booking failure when slot is NOT available"""
        # 1. Setup mocks
        self.mock_availability_service.is_slot_available.return_value = False
        
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        end = start + timedelta(minutes=60)
        
        # 2. Execute & Verify Exception
        with self.assertRaises(SlotNotAvailableError):
            self.service.create_booking(
                tenant_id=self.tenant_id,
                service_id=self.service_id,
                provider_id=self.provider_id,
                start=start,
                end=end,
                client_first_name="Test",
                client_last_name="Client",
                client_email="test@example.com"
            )
        
        self.mock_booking_repo.save.assert_not_called()

    def test_max_advance_booking_rejected(self):
        """Test booking too far in the future is rejected (Fix 5)"""
        from shared.domain.exceptions import ValidationError
        self.mock_availability_service.is_slot_available.return_value = True
        self.mock_service.price = 0

        # 200 days in the future, beyond default 180-day limit
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=200)
        end = start + timedelta(minutes=60)

        with patch.dict('os.environ', {'MAX_BOOKING_ADVANCE_DAYS': '180'}):
            with self.assertRaises(ValidationError) as ctx:
                self.service.create_booking(
                    tenant_id=self.tenant_id,
                    service_id=self.service_id,
                    provider_id=self.provider_id,
                    start=start,
                    end=end,
                    client_first_name="Test",
                    client_last_name="Client",
                    client_email="test@example.com"
                )
        self.assertIn("180", str(ctx.exception))
        self.mock_booking_repo.save.assert_not_called()

    def test_max_advance_booking_allowed(self):
        """Test booking within the 180-day window is allowed (Fix 5)"""
        self.mock_availability_service.is_slot_available.return_value = True
        self.mock_service.price = 0

        # 90 days in the future, within default 180-day limit
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=90)
        end = start + timedelta(minutes=60)

        with patch.dict('os.environ', {'MAX_BOOKING_ADVANCE_DAYS': '180'}):
            booking = self.service.create_booking(
                tenant_id=self.tenant_id,
                service_id=self.service_id,
                provider_id=self.provider_id,
                start=start,
                end=end,
                client_first_name="Test",
                client_last_name="Client",
                client_email="test@example.com"
            )
        self.assertIsNotNone(booking)
        self.mock_booking_repo.save.assert_called_once()


class TestFrontendUrlEnvVar(unittest.TestCase):
    def test_raises_runtime_error_when_not_set(self):
        svc = BookingService(
            booking_repo=Mock(),
            service_repo=Mock(),
            provider_repo=Mock(),
            tenant_repo=Mock(),
        )
        with patch.dict('os.environ', {}, clear=True):
            os.environ.pop("FRONTEND_URL", None)
            with self.assertRaises(RuntimeError) as ctx:
                svc._get_frontend_url()
        self.assertIn("FRONTEND_URL", str(ctx.exception))

    def test_returns_url_when_set(self):
        svc = BookingService(
            booking_repo=Mock(), service_repo=Mock(),
            provider_repo=Mock(), tenant_repo=Mock(),
        )
        with patch.dict('os.environ', {"FRONTEND_URL": "https://example.com"}):
            url = svc._get_frontend_url()
        self.assertEqual(url, "https://example.com")


class TestEmailCustomTemplates(unittest.TestCase):
    def setUp(self):
        self.mock_email_service = Mock()
        self.svc = BookingService(
            booking_repo=Mock(), service_repo=Mock(),
            provider_repo=Mock(), tenant_repo=Mock(),
            email_service=self.mock_email_service,
        )
        self.provider = Mock(timezone="UTC", name="Dr. García", email="dr@example.com")
        self.service = Mock(name="Masaje", duration_minutes=60, price=0)
        self.booking = Mock(booking_id="bkg-1", tenant_id=Mock(value="t1"))
        self.start = datetime.now(UTC) + timedelta(days=1)

    def test_default_subject_used_when_no_template(self):
        with patch.dict('os.environ', {"FRONTEND_URL": "https://example.com", "SES_SENDER_EMAIL": "no-reply@test.cl"}):
            self.svc._send_confirmation_email(
                self.provider, self.service, self.booking, "Ana", "ana@test.cl", self.start
            )
        call_kwargs = self.mock_email_service.send_email.call_args[1]
        self.assertIn("Masaje", call_kwargs["subject"])

    def test_custom_subject_and_body_used(self):
        custom = {
            "client_confirmation": {
                "subject": "Tu cita de {servicio} está lista, {nombre}!",
                "body": "Nos vemos el {fecha} a las {hora}. — {profesional}",
            }
        }
        with patch.dict('os.environ', {"FRONTEND_URL": "https://example.com", "SES_SENDER_EMAIL": "no-reply@test.cl"}):
            self.svc._send_confirmation_email(
                self.provider, self.service, self.booking, "Ana", "ana@test.cl",
                self.start, custom_templates=custom
            )
        call_kwargs = self.mock_email_service.send_email.call_args[1]
        self.assertIn("Ana", call_kwargs["subject"])
        self.assertIn("Masaje", call_kwargs["subject"])
        self.assertIn("Dr. García", call_kwargs["body_text"])


class TestSmsNotification(unittest.TestCase):
    def setUp(self):
        self.mock_sms = Mock()
        self.svc = BookingService(
            booking_repo=Mock(), service_repo=Mock(),
            provider_repo=Mock(), tenant_repo=Mock(),
            sms_service=self.mock_sms,
        )
        self.provider = Mock(timezone="UTC", name="Dr. García")
        self.service = Mock(name="Masaje")
        self.booking = Mock(booking_id="bkg-1", tenant_id=Mock(value="t1"))
        self.start = datetime.now(UTC) + timedelta(days=1)

    def test_default_sms_template_used(self):
        self.svc._send_sms_notification(
            self.service, self.booking, "Ana", "+56912345678",
            self.start, self.provider, sms_cfg={}
        )
        self.mock_sms.send_sms.assert_called_once()
        args = self.mock_sms.send_sms.call_args[1]
        self.assertEqual(args["phone_number"], "+56912345678")
        self.assertIn("Masaje", args["message"])

    def test_custom_sms_template_used(self):
        cfg = {"templates": {"on_booking": "Cita de {servicio} para {nombre} el {fecha}."}}
        self.svc._send_sms_notification(
            self.service, self.booking, "Ana", "+56912345678",
            self.start, self.provider, sms_cfg=cfg
        )
        args = self.mock_sms.send_sms.call_args[1]
        self.assertIn("Masaje", args["message"])
        self.assertIn("Ana", args["message"])


if __name__ == "__main__":
    unittest.main()
