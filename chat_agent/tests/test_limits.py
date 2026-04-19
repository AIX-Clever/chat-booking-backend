import pytest
from unittest.mock import Mock, MagicMock
from chat_agent.service import ChatAgentService
from shared.domain.entities import TenantId, Conversation, ConversationState, Tenant
from shared.limit_service import TenantLimitService
from shared.metrics import MetricsService


class TestChatAgentLimits:
    def test_message_limit_exceeded(self):
        """Test blocking message when limit exceeded"""
        # Mocks
        conversation_repo = Mock()
        limit_service = Mock(spec=TenantLimitService)
        # Mock limit service to return False (limit exceeded)
        limit_service.check_can_send_message.return_value = False

        service = ChatAgentService(
            conversation_repo=conversation_repo,
            service_repo=Mock(),
            provider_repo=Mock(),
            booking_repo=Mock(),
            availability_repo=Mock(),
            faq_repo=Mock(),
            workflow_repo=Mock(),
            tenant_repo=Mock(),
            limit_service=limit_service,
        )

        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("tenant_123"),
            state=ConversationState.INIT,
        )
        conversation_repo.get_by_id.return_value = conversation

        # Execute
        conv, response = service.process_message(
            TenantId("tenant_123"), "conv_123", "Hello"
        )

        # Assert
        assert response["type"] == "error"  # or whatever error type is defined
        assert "límite de mensajes" in response["text"]
        limit_service.check_can_send_message.assert_called_once()

    def test_ai_limit_fallback_to_fsm(self):
        """Test fallback to FSM when AI limit exceeded"""
        # Mocks
        conversation_repo = Mock()
        tenant_repo = Mock()
        limit_service = Mock(spec=TenantLimitService)

        # Scenario: AI is enabled in settings, BUT limit service says NO
        limit_service.check_can_use_ai.return_value = False

        tenant = Mock(spec=Tenant)
        tenant.settings = {"ai_config": {"enabled": True, "mode": "HAIKU"}}
        tenant_repo.get_by_id.return_value = tenant

        service = ChatAgentService(
            conversation_repo=conversation_repo,
            service_repo=Mock(),
            provider_repo=Mock(),
            booking_repo=Mock(),
            availability_repo=Mock(),
            faq_repo=Mock(),
            workflow_repo=Mock(),
            tenant_repo=tenant_repo,
            limit_service=limit_service,
        )

        # We need to mock workflow_repo to return a workflow so it doesn't fail later
        workflow = Mock()
        service._workflow_repo.get_by_id.return_value = workflow
        # Mock workflow engine to return a dummy response so we know it reached FSM
        service.workflow_engine.process_step = Mock(
            return_value={"type": "text", "text": "FSM Response"}
        )

        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("tenant_123"),
            state=ConversationState.INIT,
            workflow_id="wf_123",
        )
        conversation_repo.get_by_id.return_value = conversation

        # Execute
        conv, response = service.process_message(
            TenantId("tenant_123"), "conv_123", "Hello AI"
        )

        # Assert
        # Should have called check_can_use_ai
        limit_service.check_can_use_ai.assert_called_once()
        # Should have used FSM (because we mocked workflow_engine response)
        assert response["text"] == "FSM Response"
