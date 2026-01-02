import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from chat_agent.service import ChatAgentService
from chat_agent.workflow_engine import WorkflowEngine
from shared.domain.entities import (
    Conversation, ConversationState, TenantId, Workflow, WorkflowStep, 
    Service, Provider, ProviderAvailability, TimeRange
)

class TestFSMBasicFlow(unittest.TestCase):
    def setUp(self):
        # Mocks
        self.conversation_repo = MagicMock()
        self.service_repo = MagicMock()
        self.provider_repo = MagicMock()
        self.booking_repo = MagicMock()
        self.availability_repo = MagicMock()
        self.faq_repo = MagicMock()
        self.workflow_repo = MagicMock()
        self.tenant_repo = MagicMock()
        
        # Setup Service
        self.service = ChatAgentService(
            self.conversation_repo,
            self.service_repo,
            self.provider_repo,
            self.booking_repo,
            self.availability_repo,
            self.faq_repo,
            self.workflow_repo,
            self.tenant_repo
        )
        
        # Mock AI Handler to fail (forcing FSM)
        self.service.ai_handler = MagicMock()
        self.service.ai_handler.generate_response.side_effect = Exception("AI Offline")
        
        # Mock Data
        self.tenant_id = TenantId("tenant-123")
        self.service_repo.list_by_tenant.return_value = [
            Service(
                service_id="svc-1", 
                tenant_id=self.tenant_id, 
                name="Corte de Pelo", 
                description="Corte clasico", # Added description
                category="Hair", 
                duration_minutes=30, 
                price=100
            )
        ]
        self.provider_repo.list_by_tenant.return_value = [
            Provider(
                provider_id="prov-1", 
                tenant_id=self.tenant_id, 
                name="Juan", 
                bio="Expert", # Added bio
                timezone="America/Santiago", 
                service_ids=["svc-1"]
            )
        ]
        
        # Mock Workflow with separate paths
        self.workflow = Workflow(
            workflow_id="wf-default",
            tenant_id=self.tenant_id,
            name="Default Booking Flow",
            steps={
                "start": WorkflowStep(step_id="start", type="DYNAMIC_OPTIONS", content={
                    "text": "Hola", 
                    "options_mapping": {
                        "SERVICES": {"value": "flow_booking", "next": "search_service"},
                        "PROVIDERS": {"value": "flow_providers", "next": "list_providers_all"},
                        "FAQS": {"value": "flow_faqs", "next": "show_faqs"}
                    }
                }),
                
                # Service Flow
                "search_service": WorkflowStep(step_id="search_service", type="TOOL", content={"tool": "searchServices"}, next_step="list_providers_filtered"),
                "list_providers_filtered": WorkflowStep(step_id="list_providers_filtered", type="TOOL", content={"tool": "listProviders"}, next_step="select_timeslot"),
                
                # Provider Flow
                "list_providers_all": WorkflowStep(step_id="list_providers_all", type="TOOL", content={"tool": "listProviders"}, next_step="select_service_for_provider"),
                "select_service_for_provider": WorkflowStep(step_id="select_service_for_provider", type="TOOL", content={"tool": "searchServices"}, next_step="select_timeslot"),
                
                # Common
                "select_timeslot": WorkflowStep(step_id="select_timeslot", type="TOOL", content={"tool": "checkAvailability"}, next_step="request_contact_info"),
                "request_contact_info": WorkflowStep(step_id="request_contact_info", type="MESSAGE", content={"text": "Datos?"}, next_step="collect_contact_info"),
                "collect_contact_info": WorkflowStep(step_id="collect_contact_info", type="TOOL", content={"tool": "collectContactInfo"}, next_step="confirm_booking"),
                "confirm_booking": WorkflowStep(step_id="confirm_booking", type="TOOL", content={"tool": "confirmBooking"}, next_step="booking_success"),
                "booking_success": WorkflowStep(step_id="booking_success", type="MESSAGE", content={"text": "Exito"}),
                
                # FAQ Flow
                "show_faqs": WorkflowStep(step_id="show_faqs", type="TOOL", content={"tool": "showFAQs"})
            }
        )
        self.workflow_repo.list_by_tenant.return_value = [self.workflow]
        self.workflow_repo.get_by_id.return_value = self.workflow
        
    def test_service_flow(self):
        """Test Start -> Service -> Provider -> Slot -> Confirm"""
        # ... (Existing test logic adapted to new step names)
        pass

    def test_provider_flow(self):
        """Test Start -> Provider -> Service -> Slot -> Confirm"""
        pass

    def test_faq_flow(self):
        """Test Start -> FAQ"""
        pass
        
    def test_service_flow(self):
        print("\n--- Testing Service Flow ---")
        # 1. Start
        conv, resp = self.service.start_conversation(self.tenant_id)
        
        # 2. Select Service Flow
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Quiero reservar", "text", {"value": "flow_booking"})
        self.assertEqual(conv.current_step_id, "search_service")
        
        # 3. Select Service
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Corte", "text", {"value": "svc-1"})
        self.assertEqual(conv.context['serviceId'], "svc-1")
        self.assertEqual(conv.current_step_id, "list_providers_filtered")
        
        # 4. Select Provider
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Juan", "text", {"value": "prov-1"})
        self.assertEqual(conv.context['providerId'], "prov-1")
        self.assertEqual(conv.current_step_id, "select_timeslot")
        
        # 5. Select Slot
        slot_iso = "2025-01-01T10:00:00"
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "10am", "text", {"value": slot_iso})
        self.assertEqual(conv.context['selectedSlot'], slot_iso)
        
        # 6. Contact & Confirm
        contact_data = {"clientName": "Test", "clientEmail": "test@test.com", "clientPhone": "12345678"} # added phone
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Mis datos", "text", contact_data)
        
        self.assertEqual(self.booking_repo.save.call_count, 1)

    def test_provider_flow(self):
        print("\n--- Testing Provider Flow ---")
        # 1. Start
        conv, resp = self.service.start_conversation(self.tenant_id)
        
        # 2. Select Provider Flow
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Profesionales", "text", {"value": "flow_providers"})
        self.assertEqual(conv.current_step_id, "list_providers_all")
        
        # 3. Select Provider
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Juan", "text", {"value": "prov-1"})
        self.assertEqual(conv.context['providerId'], "prov-1")
        # Should ask for Service now
        self.assertEqual(conv.current_step_id, "select_service_for_provider")
        
        # 4. Select Service
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Corte", "text", {"value": "svc-1"})
        self.assertEqual(conv.context['serviceId'], "svc-1")
        self.assertEqual(conv.current_step_id, "select_timeslot")
        
        # 5. Slot & Confirm... (Same as above)
        slot_iso = "2025-01-01T10:00:00"
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "10am", "text", {"value": slot_iso})
        contact_data = {"clientName": "Test", "clientEmail": "test@test.com", "clientPhone": "12345678"} # added phone
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Mis datos", "text", contact_data)
        
        self.assertEqual(self.booking_repo.save.call_count, 2) # Total calls in suite
        
    def test_faq_flow(self):
        print("\n--- Testing FAQ Flow ---")
        # Mock FAQs
        from shared.domain.entities import FAQ
        self.faq_repo.list_by_tenant.return_value = [FAQ(faq_id="f1", tenant_id=self.tenant_id, question="Q?", answer="A", category="General")]

        # 1. Start
        conv, resp = self.service.start_conversation(self.tenant_id)
        
        # 2. Select FAQS
        conv, resp = self.service.process_message(self.tenant_id, conv.conversation_id, "Preguntas", "text", {"value": "flow_faqs"})
        
        self.assertEqual(conv.current_step_id, "show_faqs")
        self.assertIn("A", resp['text'])

if __name__ == '__main__':
    unittest.main()
