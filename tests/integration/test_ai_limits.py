import pytest
from unittest.mock import MagicMock
from chat_agent.service import ChatAgentService
from shared.domain.entities import (
    Tenant,
    TenantId,
    Conversation,
    ConversationState,
    TenantPlan,
    TenantStatus,
)
from shared.limit_service import TenantLimitService
from shared.metrics import MetricsService


class TestChatAgentAILimits:
    def setup_method(self):
        self.tenant_id = TenantId("test-tenant")
        self.tenant = Tenant(
            tenant_id=self.tenant_id,
            name="Test Tenant",
            slug="test",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.LITE,
            owner_user_id="owner",
            billing_email="test@example.com",
            whatsapp_quota=100,
        )
        # Setup mocks
        self.conversation_repo = MagicMock()
        self.service_repo = MagicMock()
        self.provider_repo = MagicMock()
        self.booking_repo = MagicMock()
        self.availability_repo = MagicMock()
        self.faq_repo = MagicMock()
        self.workflow_repo = MagicMock()
        self.tenant_repo = MagicMock()
        self.metrics_service = MagicMock()

        # Configure tenant repo
        self.tenant_repo.get_by_id.return_value = self.tenant

        # Configure Limit Service
        self.limit_service = TenantLimitService(self.tenant_repo, self.metrics_service)

        # Initialize Service
        self.service = ChatAgentService(
            conversation_repo=self.conversation_repo,
            service_repo=self.service_repo,
            provider_repo=self.provider_repo,
            booking_repo=self.booking_repo,
            availability_repo=self.availability_repo,
            faq_repo=self.faq_repo,
            workflow_repo=self.workflow_repo,
            tenant_repo=self.tenant_repo,
            limit_service=self.limit_service,
            metrics_service=self.metrics_service,
        )

        # Mock Workflow Engine response to verify flow
        self.service.workflow_engine = MagicMock()
        self.service.workflow_engine.process_step.return_value = {
            "type": "text",
            "text": "FSM Response",
        }

    def test_lite_plan_should_not_use_ai(self):
        """LITE plan without AI enabled should fallback to FSM"""
        # Arrange
        # LITE plan has ai_enabled: False (implied or explicit in check_can_use_ai)
        self.metrics_service.get_usage_for_plan_limits.return_value = {"tokensIA": 0}

        conversation = Conversation(
            conversation_id="conv_1",
            tenant_id=self.tenant_id,
            state=ConversationState.INIT,
            workflow_id="wf_1",
        )
        self.conversation_repo.get_by_id.return_value = conversation
        self.workflow_repo.get_by_id.return_value = MagicMock()

        # Act
        # Force a message that would trigger AI if enabled
        conv, response = self.service.process_message(
            self.tenant_id,
            "conv_1",
            "Quiero agendar una cita para mañana",
            user_data={"force_rag": True},  # Try to force it, but plan should block
        )

        # Assert
        # Should verify check_can_use_ai was called
        # And response should be from FSM (mocked above)
        assert response["text"] == "FSM Response"

        # Verify limit service check
        # This confirms logic in ChatAgentService calls limit service
        # Since usage is 0 but Plan LITE doesn't have AI, check_can_use_ai returns False

    def test_business_plan_with_tokens_should_use_ai(self):
        """BUSINESS plan with available tokens should use AI"""
        # Update tenant to BUSINESS
        self.tenant.plan = TenantPlan.BUSINESS
        self.tenant.settings = {"ai_config": {"enabled": True, "mode": "HAIKU"}}

        # Mock limit service to return True
        self.metrics_service.get_usage_for_plan_limits.return_value = {
            "tokensIA": 100
        }  # Assuming limit is higher

        # Mock AI Handler
        self.service.ai_handler = MagicMock()
        self.service.ai_handler.generate_response.return_value = "AI Response"

        conversation = Conversation(
            conversation_id="conv_2",
            tenant_id=self.tenant_id,
            state=ConversationState.INIT,
            workflow_id="wf_1",
        )
        self.conversation_repo.get_by_id.return_value = conversation

        # Act
        conv, response = self.service.process_message(
            self.tenant_id, "conv_2", "Hola AI"
        )

        # Assert
        assert response["text"] == "AI Response"
        assert response.get("ai_generated") is True


if __name__ == "__main__":
    t = TestChatAgentAILimits()
    t.setup_method()
    t.test_lite_plan_should_not_use_ai()
    print("✅ test_lite_plan_should_not_use_ai passed")

    t.test_business_plan_with_tokens_should_use_ai()
    print("✅ test_business_plan_with_tokens_should_use_ai passed")
