"""Unit tests for whatsapp_scheduler Lambda handler."""
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_event(payload: dict) -> dict:
    """Wrap a payload in an SNS-style record as whatsapp_scheduler expects."""
    return {
        "Records": [
            {"body": json.dumps({"Message": json.dumps(payload)})}
        ]
    }


def _booking_payload(
    tenant_id="tenant-1",
    event_type="BOOKING_CONFIRMED",
    hours_offset=48,
    customer_phone="+56912345678",
    customer_name="Carlos",
    service_name="Consulta General",
):
    start = datetime.now(timezone.utc) + timedelta(hours=hours_offset)
    return {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "booking_id": "booking-abc",
        "booking_start_time": start.isoformat(),
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "service_name": service_name,
    }


def _make_tenant(rules=None):
    tenant = MagicMock()
    tenant.tenant_id.value = "tenant-1"
    tenant.settings = {"notification_rules": rules} if rules is not None else {}
    return tenant


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseRecord(unittest.TestCase):
    def test_parse_sns_wrapped_record(self):
        from backend.whatsapp_scheduler.handler import _parse_record
        payload = {"event_type": "BOOKING_CONFIRMED", "tenant_id": "t1"}
        record = {"body": json.dumps({"Message": json.dumps(payload)})}
        result = _parse_record(record)
        self.assertEqual(result["event_type"], "BOOKING_CONFIRMED")

    def test_parse_raw_record(self):
        from backend.whatsapp_scheduler.handler import _parse_record
        payload = {"event_type": "BOOKING_CONFIRMED"}
        record = {"body": json.dumps(payload)}
        result = _parse_record(record)
        self.assertEqual(result["event_type"], "BOOKING_CONFIRMED")

    def test_parse_invalid_json_returns_none(self):
        from backend.whatsapp_scheduler.handler import _parse_record
        record = {"body": "NOT_JSON"}
        result = _parse_record(record)
        self.assertIsNone(result)


class TestParseIso(unittest.TestCase):
    def test_valid_utc_z(self):
        from backend.whatsapp_scheduler.handler import _parse_iso
        result = _parse_iso("2025-06-15T14:00:00Z")
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_valid_offset(self):
        from backend.whatsapp_scheduler.handler import _parse_iso
        result = _parse_iso("2025-06-15T11:00:00-03:00")
        self.assertIsNotNone(result)

    def test_invalid_returns_none(self):
        from backend.whatsapp_scheduler.handler import _parse_iso
        self.assertIsNone(_parse_iso("not-a-date"))


class TestBuildMessage(unittest.TestCase):
    def test_on_booking_message(self):
        from backend.whatsapp_scheduler.handler import _build_message
        rule = {"trigger": "on_booking"}
        dt = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
        msg = _build_message(rule, "Ana", "Masaje", dt)
        self.assertIn("Ana", msg)
        self.assertIn("Masaje", msg)
        self.assertIn("confirmada", msg)

    def test_hours_before_24(self):
        from backend.whatsapp_scheduler.handler import _build_message
        rule = {"trigger": "hours_before", "hours_before": 24}
        dt = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
        msg = _build_message(rule, "Juan", "Yoga", dt)
        self.assertIn("Juan", msg)
        self.assertIn("Yoga", msg)

    def test_hours_before_2(self):
        from backend.whatsapp_scheduler.handler import _build_message
        rule = {"trigger": "hours_before", "hours_before": 2}
        dt = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
        msg = _build_message(rule, "Laura", "Pilates", dt)
        self.assertIn("2 hora(s)", msg)

    def test_no_customer_name(self):
        from backend.whatsapp_scheduler.handler import _build_message
        rule = {"trigger": "on_booking"}
        dt = datetime(2025, 6, 15, 14, 0, tzinfo=timezone.utc)
        msg = _build_message(rule, "", "Consulta", dt)
        self.assertTrue(msg.startswith("Hola,"))


class TestLambdaHandler(unittest.TestCase):
    @patch("backend.whatsapp_scheduler.handler.sns_client")
    @patch("backend.whatsapp_scheduler.handler.scheduler_client")
    @patch("backend.whatsapp_scheduler.handler.tenant_repo")
    def test_handler_skips_non_booking_confirmed(self, mock_repo, mock_sched, mock_sns):
        from backend.whatsapp_scheduler.handler import lambda_handler
        event = _make_event({"event_type": "SOME_OTHER_EVENT", "tenant_id": "t1"})
        result = lambda_handler(event, {})
        self.assertEqual(result["processed"], 0)
        mock_sns.publish.assert_not_called()

    @patch("backend.whatsapp_scheduler.handler.sns_client")
    @patch("backend.whatsapp_scheduler.handler.scheduler_client")
    @patch("backend.whatsapp_scheduler.handler.tenant_repo")
    def test_handler_returns_zero_for_tenant_not_found(self, mock_repo, mock_sched, mock_sns):
        from backend.whatsapp_scheduler.handler import lambda_handler
        mock_repo.get_by_id.return_value = None
        event = _make_event(_booking_payload())
        result = lambda_handler(event, {})
        # Processed = 1 (record was processed), but internally skipped due to missing tenant
        self.assertEqual(result["errors"], 0)
        mock_sns.publish.assert_not_called()

    @patch("backend.whatsapp_scheduler.handler.sns_client")
    @patch("backend.whatsapp_scheduler.handler.scheduler_client")
    @patch("backend.whatsapp_scheduler.handler.tenant_repo")
    def test_on_booking_rule_publishes_to_sns(self, mock_repo, mock_sched, mock_sns):
        from backend.whatsapp_scheduler.handler import lambda_handler
        rules = [
            {"id": "on_booking", "name": "Confirmación", "trigger": "on_booking", "active": True, "hours_before": None},
        ]
        mock_repo.get_by_id.return_value = _make_tenant(rules)
        event = _make_event(_booking_payload())
        result = lambda_handler(event, {})
        self.assertEqual(result["processed"], 1)
        mock_sns.publish.assert_called_once()

    @patch("backend.whatsapp_scheduler.handler.sns_client")
    @patch("backend.whatsapp_scheduler.handler.scheduler_client")
    @patch("backend.whatsapp_scheduler.handler.tenant_repo")
    def test_hours_before_rule_creates_schedule(self, mock_repo, mock_sched, mock_sns):
        from backend.whatsapp_scheduler.handler import lambda_handler
        rules = [
            {"id": "remind_24h", "name": "24h", "trigger": "hours_before", "active": True, "hours_before": 24},
        ]
        mock_repo.get_by_id.return_value = _make_tenant(rules)
        event = _make_event(_booking_payload(hours_offset=48))  # booking 48h from now
        result = lambda_handler(event, {})
        self.assertEqual(result["processed"], 1)
        mock_sched.create_schedule.assert_called_once()
        mock_sns.publish.assert_not_called()

    @patch("backend.whatsapp_scheduler.handler.sns_client")
    @patch("backend.whatsapp_scheduler.handler.scheduler_client")
    @patch("backend.whatsapp_scheduler.handler.tenant_repo")
    def test_past_schedule_is_skipped(self, mock_repo, mock_sched, mock_sns):
        from backend.whatsapp_scheduler.handler import lambda_handler
        rules = [
            {"id": "remind_24h", "name": "24h", "trigger": "hours_before", "active": True, "hours_before": 24},
        ]
        mock_repo.get_by_id.return_value = _make_tenant(rules)
        # booking is only 10 hours from now, but rule wants 24h before = already past
        event = _make_event(_booking_payload(hours_offset=10))
        result = lambda_handler(event, {})
        self.assertEqual(result["processed"], 1)
        mock_sched.create_schedule.assert_not_called()

    @patch("backend.whatsapp_scheduler.handler.sns_client")
    @patch("backend.whatsapp_scheduler.handler.scheduler_client")
    @patch("backend.whatsapp_scheduler.handler.tenant_repo")
    def test_inactive_rule_is_skipped(self, mock_repo, mock_sched, mock_sns):
        from backend.whatsapp_scheduler.handler import lambda_handler
        rules = [
            {"id": "on_booking", "name": "Confirmación", "trigger": "on_booking", "active": False, "hours_before": None},
        ]
        mock_repo.get_by_id.return_value = _make_tenant(rules)
        event = _make_event(_booking_payload())
        result = lambda_handler(event, {})
        mock_sns.publish.assert_not_called()
        mock_sched.create_schedule.assert_not_called()

    @patch("backend.whatsapp_scheduler.handler.sns_client")
    @patch("backend.whatsapp_scheduler.handler.scheduler_client")
    @patch("backend.whatsapp_scheduler.handler.tenant_repo")
    def test_no_phone_skips_dispatch(self, mock_repo, mock_sched, mock_sns):
        from backend.whatsapp_scheduler.handler import lambda_handler
        mock_repo.get_by_id.return_value = _make_tenant()
        event = _make_event(_booking_payload(customer_phone=""))
        result = lambda_handler(event, {})
        mock_sns.publish.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
