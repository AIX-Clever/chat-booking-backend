"""
Unit tests for whatsapp_scheduler — hexagonal architecture.

Tests are organized by layer:
  - Domain: NotificationRule, BookingEvent, message_builder (pure, no mocks needed)
  - Application: ScheduleNotificationsUseCase (inject mock ports)
  - Handler: record parsing, BookingEvent construction
"""
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call

import pytest

from backend.whatsapp_scheduler.domain.models import (
    NotificationRule, BookingEvent, TriggerType,
    INotificationPublisher, INotificationScheduler,
)
from backend.whatsapp_scheduler.domain.message_builder import build_message, _hours_label
from backend.whatsapp_scheduler.application.schedule_notifications import (
    ScheduleNotificationsUseCase, DEFAULT_RULES,
)
from backend.whatsapp_scheduler.handler import _parse_record, _to_booking_event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _future_dt(hours: int = 48) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _booking(hours_offset: int = 48, phone: str = "+56912345678") -> BookingEvent:
    return BookingEvent(
        tenant_id="tenant-1",
        booking_id="booking-abc",
        booking_start_time=_future_dt(hours_offset),
        customer_phone=phone,
        customer_name="Ana",
        service_name="Masaje",
    )


def _rule(trigger=TriggerType.ON_BOOKING, active=True, hours=None) -> NotificationRule:
    return NotificationRule(
        id="r1", name="Test rule", trigger=trigger, active=active, hours_before=hours
    )


def _mock_tenant(rules=None):
    tenant = MagicMock()
    tenant.settings = {"notification_rules": rules} if rules is not None else {}
    return tenant


# ===========================================================================
# DOMAIN LAYER
# ===========================================================================

class TestNotificationRule(unittest.TestCase):
    def test_on_booking_trigger(self):
        r = _rule(trigger=TriggerType.ON_BOOKING)
        self.assertTrue(r.is_on_booking())
        self.assertFalse(r.is_hours_before())

    def test_hours_before_trigger(self):
        r = _rule(trigger=TriggerType.HOURS_BEFORE, hours=24)
        self.assertFalse(r.is_on_booking())
        self.assertTrue(r.is_hours_before())

    def test_from_dict(self):
        d = {"id": "x", "name": "N", "trigger": "hours_before", "active": True, "hours_before": 12}
        r = NotificationRule.from_dict(d)
        self.assertEqual(r.hours_before, 12)

    def test_from_dict_defaults(self):
        r = NotificationRule.from_dict({"id": "x"})
        self.assertFalse(r.active)

    def test_immutable(self):
        r = _rule()
        with self.assertRaises(Exception):
            r.active = False  # frozen dataclass


class TestBookingEvent(unittest.TestCase):
    def test_fire_time_for_on_booking_returns_none(self):
        b = _booking()
        r = _rule(trigger=TriggerType.ON_BOOKING)
        self.assertIsNone(b.fire_time_for_rule(r))

    def test_fire_time_for_hours_before(self):
        start = _future_dt(48)
        b = BookingEvent("t", "b", start, "+56912345678", "Ana", "Yoga")
        r = _rule(trigger=TriggerType.HOURS_BEFORE, hours=24)
        expected = start - timedelta(hours=24)
        self.assertEqual(b.fire_time_for_rule(r), expected)

    def test_fire_time_none_hours_before_is_none(self):
        b = _booking()
        r = NotificationRule("x", "n", TriggerType.HOURS_BEFORE, True, None)
        self.assertIsNone(b.fire_time_for_rule(r))


class TestMessageBuilder(unittest.TestCase):
    def test_on_booking_contains_name_and_service(self):
        b = _booking()
        r = _rule(trigger=TriggerType.ON_BOOKING)
        msg = build_message(r, b)
        self.assertIn("Ana", msg)
        self.assertIn("Masaje", msg)
        self.assertIn("confirmada", msg)

    def test_hours_before_24_label(self):
        b = _booking()
        r = _rule(trigger=TriggerType.HOURS_BEFORE, hours=24)
        msg = build_message(r, b)
        self.assertIn("1 día", msg)

    def test_hours_before_2_label(self):
        b = _booking()
        r = _rule(trigger=TriggerType.HOURS_BEFORE, hours=2)
        msg = build_message(r, b)
        self.assertIn("2 horas", msg)

    def test_hours_before_48_label(self):
        self.assertEqual(_hours_label(48), "2 días")

    def test_no_customer_name(self):
        b = BookingEvent("t", "b", _future_dt(), "+56912345678", "", "Yoga")
        r = _rule()
        msg = build_message(r, b)
        self.assertTrue(msg.startswith("Hola,"))


# ===========================================================================
# APPLICATION LAYER
# ===========================================================================

class TestScheduleNotificationsUseCase(unittest.TestCase):

    def _make_use_case(self, tenant=None, rules=None):
        repo = MagicMock()
        repo.get_by_id.return_value = tenant or _mock_tenant(rules)
        publisher = MagicMock(spec=INotificationPublisher)
        scheduler = MagicMock(spec=INotificationScheduler)
        uc = ScheduleNotificationsUseCase(
            tenant_repository=repo,
            publisher=publisher,
            scheduler=scheduler,
        )
        return uc, publisher, scheduler

    def test_on_booking_active_publishes(self):
        rules = [{"id": "on_booking", "name": "N", "trigger": "on_booking", "active": True, "hours_before": None}]
        uc, publisher, sched = self._make_use_case(rules=rules)
        uc.execute(_booking())
        publisher.publish.assert_called_once()
        sched.schedule.assert_not_called()

    def test_hours_before_active_schedules(self):
        rules = [{"id": "r24h", "name": "24h", "trigger": "hours_before", "active": True, "hours_before": 24}]
        uc, publisher, sched = self._make_use_case(rules=rules)
        uc.execute(_booking(hours_offset=48))
        sched.schedule.assert_called_once()
        publisher.publish.assert_not_called()

    def test_inactive_rule_is_skipped(self):
        rules = [{"id": "on_booking", "name": "N", "trigger": "on_booking", "active": False, "hours_before": None}]
        uc, publisher, sched = self._make_use_case(rules=rules)
        uc.execute(_booking())
        publisher.publish.assert_not_called()
        sched.schedule.assert_not_called()

    def test_past_fire_time_is_skipped(self):
        rules = [{"id": "r24h", "name": "24h", "trigger": "hours_before", "active": True, "hours_before": 24}]
        uc, publisher, sched = self._make_use_case(rules=rules)
        uc.execute(_booking(hours_offset=10))  # only 10h away, 24h window already passed
        sched.schedule.assert_not_called()

    def test_no_phone_skips_all(self):
        uc, publisher, sched = self._make_use_case()
        uc.execute(_booking(phone=""))
        publisher.publish.assert_not_called()
        sched.schedule.assert_not_called()

    def test_tenant_not_found_raises(self):
        repo = MagicMock()
        repo.get_by_id.return_value = None
        uc = ScheduleNotificationsUseCase(repo, MagicMock(), MagicMock())
        with self.assertRaises(ValueError):
            uc.execute(_booking())

    def test_default_rules_applied_when_settings_empty(self):
        """When tenant has no notification_rules, default rules should apply."""
        repo = MagicMock()
        tenant = MagicMock()
        tenant.settings = {}  # no notification_rules key
        repo.get_by_id.return_value = tenant
        publisher = MagicMock(spec=INotificationPublisher)
        sched = MagicMock(spec=INotificationScheduler)
        uc = ScheduleNotificationsUseCase(repo, publisher, sched)
        uc.execute(_booking())
        # Default has on_booking=True, so publisher should be called
        publisher.publish.assert_called_once()

    def test_multiple_rules_dispatched(self):
        rules = [
            {"id": "on_booking", "name": "N", "trigger": "on_booking", "active": True, "hours_before": None},
            {"id": "r24h", "name": "24h", "trigger": "hours_before", "active": True, "hours_before": 24},
        ]
        uc, publisher, sched = self._make_use_case(rules=rules)
        uc.execute(_booking(hours_offset=48))
        publisher.publish.assert_called_once()
        sched.schedule.assert_called_once()


# ===========================================================================
# HANDLER (record parsing)
# ===========================================================================

class TestParseRecord(unittest.TestCase):
    def test_sns_wrapped(self):
        payload = {"event_type": "BOOKING_CONFIRMED", "tenant_id": "t1"}
        record = {"body": json.dumps({"Message": json.dumps(payload)})}
        result = _parse_record(record)
        self.assertEqual(result["event_type"], "BOOKING_CONFIRMED")

    def test_raw_body(self):
        payload = {"event_type": "BOOKING_CONFIRMED"}
        record = {"body": json.dumps(payload)}
        result = _parse_record(record)
        self.assertEqual(result["event_type"], "BOOKING_CONFIRMED")

    def test_invalid_json_returns_none(self):
        self.assertIsNone(_parse_record({"body": "NOT_JSON"}))


class TestToBookingEvent(unittest.TestCase):
    def _payload(self, **overrides):
        base = {
            "event_type": "BOOKING_CONFIRMED",
            "tenant_id": "t1",
            "booking_id": "b1",
            "booking_start_time": (_future_dt()).isoformat(),
            "customer_phone": "+56912345678",
            "customer_name": "Ana",
            "service_name": "Yoga",
        }
        base.update(overrides)
        return base

    def test_valid_payload(self):
        ev = _to_booking_event(self._payload())
        self.assertIsNotNone(ev)
        self.assertEqual(ev.tenant_id, "t1")

    def test_missing_tenant_id_returns_none(self):
        self.assertIsNone(_to_booking_event(self._payload(tenant_id="")))

    def test_invalid_booking_time_returns_none(self):
        self.assertIsNone(_to_booking_event(self._payload(booking_start_time="not-a-date")))

    def test_z_suffix_parsed(self):
        ev = _to_booking_event(self._payload(booking_start_time="2025-06-15T14:00:00Z"))
        self.assertIsNotNone(ev)
        self.assertEqual(ev.booking_start_time.tzinfo, timezone.utc)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
