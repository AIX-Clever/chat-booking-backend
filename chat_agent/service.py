"""
Chat Agent Application Service (Application Layer)

Orchestrates conversational booking flow using FSM
"""

from datetime import datetime, timedelta, UTC
from typing import Optional, Dict, Any

from shared.domain.entities import (
    TenantId,
    Conversation,
    ConversationState,
    Booking,
    BookingStatus,
    CustomerInfo
)
from shared.domain.repositories import (
    IConversationRepository,
    IServiceRepository,
    IProviderRepository,
    IBookingRepository,
    IAvailabilityRepository,
    IFAQRepository,
    IWorkflowRepository
)
from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError
)
from shared.utils import generate_id, parse_iso_datetime
from .workflow_engine import WorkflowEngine
from fsm import ResponseBuilder


class ChatAgentService:
    """
    Service for managing conversational booking flow using WorkflowEngine
    """
    
    def __init__(
        self,
        conversation_repo: IConversationRepository,
        service_repo: IServiceRepository,
        provider_repo: IProviderRepository,
        booking_repo: IBookingRepository,
        availability_repo: IAvailabilityRepository,
        faq_repo: IFAQRepository,
        workflow_repo: IWorkflowRepository
    ):
        self._conversation_repo = conversation_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._booking_repo = booking_repo
        self._availability_repo = availability_repo
        self._faq_repo = faq_repo
        self._workflow_repo = workflow_repo
        
        self.workflow_engine = WorkflowEngine(
            service_repo, provider_repo, faq_repo
        )
    
    def start_conversation(
        self,
        tenant_id: TenantId,
        channel: str = 'widget',
        metadata: Optional[Dict[str, Any]] = None
    ) -> tuple[Conversation, dict]:
        conversation_id = generate_id('conv')
        
        # 1. Load active workflow for tenant
        workflows = self._workflow_repo.list_by_tenant(tenant_id)
        active_workflow = next((w for w in workflows if w.is_active), None)
        
        if not active_workflow:
             # Legacy/Migration: Create default workflow for existing tenant
             # This ensures functionality for tenants created before this update
             from workflow_manager.base_workflow import create_default_workflow_entity # We need to move logic to a shared place or inline it
             # Inline logic for now to avoid complexity, reusing what we know about base_workflow
             # Actually, better to define a helper in utils or directly here
             active_workflow = self._create_default_workflow(tenant_id)
             self._workflow_repo.save(active_workflow)

        # 2. Initialize Conversation
        conversation = Conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            state=ConversationState.INIT,
            workflow_id=active_workflow.workflow_id
        )
        
        self._conversation_repo.save(conversation)
        
        # 3. Execute first step
        response = self.workflow_engine.process_step(
            conversation, active_workflow, "start"
        )
        
        self._conversation_repo.save(conversation)
        
        return conversation, response

    def process_message(
        self,
        tenant_id: TenantId,
        conversation_id: str,
        message: str,
        message_type: str = 'text',
        user_data: Optional[Dict[str, Any]] = None
    ) -> tuple[Conversation, dict]:
        conversation = self._conversation_repo.get_by_id(tenant_id, conversation_id)
        if not conversation:
            raise EntityNotFoundError(f"Conversation not found: {conversation_id}")
            
        if not conversation.workflow_id:
            # Legacy conversation or broken state
            return self._fallback_process(tenant_id, conversation, message, user_data)
            
        workflow = self._workflow_repo.get_by_id(tenant_id, conversation.workflow_id)
        if not workflow:
             return conversation, ResponseBuilder.error_message("Workflow active not found")

        # Global Intent Detection (Greeting / Reset)
        if message and message_type == 'text':
             normalized = message.lower().strip()
             if normalized in ['hola', 'buenos dias', 'buenas tardes', 'inicio', 'menu']:
                 # Reset to start/menu
                 response = self.workflow_engine.process_step(
                     conversation, workflow, "start" # Or "initial_menu" if we want to skip hello
                 )
                 self._conversation_repo.save(conversation)
                 return conversation, response

        # Process Step
        response = self.workflow_engine.process_step(
            conversation, workflow, message, user_data
        )
        
        conversation.updated_at = datetime.now(UTC)
        self._conversation_repo.save(conversation)
        
        return conversation, response

    def _fallback_start(self, tenant_id, conversation_id):
        # ... logic for when no workflow exists ...
        # For now return error or simple message
        conversation = Conversation(conversation_id=conversation_id, tenant_id=tenant_id, state=ConversationState.INIT)
        self._conversation_repo.save(conversation)
        return conversation, {'type': 'text', 'text': 'System Error: No workflow configured.'}

    def _fallback_process(self, tenant_id, conversation, message, user_data):
         return conversation, {'type': 'text', 'text': 'Legacy conversation not supported in v2 engine.'}

    # ... Keep confirm_booking as it might be used by a TOOL ...
    def confirm_booking(self, tenant_id, conversation_id):
         # This logic should be moved to a TOOL execution inside WorkflowEngine ideally
         # But for now we might keep it accessible
         pass

    def _create_default_workflow(self, tenant_id: TenantId):
        import json
        import os
        from shared.domain.entities import Workflow, WorkflowStep
        
        try:
            # Assume file is adjacent or accessible relative to CWD in Lambda
            # In Lambda, CWD is defined. But safer to find relative to file.
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(base_path, 'workflow_manager', 'base_workflow.json')
            
            with open(file_path, 'r') as f:
                data = json.load(f)
                
            steps = {}
            for sid, content in data['steps'].items():
                steps[sid] = WorkflowStep(
                    step_id=content['stepId'],
                    type=content['type'],
                    content=content.get('content', {}),
                    next_step=content.get('next')
                )
                
            return Workflow(
                workflow_id=generate_id('wf'),
                tenant_id=tenant_id,
                name=data.get('name', 'Default Workflow'),
                description="Auto-generated default workflow",
                steps=steps,
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )
        except Exception as e:
            # Fallback hardcoded if file fails
            from shared.domain.entities import WorkflowStep
            steps = {
                 "start": WorkflowStep("start", "MESSAGE", {"text": "Hola! (Fallback)"})
            }
            return Workflow(generate_id('wf'), tenant_id, "Fallback", "", steps, True, datetime.now(UTC), datetime.now(UTC))


