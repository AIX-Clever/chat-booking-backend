"""
Unit tests for notification_scheduler — hexagonal architecture.

Organized by layer:
  - Domain: NotificationRule, BookingEvent, message_builder
  - Application: ScheduleRemindersUseCase (injected mock ports)
  - Handler: record parsing, fire mode
"""
import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

from backend.notification_scheduler.domain.models import (
    BookingEvent,
    Channel,
    INotificationScheduler,
    NotificationRule,
    ReminderPayload,
    TriggerType,
)
from backend.notification_scheduler.domain.message_builder import (
    build_email_reminder,
    build_sms_reminder,
    build_reminder_payload,
)
from backend.notification_scheduler.application.schedule_reminders import ScheduleRemindersUseCase
from backend.notification_scheduler.handler import _parse_record, _to_booking_event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _future(hours: int = 48) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _event(hours_offset: int = 48, email: str = "ana@test.cl", phone: str = "+56912345678") -> BookingEvent:
    return BookingEvent(
        tenant_id="tenant-1",
        booking_id="booking-abc",
        booking_start_time=_future(hours_offset),
        customer_name="Ana",
        customer_email=email,
        customer_phone=phone,
        service_name="Masaje",
        provider_name="Dr. García",
        provider_timezone="UTC",
    )


def _rule(trigger=TriggerType.HOURS_BEFORE, active=True, hours=24) -> NotificationRule:
    return NotificationRule(id=f"remind_{hours}h", trigger=trigger, active=active, hours_before=hours)


def _mock_scheduler():
    class MockScheduler(INotificationScheduler):
        def __init__(self):
            self.calls = []

        def schedule(self, schedule_name, fire_at, payload, lambda_arn, role_arn, group_name):
            self.calls.append({
                "schedule_name": schedule_name,
                "fire_at": fire_at,
                "payload": payload,
                "lambda_arn": lambda_arn,
            })

    return MockScheduler()


# ===========================================================================
# DOMAIN — NotificationRule
# ===========================================================================

class TestNotificationRule(unittest.TestCase):
    def test_hours_before_true(self):
        r = _rule(trigger=TriggerType.HOURS_BEFORE, hours=24)
        self.assertTrue(r.is_hours_before())

    def test_on_booking_not_hours_before(self):
        r = NotificationRule(id="on_booking", trigger=TriggerType.ON_BOOKING, active=True)
        self.assertFalse(r.is_hours_before())

    def test_from_dict(self):
        d = {"id": "remind_24h", "trigger": "hours_before", "active": True, "hours_before": 24}
        r = NotificationRule.from_dict(d)
        self.assertEqual(r.hours_before, 24)
        self.assertTrue(r.is_hours_before())

    def test_from_dict_defaults(self):
        r = NotificationRule.from_dict({"trigger": "hours_before", "hours_before": 12})
        self.assertTrue(r.active)  # default True

    def test_hours_before_none_not_valid(self):
        r = NotificationRule(id="x", trigger=TriggerType.HOURS_BEFORE, active=True, hours_before=None)
        self.assertFalse(r.is_hours_before())


# ===========================================================================
# DOMAIN — BookingEvent
# ===========================================================================

class TestBookingEvent(unittest.TestCase):
    def test_fire_time_hours_before(self):
        event = _event()
        rule = _rule(hours=24)
        expected = event.booking_start_time - timedelta(hours=24)
        self.assertEqual(event.fire_time(rule), expected)

    def test_fire_time_on_booking_returns_none(self):
        event = _event()
        rule = NotificationRule(id="on_booking", trigger=TriggerType.ON_BOOKING, active=True)
        self.assertIsNone(event.fire_time(rule))

    def test_fire_time_no_hours_before_returns_none(self):
        event = _event()
        rule = NotificationRule(id="x", trigger=TriggerType.HOURS_BEFORE, active=True, hours_before=None)
        self.assertIsNone(event.fire_time(rule))


# ===========================================================================
# DOMAIN — ReminderPayload
# ===========================================================================

class TestReminderPayload(unittest.TestCase):
    def test_to_dict_and_from_dict_roundtrip(self):
        p = ReminderPayload(
            channel=Channel.EMAIL,
            tenant_id="t1",
            booking_id="b1",
            rule_id="remind_24h",
            to_address="user@test.cl",
            subject="Recordatorio",
            body_html="<p>Hola</p>",
            body_text="Hola",
        )
        d = p.to_dict()
        self.assertEqual(d["event_type"], "REMINDER_FIRE")
        restored = ReminderPayload.from_dict(d)
        self.assertEqual(restored.to_address, "user@test.cl")
        self.assertEqual(restored.channel, Channel.EMAIL)

    def test_sms_payload_roundtrip(self):
        p = ReminderPayload(
            channel=Channel.SMS, tenant_id="t1", booking_id="b1", rule_id="r1",
            phone_number="+56912345678", message="Hola Ana",
        )
        restored = ReminderPayload.from_dict(p.to_dict())
        self.assertEqual(restored.phone_number, "+56912345678")
        self.assertEqual(restored.message, "Hola Ana")


# ===========================================================================
# DOMAIN — message_builder
# ===========================================================================

class TestMessageBuilder(unittest.TestCase):
    def setUp(self):
        self.event = _event()
        self.rule = _rule(hours=24)
        self.local_start = self.event.booking_start_time

    def test_default_email_subject_contains_servicio(self):
        subject, _, _ = build_email_reminder(self.rule, self.event, self.local_start)
        self.assertIn("Masaje", subject)

    def test_default_email_body_contains_nombre_and_profesional(self):
        _, body_text, _ = build_email_reminder(self.rule, self.event, self.local_start)
        self.assertIn("Ana", body_text)
        self.assertIn("Dr. García", body_text)

    def test_custom_email_template(self):
        templates = {"remind_24h": {"subject": "Cita de {servicio}", "body": "Hola {nombre}"}}
        subject, body_text, _ = build_email_reminder(self.rule, self.event, self.local_start, templates)
        self.assertEqual(subject, "Cita de Masaje")
        self.assertEqual(body_text, "Hola Ana")

    def test_default_sms_contains_servicio(self):
        msg = build_sms_reminder(self.rule, self.event, self.local_start)
        self.assertIn("Masaje", msg)
        self.assertIn("Ana", msg)

    def test_custom_sms_template(self):
        templates = {"remind_24h": "Tu cita: {servicio} con {profesional}"}
        msg = build_sms_reminder(self.rule, self.event, self.local_start, templates)
        self.assertIn("Masaje", msg)
        self.assertIn("Dr. García", msg)

    def test_build_reminder_payload_email(self):
        payload = build_reminder_payload(
            channel=Channel.EMAIL,
            rule=self.rule,
            event=self.event,
            fire_at=self.event.booking_start_time - timedelta(hours=24),
        )
        self.assertEqual(payload.channel, Channel.EMAIL)
        self.assertEqual(payload.to_address, "ana@test.cl")
        self.assertIn("Masaje", payload.subject)

    def test_build_reminder_payload_sms(self):
        payload = build_reminder_payload(
            channel=Channel.SMS,
            rule=self.rule,
            event=self.event,
            fire_at=self.event.booking_start_time - timedelta(hours=24),
        )
        self.assertEqual(payload.channel, Channel.SMS)
        self.assertEqual(payload.phone_number, "+56912345678")
        self.assertIn("Masaje", payload.message)


# ===========================================================================
# APPLICATION — ScheduleRemindersUseCase
# ===========================================================================

class TestScheduleRemindersUseCase(unittest.TestCase):
    def _make_use_case(self, tenant_settings: dict):
        tenant = MagicMock()
        tenant.settings = tenant_settings
        tenant_repo = MagicMock()
        tenant_repo.get_by_id.return_value = tenant

        scheduler = _mock_scheduler()
        uc = ScheduleRemindersUseCase(tenant_repository=tenant_repo, scheduler=scheduler)
        return uc, scheduler

    def test_schedules_email_reminder_when_enabled(self):
        settings = {
            "email_notifications": {
                "enabled": True,
                "rules": [{"id": "remind_24h", "trigger": "hours_before", "active": True, "hours_before": 24}],
            }
        }
        uc, sched = self._make_use_case(settings)
        with patch.dict("os.environ", {
            "NOTIFICATION_SCHEDULER_LAMBDA_ARN": "arn:aws:lambda:us-east-2:123:function:notif",
            "NOTIFICATION_SCHEDULER_ROLE_ARN": "arn:aws:iam::123:role/notif-role",
        }):
            uc.execute(_event())
        self.assertEqual(len(sched.calls), 1)
        self.assertEqual(sched.calls[0]["payload"].channel, Channel.EMAIL)

    def test_does_not_schedule_when_email_disabled(self):
        settings = {"email_notifications": {"enabled": False}}
        uc, sched = self._make_use_case(settings)
        uc.execute(_event())
        self.assertEqual(len(sched.calls), 0)

    def test_does_not_schedule_when_rule_inactive(self):
        settings = {
            "email_notifications": {
                "enabled": True,
                "rules": [{"id": "remind_24h", "trigger": "hours_before", "active": False, "hours_before": 24}],
            }
        }
        uc, sched = self._make_use_case(settings)
        uc.execute(_event())
        self.assertEqual(len(sched.calls), 0)

    def test_skips_past_fire_time(self):
        # booking starts in 12h but rule is remind_24h → fire_at is 12h in the past
        settings = {
            "email_notifications": {
                "enabled": True,
                "rules": [{"id": "remind_24h", "trigger": "hours_before", "active": True, "hours_before": 24}],
            }
        }
        uc, sched = self._make_use_case(settings)
        event = _event(hours_offset=12)  # booking 12h from now → fire_at would be 12h ago
        uc.execute(event)
        self.assertEqual(len(sched.calls), 0)

    def test_schedules_sms_reminder_when_enabled(self):
        settings = {
            "email_notifications": {"enabled": False},
            "sms_notifications": {
                "enabled": True,
                "rules": [{"id": "remind_24h", "trigger": "hours_before", "active": True, "hours_before": 24}],
            },
        }
        uc, sched = self._make_use_case(settings)
        with patch.dict("os.environ", {
            "NOTIFICATION_SCHEDULER_LAMBDA_ARN": "arn:aws:lambda:us-east-2:123:function:notif",
            "NOTIFICATION_SCHEDULER_ROLE_ARN": "arn:aws:iam::123:role/notif-role",
        }):
            uc.execute(_event())
        self.assertEqual(len(sched.calls), 1)
        self.assertEqual(sched.calls[0]["payload"].channel, Channel.SMS)

    def test_skips_email_when_no_email_address(self):
        settings = {
            "email_notifications": {
                "enabled": True,
                "rules": [{"id": "remind_24h", "trigger": "hours_before", "active": True, "hours_before": 24}],
            }
        }
        uc, sched = self._make_use_case(settings)
        uc.execute(_event(email=""))
        self.assertEqual(len(sched.calls), 0)

    def test_raises_when_tenant_not_found(self):
        tenant_repo = MagicMock()
        tenant_repo.get_by_id.return_value = None
        scheduler = _mock_scheduler()
        uc = ScheduleRemindersUseCase(tenant_repository=tenant_repo, scheduler=scheduler)
        with self.assertRaises(ValueError):
            uc.execute(_event())

    def test_schedules_multiple_rules(self):
        settings = {
            "email_notifications": {
                "enabled": True,
                "rules": [
                    {"id": "remind_24h", "trigger": "hours_before", "active": True, "hours_before": 24},
                    {"id": "remind_2h", "trigger": "hours_before", "active": True, "hours_before": 2},
                ],
            }
        }
        uc, sched = self._make_use_case(settings)
        with patch.dict("os.environ", {
            "NOTIFICATION_SCHEDULER_LAMBDA_ARN": "arn:aws:lambda:us-east-2:123:function:notif",
            "NOTIFICATION_SCHEDULER_ROLE_ARN": "arn:aws:iam::123:role/notif-role",
        }):
            uc.execute(_event())
        self.assertEqual(len(sched.calls), 2)

    def test_schedule_name_truncated_to_64(self):
        settings = {
            "email_notifications": {
                "enabled": True,
                "rules": [{"id": "remind_24h", "trigger": "hours_before", "active": True, "hours_before": 24}],
            }
        }
        uc, sched = self._make_use_case(settings)
        with patch.dict("os.environ", {
            "NOTIFICATION_SCHEDULER_LAMBDA_ARN": "arn:aws:lambda:us-east-2:123:function:notif",
            "NOTIFICATION_SCHEDULER_ROLE_ARN": "arn:aws:iam::123:role/notif-role",
        }):
            uc.execute(_event())
        self.assertLessEqual(len(sched.calls[0]["schedule_name"]), 64)


# ===========================================================================
# HANDLER — record parsing
# ===========================================================================

class TestHandlerParsing(unittest.TestCase):
    def test_parse_plain_json_record(self):
        payload = {"event_type": "BOOKING_CONFIRMED", "tenant_id": "t1"}
        record = {"body": json.dumps(payload)}
        result = _parse_record(record)
        self.assertEqual(result["tenant_id"], "t1")

    def test_parse_sns_wrapped_record(self):
        inner = {"event_type": "BOOKING_CONFIRMED", "tenant_id": "t1"}
        body = {"Message": json.dumps(inner)}
        record = {"body": json.dumps(body)}
        result = _parse_record(record)
        self.assertEqual(result["tenant_id"], "t1")

    def test_parse_invalid_returns_none(self):
        result = _parse_record({"body": "not-json"})
        self.assertIsNone(result)

    def test_to_booking_event_success(self):
        payload = {
            "event_type": "BOOKING_CONFIRMED",
            "tenant_id": "t1",
            "booking_id": "b1",
            "booking_start_time": "2026-06-01T10:00:00+00:00",
            "customer_name": "Ana",
            "customer_email": "ana@test.cl",
            "customer_phone": "+56912345678",
            "service_name": "Masaje",
            "provider_name": "Dr. García",
            "provider_timezone": "America/Santiago",
        }
        event = _to_booking_event(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.tenant_id, "t1")
        self.assertEqual(event.customer_email, "ana@test.cl")
        self.assertEqual(event.provider_timezone, "America/Santiago")

    def test_to_booking_event_missing_tenant_id_returns_none(self):
        payload = {"booking_start_time": "2026-06-01T10:00:00+00:00"}
        self.assertIsNone(_to_booking_event(payload))

    def test_to_booking_event_invalid_date_returns_none(self):
        payload = {"tenant_id": "t1", "booking_start_time": "not-a-date"}
        self.assertIsNone(_to_booking_event(payload))


# ===========================================================================
# HANDLER — SMS quota check in _handle_fire
# ===========================================================================

class TestHandlerSmsQuota(unittest.TestCase):
    def _reminder(self, **kwargs):
        defaults = dict(
            channel="sms",
            tenant_id="tenant-1",
            booking_id="b1",
            rule_id="remind_24h",
            phone_number="+56912345678",
            message="Tu cita es mañana.",
        )
        defaults.update(kwargs)
        return ReminderPayload(**defaults)

    @patch("backend.notification_scheduler.handler._tenant_repo")
    @patch("backend.notification_scheduler.handler.boto3")
    def test_sms_sent_and_quota_decremented(self, mock_boto3, mock_repo):
        mock_tenant = MagicMock(sms_quota=5)
        mock_repo.get_by_id.return_value = mock_tenant
        mock_repo.decrement_sms_quota.return_value = True
        mock_sns = MagicMock()
        mock_boto3.client.return_value = mock_sns

        from backend.notification_scheduler.handler import _send_sms
        _send_sms(self._reminder())

        mock_sns.publish.assert_called_once()
        mock_repo.decrement_sms_quota.assert_called_once()

    @patch("backend.notification_scheduler.handler._tenant_repo")
    @patch("backend.notification_scheduler.handler.boto3")
    def test_sms_skipped_when_quota_zero(self, mock_boto3, mock_repo):
        mock_tenant = MagicMock(sms_quota=0)
        mock_repo.get_by_id.return_value = mock_tenant

        from backend.notification_scheduler.handler import _send_sms
        _send_sms(self._reminder())

        mock_boto3.client.assert_not_called()
        mock_repo.decrement_sms_quota.assert_not_called()

    @patch("backend.notification_scheduler.handler._tenant_repo")
    @patch("backend.notification_scheduler.handler.boto3")
    def test_sms_skipped_when_tenant_not_found(self, mock_boto3, mock_repo):
        mock_repo.get_by_id.return_value = None

        from backend.notification_scheduler.handler import _send_sms
        _send_sms(self._reminder())

        mock_boto3.client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
