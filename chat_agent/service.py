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
    IWorkflowRepository,
    ITenantRepository
)
from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError
)
from shared.utils import generate_id, parse_iso_datetime
from workflow_engine import WorkflowEngine
from workflow_engine import WorkflowEngine
from fsm import ResponseBuilder
from shared.ai_handler import AIHandler
from shared.infrastructure.vector_repository import VectorRepository
import os



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
        workflow_repo: IWorkflowRepository,
        tenant_repo: ITenantRepository
    ):
        self._conversation_repo = conversation_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._booking_repo = booking_repo
        self._availability_repo = availability_repo
        self._faq_repo = faq_repo
        self._workflow_repo = workflow_repo
        self._tenant_repo = tenant_repo
        
        self.workflow_engine = WorkflowEngine(
            service_repo, provider_repo, faq_repo, availability_repo
        )

        # Initialize AI Handler if infrastructure is available
        self.ai_handler = None
        db_cluster_arn = os.environ.get('DB_ENDPOINT') # Mapped to Cluster ARN in infra
        db_secret_arn = os.environ.get('DB_SECRET_ARN')
        
        if db_cluster_arn and db_secret_arn:
            vector_repo = VectorRepository(db_cluster_arn, db_secret_arn)
            self.ai_handler = AIHandler(vector_repo)
    
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
             # Logic inlined to avoid dependencies on workflow_manager package
             active_workflow = self._create_default_workflow(tenant_id)
             self._workflow_repo.save(active_workflow)
        
        # Self-healing: Repair broken default workflow if missing critical steps
        if active_workflow.name == "Default Booking Flow" and "select_timeslot" not in active_workflow.steps:
             updated_default = self._create_default_workflow(tenant_id)
             # Preserve ID and other metadata, just update steps
             active_workflow.steps = updated_default.steps
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
        user_data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> tuple[Conversation, dict]:
        conversation = self._conversation_repo.get_by_id(tenant_id, conversation_id)
        if not conversation:
            raise EntityNotFoundError(f"Conversation not found: {conversation_id}")

        # 0. Check for AI Mode (Business/Enterprise)
        tenant = self._tenant_repo.get_by_id(tenant_id)
        if not tenant:
             raise EntityNotFoundError(f"Tenant not found: {tenant_id}")
             
        # Check settings for AI Mode
        ai_settings = tenant.settings.get('ai', {}) or {}
        ai_enabled = ai_settings.get('enabled', False)
        # Fallback to metadata for testing override if needed, but prioritize DB
        ai_mode = 'BEDROCK_RAG' if ai_enabled else None
        
        if ai_mode == 'BEDROCK_RAG' and self.ai_handler:
            # RAG FLOW
            
            # 1. Get History (Last 10 messages)
            # conversation.history is needed. Assuming conversation entity has it or we query it.
            # Only existing messages are relevant.
            
            # 2. Get Response from AI
            ai_response_text = self.ai_handler.generate_response(
                tenant_id, 
                conversation.get_history(), # Assuming get_history() exists or property
                message
            )
            
            # 3. Wrap in standard response format
            response = {
                'type': 'text',
                'text': ai_response_text,
                'ai_generated': True
            }
            
            # 4. Save User Message & AI Response to History
            conversation.add_message('user', message)
            conversation.add_message('assistant', ai_response_text)
            self._conversation_repo.save(conversation)
            
            return conversation, response

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
        from shared.domain.entities import Workflow, WorkflowStep
        
        # Hardcoded default workflow (copy of base_workflow.json)
        # Used as fallback and initial setup for self-healing
        data = {
            "name": "Default Booking Flow",
            "steps": {
                "start": {
                    "stepId": "start",
                    "type": "DYNAMIC_OPTIONS",
                    "content": {
                        "text": "¡Hola! 👋 Soy Lucia. Bienvenido. ¿En qué te puedo ayudar hoy?",
                        "sources": ["SERVICES", "PROVIDERS", "FAQS"],
                        "options_mapping": {
                            "SERVICES": {"label": "Reservar Servicio", "value": "flow_booking", "next": "search_service"},
                            "PROVIDERS": {"label": "Ver Profesionales", "value": "flow_providers", "next": "list_providers"},
                            "FAQS": {"label": "Preguntas Frecuentes", "value": "flow_faqs", "next": "show_faqs"}
                        },
                        "empty_text": "No hay servicios disponibles por el momento."
                    }
                },
                "search_service": {
                    "stepId": "search_service",
                    "type": "TOOL",
                    "content": {"tool": "searchServices"},
                    "next": "list_providers"
                },
                "list_providers": {
                    "stepId": "list_providers",
                    "type": "TOOL",
                    "content": {"tool": "listProviders"},
                    "next": "select_timeslot"
                },
                "select_timeslot": {
                    "stepId": "select_timeslot",
                    "type": "TOOL",
                    "content": {"tool": "checkAvailability"},
                    "next": "confirm_booking"
                },
                "confirm_booking": {
                    "stepId": "confirm_booking",
                    "type": "MESSAGE",
                    "content": {"text": "¡Perfecto! Funcionalidad de confirmación en desarrollo. Aquí termina el demo por ahora."}
                },
                "show_faqs": {
                    "stepId": "show_faqs",
                    "type": "TOOL",
                    "content": {"tool": "showFAQs"}
                }
            }
        }
            
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


