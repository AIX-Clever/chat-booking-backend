
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from shared.domain.entities import Conversation, Workflow, WorkflowStep, TenantId
from shared.domain.exceptions import ValidationError
from fsm import ResponseBuilder

class WorkflowEngine:
    """
    Executes dynamic workflows defined in JSON.
    Replaces the hardcoded FSM logic.
    """

    def __init__(self, service_repo, provider_repo, faq_repo):
        self.service_repo = service_repo
        self.provider_repo = provider_repo
        self.faq_repo = faq_repo

    def process_step(
        self, 
        conversation: Conversation, 
        workflow: Workflow, 
        user_input: str,
        user_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process the current step or transition to the next one based on input.
        """
        current_step_id = conversation.current_step_id
        
        # If no step, start at 'start' (or whatever is first)
        if not current_step_id:
            current_step_id = 'start'
            conversation.current_step_id = current_step_id
            return self._execute_step(conversation, workflow, current_step_id)

        current_step = workflow.steps.get(current_step_id)
        if not current_step:
            # Fallback or error
            return ResponseBuilder.error_message(f"Step {current_step_id} not found")

        # 1. Handle Input for CURRENT step (if it was waiting for input)
        # e.g. if we are in a QUESTION step, we check the answer
        
        next_step_id = None
        
        if current_step.type == 'QUESTION':
            next_step_id = self._handle_question_input(current_step, user_input, user_data, conversation)
        elif current_step.type == 'DYNAMIC_OPTIONS':
            next_step_id = self._handle_dynamic_options_input(current_step, user_input, user_data, conversation)
        else:
            # For types that don't wait for input (like MESSAGE), we should have auto-advanced.
            # If we are here, it means we probably sent a message and now user replied.
            # We usually just move to 'next' if defined, or stay here if no next.
            if current_step.next_step:
                next_step_id = current_step.next_step

        if next_step_id:
            conversation.current_step_id = next_step_id
            return self._execute_step(conversation, workflow, next_step_id)
            
        # If no transition, re-execute current step (e.g. invalid input)
        # Or if we just finished a leaf step.
        return self._execute_step(conversation, workflow, current_step_id)


    def _execute_step(self, conversation: Conversation, workflow: Workflow, step_id: str) -> Dict[str, Any]:
        """
        Execute the logic for a specific step (generate response/action)
        """
        step = workflow.steps.get(step_id)
        if not step:
            return ResponseBuilder.error_message("Flow Error: Step needed")

        if step.type == 'MESSAGE':
            # Send message and optionally auto-advance
            # If next_step is present, we might want to recurse immediately depending on UI
            # For chat, usually valid to send text and wait, OR send text and immediately process next logic
            # Simplification: Return text, if next exists, frontend/user triggers next? 
            # Actually, standard chatbot: send msg, wait for user. 
            # UNLESS it's a structural node. 
            return {
                'type': 'text',
                'text': step.content.get('text', '')
            }

        elif step.type == 'QUESTION':
            return {
                'type': step.content.get('ui_type', 'text'), # text, options, form
                'text': step.content.get('text', ''),
                'options': step.content.get('options', [])
            }

        elif step.type == 'DYNAMIC_OPTIONS':
            return self._generate_dynamic_options(conversation, step)
            
        elif step.type == 'TOOL':
            return self._execute_tool(conversation, step, workflow)

        return ResponseBuilder.error_message(f"Unknown step type: {step.type}")


    def _generate_dynamic_options(self, conversation: Conversation, step: WorkflowStep) -> Dict[str, Any]:
        """
        Check DB for Services, Providers, FAQs and build options
        """
        sources = step.content.get('sources', [])
        mapping = step.content.get('options_mapping', {})
        
        options = []
        
        # Check Services
        if 'SERVICES' in sources and self.service_repo.list_by_tenant(conversation.tenant_id):
            svc_map = mapping.get('SERVICES', {})
            options.append({
                'label': svc_map.get('label', 'Services'),
                'value': svc_map.get('value', 'flow_services')
            })

        # Check Providers
        if 'PROVIDERS' in sources and self.provider_repo.list_by_tenant(conversation.tenant_id):
            prov_map = mapping.get('PROVIDERS', {})
            options.append({
                'label': prov_map.get('label', 'Providers'),
                'value': prov_map.get('value', 'flow_providers')
            })
            
        # Check FAQs
        if 'FAQS' in sources and self.faq_repo.list_by_tenant(conversation.tenant_id):
            faq_map = mapping.get('FAQS', {})
            options.append({
                'label': faq_map.get('label', 'FAQs'),
                'value': faq_map.get('value', 'flow_faqs')
            })

        if not options:
            # Fallback if nothing available
            if step.next_step:
                 # Skip to next if no options?
                 pass 
            return {
                'type': 'text',
                'text': step.content.get('empty_text', 'No options available.')
            }

        return {
            'type': 'options',
            'text': step.content.get('text', 'Select an option:'),
            'options': options
        }

    def _handle_question_input(self, step, user_input, user_data, conversation):
        # Check validity (regex, options match)
        options = step.content.get('options', [])
        
        # If options defined, check match
        if options:
            # Check user_data value or text match
            val = user_data.get('value') if user_data else None
            
            # Find matching option
            selected = None
            if val:
                selected = next((o for o in options if o['value'] == val), None)
            
            if not selected and user_input:
                # Fuzzy match text
                 selected = next((o for o in options if o['label'].lower() in user_input.lower()), None)
            
            if selected:
                # Store selection in context
                if 'save_as' in step.content:
                    key = step.content['save_as']
                    conversation.context[key] = selected['value']
                
                return selected.get('next', step.next_step)
        
        # Free text input
        # Store validation logic here...
        
        return step.next_step


    def _handle_dynamic_options_input(self, step, user_input, user_data, conversation):
        mapping = step.content.get('options_mapping', {})
        
        # User selected a value like 'flow_booking'
        val = user_data.get('value') if user_data else user_input
        
        # Find which source this maps to
        for source, config in mapping.items():
            if config.get('value') == val:
                return config.get('next')
                
        return None # Invalid selection

    def _execute_tool(self, conversation, step, workflow):
        tool_name = step.content.get('tool')
        
        if tool_name == 'searchServices':
            # This would be similar to _handle_service_selection logic
            # For MVP, assume it returns a list of services or transitions
            # If tool returns data, we might need an intermediate step 
            # OR the tool returns the next step id directly?
            pass
            
        return ResponseBuilder.error_message(f"Tool {tool_name} not implemented")

