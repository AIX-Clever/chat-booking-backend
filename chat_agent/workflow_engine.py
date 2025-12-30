
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC, timedelta
from shared.domain.entities import Conversation, Workflow, WorkflowStep, TenantId, Booking, BookingStatus, CustomerInfo
from shared.domain.exceptions import ValidationError
from shared.utils import generate_id
from fsm import ResponseBuilder

class WorkflowEngine:
    """
    Executes dynamic workflows defined in JSON.
    Replaces the hardcoded FSM logic.
    """

    def __init__(self, service_repo, provider_repo, faq_repo, availability_repo, booking_repo):
        self.service_repo = service_repo
        self.provider_repo = provider_repo
        self.faq_repo = faq_repo
        self.availability_repo = availability_repo
        self.booking_repo = booking_repo

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
        elif current_step.type == 'TOOL':
             # Try to handle input for the tool (e.g. selection)
             # If it returns a next_step_id, it means we consumed the input successfully
             next_step_id = self._handle_tool_input(current_step, user_input, user_data, conversation, workflow)
             
             # If no input matching happened, check if we should just auto-advance (e.g. invalid input but flow forces move)
             # But generally for selection tools we want to stay until valid selection
             if not next_step_id and current_step.next_step and not user_input:
                  # Only auto-advance if NO input was provided (e.g. just landing on step)
                  # But process_step is usually called WITH input.
                  # Logic refinement:
                  # If we are here, it means we are "in" the tool step and user replied.
                  # If _handle_tool_input returned None, it means invalid selection.
                  # We should probably return error/retry or re-render tool.
                  pass
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
            if step.next_step:
                conversation.current_step_id = step.next_step
            
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

    def _handle_tool_input(self, step, user_input, user_data, conversation, workflow):
        tool_name = step.content.get('tool')
        
        # Helper for fuzzy match
        def is_match(text, target):
            return target.lower() in text.lower() or text.lower() in target.lower()

        if tool_name == 'searchServices':
            # Expecting logic: User selects a service
            services = self.service_repo.list_by_tenant(conversation.tenant_id)
            active_services = [s for s in services if s.active]
            
            # 1. Check direct value (if structured input)
            val = user_data.get('value') if user_data else None
            # Some widgets send "service_id" or similar? Assuming "value" holds ID if clicked.
            
            selected_service = None
            
            if val:
                 selected_service = next((s for s in active_services if s.service_id == val), None)
            
            if not selected_service and user_input:
                 # Fuzzy match name
                 # Remove common prefixes like "Selecciono: "
                 clean_input = user_input.replace("Selecciono:", "").strip()
                 selected_service = next((s for s in active_services if is_match(clean_input, s.name)), None)
            
            if selected_service:
                conversation.context['serviceId'] = selected_service.service_id
                conversation.context['serviceName'] = selected_service.name
                return step.next_step
                
        elif tool_name == 'listProviders':
             # Expecting logic: User selects a provider
             providers = self.provider_repo.list_by_tenant(conversation.tenant_id)
             
             # Filter by service if in context? (Optional logic)
             service_id = conversation.context.get('serviceId')
             if service_id:
                 providers = [p for p in providers if p.can_provide_service(service_id)]
            
             val = user_data.get('value') if user_data else None
             selected_provider = None
             
             if val:
                  selected_provider = next((p for p in providers if p.provider_id == val), None)
                  
             if not selected_provider and user_input:
                  clean_input = user_input.replace("Prefiero con:", "").strip()
                  # Try to match name OR provider_id directly (fuzzy or exact)
                  selected_provider = next((p for p in providers if is_match(clean_input, p.name) or clean_input == p.provider_id), None)
             
             if selected_provider:
                conversation.context['providerId'] = selected_provider.provider_id
                conversation.context['providerName'] = selected_provider.name
                return step.next_step

        elif tool_name == 'checkAvailability':
            # Expecting a timestamp or date string selection
            val = user_data.get('value') if user_data else user_input
            
            # Handle navigation intents from "No Availability" message
            if val == 'change_provider' or (user_input and 'si' in user_input.lower()):
                # Find step with tool 'listProviders' to backtrack safely
                # Simplified: Hardcode common ID or transition to 'flow_providers' intent if supported
                # For now, let's look for a step named 'list_providers' or 'select_provider' in workflow
                
                # Check if 'list_providers' exists
                if 'list_providers' in workflow.steps:
                    return 'list_providers'
                if 'select_provider' in workflow.steps:
                    return 'select_provider'
                
                # Fallback: Just return None -> might loop or error. 
                # Better: Reset providerId and go to start?
                # Let's try to return 'list_providers' assuming default flow structure.
                return 'list_providers'

            if val == 'restart' or (user_input and 'no' in user_input.lower()):
                return 'start'

            if val:
                # Basic validation: Is it a slot (ISO Date)?
                # If it's just random text like "hola", ignore it to prevent invalid booking
                if 'T' in val and len(val) > 10:
                     conversation.context['selectedSlot'] = val
                     return step.next_step
                     
            # If we are here, input was invalid or just conversation text.
            # Return None to potentially stay on step or re-prompt? 
            return None
            
        elif tool_name == 'collectContactInfo':
             # Try to parse contact info from user_data (form submission) or user_input (text)
             # Expected keys: clientName, clientEmail, clientPhone
             
             data = user_data if user_data else {}
             
             # If text input, simple heuristics (or rely on ai later)
             # For now, require structured input or valid json?
             # Or just accept it as 'notes' if we can't parse?
             # Let's assume the frontend sends a FORM submission as user_data.
             
             name = data.get('clientName')
             email = data.get('clientEmail')
             
             # Simple validation
             if name and email:
                 conversation.context['clientName'] = name
                 conversation.context['clientEmail'] = email
                 conversation.context['clientPhone'] = data.get('clientPhone')
                 conversation.context['notes'] = data.get('notes')
                 return step.next_step
             
             # If using text chat purely, we might need a multi-turn slot filling here.
             # But for this implementation, let's assume if we fail to parse, we stay on step.
             
             return None

        elif tool_name == 'confirmBooking':
            # This tool is usually auto-executed, but if we are here handling input,
            # it means the user replied to the "Success" message.
            # We should probably do nothing or restart?
            if 'gracias' in user_input.lower():
                return None # Stay on success message
            
            return None

        return None

    def _execute_tool(self, conversation, step, workflow):
        tool_name = step.content.get('tool')
        
        if tool_name == 'searchServices':
            # List all services
            services = self.service_repo.list_by_tenant(conversation.tenant_id)
            services = [s for s in services if s.active]
            
            if not services:
                return ResponseBuilder.error_message("No hay servicios disponibles.")
                
            services_list = [
                {
                    'serviceId': s.service_id,
                    'name': s.name,
                    'description': s.description,
                    'price': float(s.price) if s.price else 0,
                    'duration': s.duration_minutes
                }
                for s in services
            ]
            
            return ResponseBuilder.service_selection_message(
                services_list, 
                text="Por favor selecciona un servicio:"
            )
            
        elif tool_name == 'listProviders':
             providers = self.provider_repo.list_by_tenant(conversation.tenant_id)
             
             # Filter by service if in context
             service_id = conversation.context.get('serviceId')
             if service_id:
                 providers = [p for p in providers if p.can_provide_service(service_id)]
            
             if not providers:
                  return ResponseBuilder.error_message("No hay profesionales disponibles para este servicio.")
             
             # Optimization: If only one provider, auto-select it!
             if len(providers) == 1:
                 p = providers[0]
                 conversation.context['providerId'] = p.provider_id
                 conversation.context['providerName'] = p.name
                 
                 # We need to advance to the next step immediately.
                 # Since we are in _execute_tool, which is called by _execute_step,
                 # we can't easily change the step ID of the caller *before* it returns unless we access conversation.
                 
                 # Check if we can find the next step
                 # The 'step' object passed here is the current 'list_providers' step.
                 next_step_id = step.next_step
                 
                 if next_step_id:
                     conversation.current_step_id = next_step_id
                     # Recursively execute the next step (e.g. checkAvailability/select_timeslot)
                     # But first, let's inform the user about the auto-selection?
                     # Ideally we return a composite message: "Asigned to X" + "Select time".
                     # But our ResponseBuilder structure typically returns one main payload.
                     
                     # A hack/feature: Return a TEXT response saying "Atendiendo: Mario Alvarez" 
                     # AND somehow trigger the next step?
                     # Or just return the response of the NEXT step directly.
                     
                     # Let's return the next step's response. The user will see the Calendar directly.
                     # We can prepend a text message if the UI supports it, but standard response is one block.
                     # The user will see "Select a time" and context has the provider.
                     
                     # To be user friendly, we probably want to mention who it is.
                     # But let's stick to the requested logic: "skip to select date".
                     return self._execute_step(conversation, workflow, next_step_id)

             providers_list = [
                {
                    'providerId': p.provider_id,
                    'name': p.name,
                    'bio': p.bio
                }
                for p in providers
            ]
             return ResponseBuilder.provider_selection_message(providers_list)

        elif tool_name == 'showFAQs':
             faqs = self.faq_repo.list_by_tenant(conversation.tenant_id)
             if not faqs:
                 return ResponseBuilder.error_message("No hay preguntas frecuentes.")
             
             faq_text = "Aquí tienes algunas preguntas frecuentes:\n\n"
             for faq in faqs:
                 faq_text += f"❓ *{faq.question}*\n💡 {faq.answer}\n\n"
            
             return {
                 'type': 'text',
                 'text': faq_text
             }

            
        elif tool_name == 'checkAvailability':
             provider_id = conversation.context.get('providerId')
             if not provider_id:
                 return ResponseBuilder.error_message("Error: Profesional no seleccionado.")

             # Get availability rules
             availability = self.availability_repo.get_provider_availability(conversation.tenant_id, provider_id)
             
             # Fallback: If no availability defined in DB, use default Mon-Fri 09:00-17:00
             if not availability:
                 from shared.domain.entities import Availability, TimeRange
                 availability = [
                     Availability(
                         availability_id='default',
                         tenant_id=conversation.tenant_id,
                         provider_id=provider_id,
                         day_of_week=day,
                     time_ranges=[TimeRange(start_time='09:00', end_time='17:00')],
                         active=True
                     )
                     for day in ['MON', 'TUE', 'WED', 'THU', 'FRI']
                 ]
             
             # Generate slots for next 5 days
             slots = []
             today = datetime.now(UTC)
             
             # Map weekday ISO (1=Mon, 7=Sun) to Entity (MON, TUE...)
             weekday_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
             
             for i in range(1, 6): # Next 5 days
                 date = today + timedelta(days=i)
                 day_str = weekday_map[date.weekday()]
                 
                 # Find rules for this day
                 day_rule = next((r for r in availability if r.day_of_week == day_str), None)
                 
                 if day_rule:
                     for window in day_rule.time_ranges:
                         # Simple 60 min slots generation
                         # Parse HH:MM
                         start_h, start_m = map(int, window.start_time.split(':'))
                         end_h, end_m = map(int, window.end_time.split(':'))
                         
                         current_h, current_m = start_h, start_m
                         
                         while (current_h * 60 + current_m) + 60 <= (end_h * 60 + end_m):
                             # Format slot
                             slot_start = f"{date.strftime('%Y-%m-%d')}T{current_h:02d}:{current_m:02d}:00"
                             # end = +60 mins
                             
                             slots.append({
                                 'start': slot_start,
                                 'available': True
                             })
                             
                             # Increment 60 mins
                             current_m += 60
                             while current_m >= 60:
                                 current_m -= 60
                                 current_h += 1
                                 
             if not slots:
                  return ResponseBuilder.no_availability_message()
             
             return ResponseBuilder.date_selection_message(slots[:10]) # Limit to 10 for UI

        elif tool_name == 'collectContactInfo':
             return ResponseBuilder.contact_info_message()
             
        elif tool_name == 'confirmBooking':
            # Create the booking
            try:
                ctx = conversation.context
                
                # Validate required fields
                required = ['serviceId', 'providerId', 'selectedSlot', 'clientName', 'clientEmail']
                missing = [f for f in required if not ctx.get(f)]
                if missing:
                     return ResponseBuilder.error_message(f"Faltan datos para la reserva: {', '.join(missing)}")
                
                booking_id = generate_id('bk')
                
                booking = Booking(
                    booking_id=booking_id,
                    tenant_id=conversation.tenant_id,
                    service_id=ctx['serviceId'],
                    provider_id=ctx['providerId'],
                    customer_info=CustomerInfo(
                        name=ctx['clientName'],
                        email=ctx['clientEmail'],
                        phone=ctx.get('clientPhone')
                    ),
                    start_time=ctx['selectedSlot'],
                    status=BookingStatus.CONFIRMED,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC)
                )
                
                self.booking_repo.save(booking)
                
                # Store booking id in context
                conversation.context['bookingId'] = booking_id
                
                # Return success message
                # Note: We return the message directly. 
                # The state remains on this step unless we force move, 
                # but typically this is the end of flow.
                
                # Construct booking dict for response
                booking_dict = {
                    'bookingId': booking.booking_id,
                    'clientEmail': booking.customer_info.email,
                    'serviceName': ctx.get('serviceName', 'Servicio'), # Should be in context
                    'providerName': ctx.get('providerName', 'Profesional'),
                    'startTime': booking.start_time
                }
                
                return ResponseBuilder.success_message(booking_dict)
                
            except Exception as e:
                print(f"Booking Error: {e}")
                return ResponseBuilder.error_message("No pudimos procesar tu reserva. Intenta nuevamente.")

        return ResponseBuilder.error_message(f"Tool {tool_name} not implemented")

