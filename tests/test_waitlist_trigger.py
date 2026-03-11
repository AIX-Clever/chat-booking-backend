"""
Unit Tests for Waitlist Trigger Lambda Handler

Tests cover:
- Processing CANCELLED booking events
- Ignoring non-CANCELLED events
- Ignoring INSERT events
"""

import json
import pytest
from unittest.mock import patch, MagicMock


def _make_stream_event(
    event_name, old_status, new_status,
    tenant_id="t-1", service_id="s-1", provider_id="p-1",
):
    """Helper to create DynamoDB Stream event records."""
    return {
        "Records": [
            {
                "eventName": event_name,
                "dynamodb": {
                    "OldImage": {
                        "tenantId": {"S": tenant_id},
                        "serviceId": {"S": service_id},
                        "providerId": {"S": provider_id},
                        "status": {"S": old_status},
                    },
                    "NewImage": {
                        "tenantId": {"S": tenant_id},
                        "serviceId": {"S": service_id},
                        "providerId": {"S": provider_id},
                        "status": {"S": new_status},
                    },
                },
            }
        ]
    }


@patch("waitlist_trigger.handler.sqs_client")
@patch("waitlist_trigger.handler.waitlist_service")
class TestWaitlistTriggerHandler:

    def test_process_cancelled_booking(
        self, mock_service, mock_sqs
    ):
        """Process a booking that changed to CANCELLED."""
        from waitlist_trigger.handler import handler

        candidate = MagicMock()
        candidate.client_id = "client@test.com"
        candidate.waiting_list_id = "wl-1"
        mock_service.process_cancellation.return_value = candidate

        event = _make_stream_event("MODIFY", "CONFIRMED", "CANCELLED")
        result = handler(event, None)

        body = json.loads(result["body"])
        assert body["processed"] == 1
        assert body["errors"] == 0
        mock_service.process_cancellation.assert_called_once()
        mock_service.mark_contacted.assert_called_once()

    def test_ignore_non_modify_events(
        self, mock_service, mock_sqs
    ):
        """Ignore INSERT events (new bookings)."""
        from waitlist_trigger.handler import handler

        event = _make_stream_event("INSERT", "", "CONFIRMED")
        result = handler(event, None)

        body = json.loads(result["body"])
        assert body["processed"] == 0
        mock_service.process_cancellation.assert_not_called()

    def test_ignore_non_cancelled_status(
        self, mock_service, mock_sqs
    ):
        """Ignore MODIFY events that don't result in CANCELLED."""
        from waitlist_trigger.handler import handler

        event = _make_stream_event(
            "MODIFY", "PENDING", "CONFIRMED"
        )
        result = handler(event, None)

        body = json.loads(result["body"])
        assert body["processed"] == 0
        mock_service.process_cancellation.assert_not_called()

    def test_no_candidates_available(
        self, mock_service, mock_sqs
    ):
        """Handle case where no waitlist candidates exist."""
        from waitlist_trigger.handler import handler

        mock_service.process_cancellation.return_value = None

        event = _make_stream_event("MODIFY", "CONFIRMED", "CANCELLED")
        result = handler(event, None)

        body = json.loads(result["body"])
        assert body["processed"] == 0
        assert body["errors"] == 0
