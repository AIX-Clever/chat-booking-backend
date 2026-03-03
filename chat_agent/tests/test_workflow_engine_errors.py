"""
Unit tests for WorkflowEngine confirmBooking error handling (Fix 6)
Validates that SlotNotAvailableError gives user-friendly options instead of raw Python error
"""
import unittest
import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

from unittest.mock import Mock
from datetime import datetime, UTC, timedelta
from shared.domain.entities import TenantId, Conversation, ConversationState, Workflow, WorkflowStep
from shared.domain.exceptions import SlotNotAvailableError, ValidationError
from chat_agent.workflow_engine import WorkflowEngine


def _make_workflow():
    """Create a minimal workflow with confirm_booking step"""
    confirm_step = WorkflowStep(
        step_id="confirm_booking",
        type="TOOL",
        content={"tool": "confirmBooking"},
        next_step="booking_success",
    )
    success_step = WorkflowStep(
        step_id="booking_success",
        type="MESSAGE",
        content={"text": "¡Reserva confirmada!"},
    )
    return Workflow(
        workflow_id="wf-test",
        tenant_id=TenantId("tenant-test"),
        name="Test Workflow",
        steps={"confirm_booking": confirm_step, "booking_success": success_step},
        is_active=True,
    )


def _make_conversation(tenant_id="tenant-test"):
    return Conversation(
        conversation_id="conv-test",
        tenant_id=TenantId(tenant_id),
        state=ConversationState.INIT,
        context={
            "serviceId": "svc-1",
            "providerId": "pro-1",
            "selectedSlot": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "clientFirstName": "Test",
            "clientLastName": "User",
            "clientEmail": "test@example.com",
            "clientPhone": "+56912345678",
            "serviceName": "Masaje",
            "providerName": "Dr. García",
        },
    )


class TestWorkflowEngineConfirmBookingErrors(unittest.TestCase):

    def _make_engine(self, booking_service):
        return WorkflowEngine(
            service_repo=Mock(),
            provider_repo=Mock(),
            faq_repo=Mock(),
            availability_repo=Mock(),
            booking_repo=Mock(),
            availability_service=Mock(),
            booking_service=booking_service,
        )

    def test_slot_not_available_gives_friendly_options(self):
        """Fix 6: SlotNotAvailableError should offer slot re-selection, NOT show raw error"""
        mock_booking_service = Mock()
        mock_booking_service.create_booking.side_effect = SlotNotAvailableError(
            "2026-03-25T10:00:00 - 2026-03-25T11:00:00"
        )

        engine = self._make_engine(mock_booking_service)
        conversation = _make_conversation()
        workflow = _make_workflow()
        step = workflow.steps["confirm_booking"]

        response = engine._execute_tool(conversation, step, workflow)

        # Should NOT expose raw Python error
        self.assertNotIn("SlotNotAvailableError", response.get("text", ""))
        # Should offer user-friendly options
        self.assertEqual(response["type"], "options")
        self.assertIn("horario", response["text"].lower())
        # Context slot should be cleared for re-selection
        self.assertIsNone(conversation.context.get("selectedSlot"))
        # Should have two options: pick again or restart
        option_values = [o["value"] for o in response.get("options", [])]
        self.assertIn("select_timeslot", option_values)
        self.assertIn("restart", option_values)

    def test_validation_error_shows_domain_message(self):
        """Fix 6: ValidationError should show the domain message, not a generic one"""
        mock_booking_service = Mock()
        mock_booking_service.create_booking.side_effect = ValidationError(
            "No se pueden crear reservas con más de 180 días de anticipación"
        )

        engine = self._make_engine(mock_booking_service)
        conversation = _make_conversation()
        workflow = _make_workflow()
        step = workflow.steps["confirm_booking"]

        response = engine._execute_tool(conversation, step, workflow)

        self.assertEqual(response["type"], "error")
        self.assertIn("180", response["text"])

    def test_generic_error_hides_internals(self):
        """Fix 6: Generic exceptions should NOT expose Python internals to the user"""
        mock_booking_service = Mock()
        mock_booking_service.create_booking.side_effect = RuntimeError(
            "DynamoDB connection timeout"
        )

        engine = self._make_engine(mock_booking_service)
        conversation = _make_conversation()
        workflow = _make_workflow()
        step = workflow.steps["confirm_booking"]

        response = engine._execute_tool(conversation, step, workflow)

        self.assertEqual(response["type"], "error")
        # Should NOT expose the raw exception message ("DynamoDB connection timeout")
        self.assertNotIn("DynamoDB", response["text"])
        # Should show a safe user-facing message
        self.assertIn("intenta", response["text"].lower())


if __name__ == "__main__":
    unittest.main()
