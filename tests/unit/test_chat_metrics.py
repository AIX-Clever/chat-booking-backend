
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

from shared.domain.entities import TenantId, Conversation, ConversationState
from chat_agent.service import ChatAgentService
from shared.metrics import MetricsService

class TestChatAgentMetrics(unittest.TestCase):
    def setUp(self):
        self.conversation_repo = MagicMock()
        self.service_repo = MagicMock()
        self.provider_repo = MagicMock()
        self.booking_repo = MagicMock()
        self.availability_repo = MagicMock()
        self.faq_repo = MagicMock()
        self.workflow_repo = MagicMock()
        self.tenant_repo = MagicMock()
        self.limit_service = MagicMock()
        self.metrics_service = MagicMock(spec=MetricsService)

        # Mock Workflow Engine inside service
        with patch('chat_agent.service.WorkflowEngine') as MockEngine:
            self.mock_engine = MockEngine.return_value
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
                metrics_service=self.metrics_service
            )
            # Ensure the mock engine is actually used (it's assigned in __init__)
            self.service.workflow_engine = self.mock_engine

    def test_service_selected_metric(self):
        tenant_id = TenantId("tenant1")
        conv_id = "conv1"
        
        # Initial conversation state
        conversation = MagicMock(spec=Conversation)
        conversation.conversation_id = conv_id
        conversation.state = ConversationState.SERVICE_PENDING
        conversation.workflow_id = "wf1"
        self.conversation_repo.get_by_id.return_value = conversation
        
        self.tenant_repo.get_by_id.return_value.settings = {} # AI disabled
        self.workflow_repo.get_by_id.return_value = MagicMock()

        # Mock process_step to change state
        def side_effect(conv, *args, **kwargs):
            conv.state = ConversationState.SERVICE_SELECTED
            return {"type": "text", "text": "Service selected"}
        
        self.mock_engine.process_step.side_effect = side_effect
        
        # Act
        self.service.process_message(tenant_id, conv_id, "Some text")
        
        # Assert
        self.metrics_service.increment_funnel_step.assert_called_with(
            "tenant1", "service_selected"
        )

    def test_provider_selected_metric(self):
        tenant_id = TenantId("tenant1")
        conv_id = "conv1"
        
        conversation = MagicMock(spec=Conversation)
        conversation.conversation_id = conv_id
        conversation.state = ConversationState.PROVIDER_PENDING
        conversation.workflow_id = "wf1"
        self.conversation_repo.get_by_id.return_value = conversation
        
        self.tenant_repo.get_by_id.return_value.settings = {}
        self.workflow_repo.get_by_id.return_value = MagicMock()

        def side_effect(conv, *args, **kwargs):
            conv.state = ConversationState.PROVIDER_SELECTED
            return {}
        
        self.mock_engine.process_step.side_effect = side_effect
        
        self.service.process_message(tenant_id, conv_id, "Provider X")
        
        self.metrics_service.increment_funnel_step.assert_called_with(
            "tenant1", "provider_selected"
        )

    def test_date_selected_metric(self):
        tenant_id = TenantId("tenant1")
        conv_id = "conv1"
        
        conversation = MagicMock(spec=Conversation)
        conversation.conversation_id = conv_id
        # State before slot selection usually implies provider selected
        conversation.state = ConversationState.PROVIDER_SELECTED 
        conversation.workflow_id = "wf1"
        self.conversation_repo.get_by_id.return_value = conversation
        
        self.tenant_repo.get_by_id.return_value.settings = {}
        self.workflow_repo.get_by_id.return_value = MagicMock()

        def side_effect(conv, *args, **kwargs):
            conv.state = ConversationState.SLOT_PENDING # Slot selected
            return {}
        
        self.mock_engine.process_step.side_effect = side_effect
        
        self.service.process_message(tenant_id, conv_id, "2023-10-10 10:00")
        
        self.metrics_service.increment_funnel_step.assert_called_with(
            "tenant1", "date_selected"
        )

if __name__ == '__main__':
    unittest.main()
