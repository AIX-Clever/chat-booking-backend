from typing import Optional, Dict, Any, List
from datetime import datetime, UTC, timedelta
from shared.domain.entities import (
    Conversation,
    Workflow,
    WorkflowStep,
    TenantId,
    Booking,
    BookingStatus,
    CustomerInfo,
)
from shared.domain.exceptions import ValidationError
from shared.utils import generate_id
from zoneinfo import ZoneInfo

try:
    from .fsm import ResponseBuilder
except ImportError:
    from fsm import ResponseBuilder


class WorkflowEngine:
    """
    Executes dynamic workflows defined in JSON.
    Replaces the hardcoded FSM logic.
    """

    def __init__(
        self,
        service_repo,
        provider_repo,
        faq_repo,
        availability_repo,
        booking_repo,
        availability_service=None,
        booking_service=None,
    ):
        self.service_repo = service_repo
        self.provider_repo = provider_repo
        self.faq_repo = faq_repo
        self.availability_repo = availability_repo
        self.booking_repo = booking_repo
        self.availability_service = availability_service
        self.booking_service = booking_service

    def process_step(
        self,
        conversation: Conversation,
        workflow: Workflow,
        user_input: str,
        user_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process the current step or transition to the next one based on input.
        """
        current_step_id = conversation.current_step_id

        # If no step, start at 'start' (or whatever is first)
        if not current_step_id:
            current_step_id = "start"
            conversation.current_step_id = current_step_id
            return self._execute_step(conversation, workflow, current_step_id)

        current_step = workflow.steps.get(current_step_id)
        if not current_step:
            # Fallback or error
            return ResponseBuilder.error_message(f"Step {current_step_id} not found")

        # 1. Handle Input for CURRENT step (if it was waiting for input)
        # e.g. if we are in a QUESTION step, we check the answer

        next_step_id = None

        if current_step.type == "QUESTION":
            next_step_id = self._handle_question_input(
                current_step, user_input, user_data, conversation
            )
        elif current_step.type == "DYNAMIC_OPTIONS":
            next_step_id = self._handle_dynamic_options_input(
                current_step, user_input, user_data, conversation
            )
        elif current_step.type == "TOOL":
            # Try to handle input for the tool (e.g. selection)
            # If it returns a next_step_id, it means we consumed the input successfully
            next_step_id = self._handle_tool_input(
                current_step, user_input, user_data, conversation, workflow
            )

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

    def _execute_step(
        self, conversation: Conversation, workflow: Workflow, step_id: str
    ) -> Dict[str, Any]:
        """
        Execute the logic for a specific step (generate response/action)
        """
        step = workflow.steps.get(step_id)
        if not step:
            return ResponseBuilder.error_message("Flow Error: Step needed")

        # HOTFIX: Skip the old static message step for contact info
        # This allows the new smart tool logic (in collectContactInfo) to handle the prompting dynamicallly.
        if step_id == "request_contact_info":
            conversation.current_step_id = "collect_contact_info"
            return self._execute_step(conversation, workflow, "collect_contact_info")

        if step.type == "MESSAGE":
            # Send message and optionally auto-advance
            if step.next_step:
                conversation.current_step_id = step.next_step

            return {"type": "text", "text": step.content.get("text", "")}

        elif step.type == "QUESTION":
            return {
                "type": step.content.get("ui_type", "text"),  # text, options, form
                "text": step.content.get("text", ""),
                "options": step.content.get("options", []),
            }

        elif step.type == "DYNAMIC_OPTIONS":
            return self._generate_dynamic_options(conversation, step)

        elif step.type == "TOOL":
            tool_response = self._execute_tool(conversation, step, workflow)

            # Auto-advance ONLY if explicitly configured (e.g. for informational steps like FAQs)
            # Interactive tools (like searchServices) must stop to wait for user input.
            if step.next_step and step.content.get("auto_advance"):
                conversation.current_step_id = step.next_step
                next_response = self._execute_step(
                    conversation, workflow, step.next_step
                )

                # Merge text content (Tool Result + Next Step Prompt)
                if "text" in tool_response and "text" in next_response:
                    next_response["text"] = (
                        tool_response["text"] + "\n\n" + next_response["text"]
                    )

                # Merge Metadata (Preserve Tool Metadata, e.g. for FAQs)
                if "metadata" in tool_response:
                    if "metadata" not in next_response:
                        next_response["metadata"] = {}
                    next_response["metadata"].update(tool_response["metadata"])

                return next_response

            return tool_response

        return ResponseBuilder.error_message(f"Unknown step type: {step.type}")

    def _generate_dynamic_options(
        self, conversation: Conversation, step: WorkflowStep
    ) -> Dict[str, Any]:
        """
        Check DB for Services, Providers, FAQs and build options
        """
        sources = step.content.get("sources", [])
        mapping = step.content.get("options_mapping", {})

        options = []

        # Check Services
        if "SERVICES" in sources and self.service_repo.list_by_tenant(
            conversation.tenant_id
        ):
            svc_map = mapping.get("SERVICES", {})
            options.append(
                {
                    "label": svc_map.get("label", "Services"),
                    "value": svc_map.get("value", "flow_services"),
                }
            )

        # Check Providers
        if "PROVIDERS" in sources and self.provider_repo.list_by_tenant(
            conversation.tenant_id
        ):
            prov_map = mapping.get("PROVIDERS", {})
            options.append(
                {
                    "label": prov_map.get("label", "Providers"),
                    "value": prov_map.get("value", "flow_providers"),
                }
            )

        # Check FAQs
        if "FAQS" in sources and self.faq_repo.list_by_tenant(conversation.tenant_id):
            faq_map = mapping.get("FAQS", {})
            options.append(
                {
                    "label": faq_map.get("label", "FAQs"),
                    "value": faq_map.get("value", "flow_faqs"),
                }
            )

        if not options:
            # Fallback if nothing available
            if step.next_step:
                # Skip to next if no options?
                pass
            return {
                "type": "text",
                "text": step.content.get("empty_text", "No options available."),
            }

        return {
            "type": "options",
            "text": step.content.get("text", "Select an option:"),
            "options": options,
        }

    def _handle_question_input(self, step, user_input, user_data, conversation):
        # Check validity (regex, options match)
        options = step.content.get("options", [])

        # If options defined, check match
        if options:
            # Check user_data value or text match
            val = user_data.get("value") if user_data else None

            # Find matching option
            selected = None
            if val:
                selected = next((o for o in options if o["value"] == val), None)

            if not selected and user_input:
                # Fuzzy match text
                selected = next(
                    (o for o in options if o["label"].lower() in user_input.lower()),
                    None,
                )

            if selected:
                # Store selection in context
                if "save_as" in step.content:
                    key = step.content["save_as"]
                    conversation.context[key] = selected["value"]

                return selected.get("next", step.next_step)

        # Free text input
        # Store validation logic here...

        return step.next_step

    def _handle_dynamic_options_input(self, step, user_input, user_data, conversation):
        mapping = step.content.get("options_mapping", {})

        selected_next = None

        # Find which source this maps to
        for source, config in mapping.items():
            config_val = config.get("value")
            config_label = config.get("label", "").lower()

            # Check 1: Explicit userData value (strongest signal)
            if user_data and user_data.get("value") == config_val:
                selected_next = config.get("next")
                break

            # Check 2: Message text matches option value (e.g. "flow_booking")
            if user_input and config_val and user_input.strip() == config_val:
                selected_next = config.get("next")
                break

            # Check 3: Message text matches option label (e.g. "reservar servicio")
            if user_input and config_label and config_label in user_input.lower():
                selected_next = config.get("next")
                break

        return selected_next  # Invalid selection

    def _handle_tool_input(self, step, user_input, user_data, conversation, workflow):
        tool_name = step.content.get("tool")

        # Helper for fuzzy match
        def is_match(text, target):
            return target.lower() in text.lower() or text.lower() in target.lower()

        # Normalize tool name keys to handle mismatch (startBookingFlow vs start_booking_flow)
        if tool_name in ["searchServices", "start_booking_flow"]:
            # Expecting logic: User selects a service
            services = self.service_repo.list_by_tenant(conversation.tenant_id)
            active_services = [s for s in services if s.active]

            # 1. Check direct value (if structured input)
            val = user_data.get("value") if user_data else None
            # Some widgets send "service_id" or similar? Assuming "value" holds ID if clicked.

            selected_service = None

            if val:
                selected_service = next(
                    (s for s in active_services if s.service_id == val), None
                )

            if not selected_service and user_input:
                # Fuzzy match name
                # Remove common prefixes like "Selecciono: "
                clean_input = user_input.replace("Selecciono:", "").strip()
                selected_service = next(
                    (s for s in active_services if is_match(clean_input, s.name)), None
                )

            if selected_service:
                conversation.context["serviceId"] = selected_service.service_id
                conversation.context["serviceName"] = selected_service.name
                return step.next_step

        elif tool_name in ["listProviders", "list_providers"]:
            # Expecting logic: User selects a provider
            providers = self.provider_repo.list_by_tenant(conversation.tenant_id)

            # Filter by service if in context? (Optional logic)
            service_id = conversation.context.get("serviceId")
            if service_id:
                providers = [p for p in providers if p.can_provide_service(service_id)]

            val = user_data.get("value") if user_data else None
            selected_provider = None

            if val:
                selected_provider = next(
                    (p for p in providers if p.provider_id == val), None
                )

            if not selected_provider and user_input:
                clean_input = user_input.replace("Prefiero con:", "").strip()
                # Try to match name OR provider_id directly
                selected_provider = next(
                    (
                        p
                        for p in providers
                        if is_match(clean_input, p.name) or clean_input == p.provider_id
                    ),
                    None,
                )

            if selected_provider:
                conversation.context["providerId"] = selected_provider.provider_id
                conversation.context["providerName"] = selected_provider.name

                # Smart routing: Check if serviceId is already in context
                # If YES -> Standard flow (Service -> Provider -> Time)
                # If NO -> Provider flow (Provider -> Service -> Time)
                if conversation.context.get("serviceId"):
                    return step.next_step  # Go to select_timeslot
                else:
                    return "resolve_service"  # Ask for service first

        elif tool_name in ["checkAvailability", "check_availability"]:
            # Expecting a timestamp or date string selection
            val = user_data.get("value") if user_data else user_input

            # Handle navigation intents from "No Availability" message
            if val == "change_provider" or (user_input and "si" in user_input.lower()):
                # Find step with tool 'listProviders' or 'list_providers' to backtrack dynamically
                prev_step_id = next(
                    (
                        sid
                        for sid, s in workflow.steps.items()
                        if s.content.get("tool") in ["list_providers", "listProviders"]
                    ),
                    "start",
                )
                return prev_step_id

            if val == "restart" or (user_input and "no" in user_input.lower()):
                return "start"

            # Attempt to accept the slot
            # 1. Direct ISO value (standard button payload)
            if val and "T" in val and len(val) > 10:
                conversation.context["selectedSlot"] = val
                return step.next_step

            # 2. Parse text input (e.g. "Reservo para: 04-01-2026, 10:00:00 a. m.")
            if user_input:
                import re

                # Improved Regex to capture Date, Time, and AM/PM indicator
                match = re.search(
                    r"(\d{2}-\d{2}-\d{4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?)(\s*[aApP]\.?\s*[mM]\.?)?",
                    user_input,
                )

                if match:
                    try:
                        date_str = match.group(1)
                        time_str = match.group(2)
                        ampm_str = match.group(3)

                        # 1. Determine Timezone
                        tz = ZoneInfo("UTC")  # Default
                        provider_id = conversation.context.get("providerId")
                        if provider_id:
                            # Assume tenant_id is available in conversation
                            provider = self.provider_repo.get_by_id(
                                conversation.tenant_id, provider_id
                            )
                            if provider and provider.timezone:
                                tz = ZoneInfo(provider.timezone)

                        # 2. Parse Date & Time to naive object
                        # Normalize time string to HH:MM:SS
                        if len(time_str.split(":")) == 2:
                            time_str += ":00"

                        dt_str = f"{date_str} {time_str}"
                        dt = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")

                        # 3. Handle AM/PM adjustment
                        if ampm_str:
                            is_pm = "p" in ampm_str.lower()
                            if is_pm and dt.hour < 12:
                                dt = dt.replace(hour=dt.hour + 12)
                            elif not is_pm and dt.hour == 12:
                                dt = dt.replace(hour=0)

                        # 4. Attach Provider Timezone
                        dt_aware = dt.replace(tzinfo=tz)

                        # 5. Convert to UTC for storage
                        dt_utc = dt_aware.astimezone(UTC)

                        conversation.context["selectedSlot"] = dt_utc.isoformat()
                        return step.next_step

                    except Exception as e:
                        print(f"Date parsing failed: {e}")
                        # Don't return None yet, let it fall through or maybe log error

            # If we are failing to match, the user is stuck.
            # IMPROVEMENT: If the user input contains high confidence date info, let's accept it merely to unblock flow?
            # No, invalid date crashes booking.

            return None

            if val:
                # Basic validation: Is it a slot (ISO Date)?
                # If it's just random text like "hola", ignore it to prevent invalid booking
                if "T" in val and len(val) > 10:
                    conversation.context["selectedSlot"] = val
                    return step.next_step

            # If we are here, input was invalid or just conversation text.
            # Return None to potentially stay on step or re-prompt?
            return None

        elif tool_name == "collectContactInfo":
            # Try to parse contact info from user_data (form submission) or user_input (text)

            data = user_data if user_data else {}

            # 1. Structure Input (Form)
            if data.get("clientName"):
                conversation.context["clientName"] = data.get("clientName")
            if data.get("clientEmail"):
                conversation.context["clientEmail"] = data.get("clientEmail")
            if data.get("clientPhone"):
                conversation.context["clientPhone"] = data.get("clientPhone")

            # 2. Text Input (Slot Filling Strategy)
            if user_input:
                text = user_input.strip()
                # Simple heuristic: Contains @ -> Email
                if "@" in text:
                    conversation.context["clientEmail"] = text
                # Heuristic: If we don't have a name yet, and this doesn't look like an email
                elif not conversation.context.get("clientName"):
                    # Only accept if it looks like a name (not a question, not too short)
                    if "?" not in text and len(text) > 2:
                        conversation.context["clientName"] = text
                    else:
                        # It's a question or garbage. We ignore it, so the prompt repeats.
                        pass

                # Heuristic: Phone number (mostly digits)
                import re

                digits = re.sub(r"\D", "", text)
                if not conversation.context.get("clientPhone") and len(digits) >= 8:
                    conversation.context["clientPhone"] = text

            # Check completion - REQUIRE ALL 3
            if (
                conversation.context.get("clientName")
                and conversation.context.get("clientEmail")
                and conversation.context.get("clientPhone")
            ):
                return step.next_step

            # If missing data, we return None to stay on step (and re-prompt)
            return None

        elif tool_name == "confirmBooking":
            # This tool is usually auto-executed, but if we are here handling input,
            # it means the user replied to the "Success" message.
            # We should probably do nothing or restart?
            if "gracias" in user_input.lower():
                return None  # Stay on success message

            return None

        return None

    def _execute_tool(self, conversation, step, workflow):
        tool_name = step.content.get("tool")

        if tool_name in ["searchServices", "start_booking_flow"]:
            # List all services
            services = self.service_repo.list_by_tenant(conversation.tenant_id)
            services = [s for s in services if s.active]

            # Filter by provider if in context (Provider-First Flow)
            provider_id = conversation.context.get("providerId")
            if provider_id:
                # Assuming provider_repo available or we can check provider's services
                # Ideally, we should fetch the provider to see their service_ids
                # For optimization, we can pull all providers or just this one if we had a method
                # Using provider_repo.list for now as we don't have get_by_id exposed in valid scope?
                # Actually, `self.provider_repo` is available
                provider = self.provider_repo.get_by_id(
                    conversation.tenant_id, provider_id
                )
                if provider:
                    services = [
                        s for s in services if s.service_id in provider.service_ids
                    ]

            if not services:
                return ResponseBuilder.error_message("No hay servicios disponibles.")

            services_list = [
                {
                    "serviceId": s.service_id,
                    "name": s.name,
                    "description": s.description,
                    "price": float(s.price) if s.price else 0,
                    "duration": s.duration_minutes,
                }
                for s in services
            ]

            return ResponseBuilder.service_selection_message(
                services_list, text="Por favor selecciona un servicio:"
            )

        elif tool_name in ["listProviders", "list_providers"]:
            providers = self.provider_repo.list_by_tenant(conversation.tenant_id)

            # Filter by service if in context
            service_id = conversation.context.get("serviceId")
            if service_id:
                providers = [p for p in providers if p.can_provide_service(service_id)]

            if not providers:
                return ResponseBuilder.error_message(
                    "No hay profesionales disponibles para este servicio."
                )

            providers_list = [
                {"providerId": p.provider_id, "name": p.name, "bio": p.bio}
                for p in providers
            ]
            return ResponseBuilder.provider_selection_message(providers_list)

        elif tool_name in ["showFAQs", "get_faqs"]:
            faqs = self.faq_repo.list_by_tenant(conversation.tenant_id)

            # Filter out placeholder/dummy FAQs
            valid_faqs = [f for f in faqs if "*question*" not in f.question]

            if not valid_faqs:
                return {
                    "type": "text",
                    "text": "No hay preguntas frecuentes registradas.",
                }

            # Return structured FAQ data for accordion rendering
            faqs_data = [
                {"question": f.question, "answer": f.answer} for f in valid_faqs
            ]

            return {
                "type": "faq_accordion",
                "text": "Aquí tienes la información que suele ser útil:",
                "metadata": {"type": "faq_accordion", "faqs": faqs_data},
            }

        elif tool_name in ["checkAvailability", "check_availability"]:
            provider_id = conversation.context.get("providerId")
            service_id = conversation.context.get("serviceId")
            
            if not provider_id:
                return ResponseBuilder.error_message(
                    "Error: Profesional no seleccionado."
                )

            # Safety Net: Ensure Service is selected
            if not service_id:
                # Loop back to resolve service if we somehow got here without a service
                # This handles the "Provider First" edge case where routing failed
                return "resolve_service"

            # Use AvailabilityService if available, otherwise fallback to local logic
            if self.availability_service:
                # Calculate range for next 5 days
                from_date = datetime.now(UTC)
                to_date = from_date + timedelta(days=5)
                
                # Get slots from service
                available_slots = self.availability_service.get_available_slots(
                    conversation.tenant_id, service_id, provider_id, from_date, to_date
                )
                
                if not available_slots:
                    return ResponseBuilder.no_availability_message()
                
                # Format for UI
                slots_data = [
                    {"start": s.start.isoformat(), "available": True}
                    for s in available_slots
                ]
                
                return ResponseBuilder.date_selection_message(slots_data[:12])
            
            # [LEGACY FALLBACK] - Keeping as safety but it's what we want to avoid
            # Get availability rules
            availability = self.availability_repo.get_provider_availability(
                conversation.tenant_id, provider_id
            )
            # ... (rest of old code removed for brevity in this replacement chunk) ...
            return ResponseBuilder.no_availability_message()

        elif tool_name == "collectContactInfo":
            # Dynamic Prompting based on missing slots
            ctx = conversation.context
            missing = []
            if not ctx.get("clientName"):
                return {
                    "type": "text",
                    "text": "Perfecto. Para confirmar tu reserva, necesito algunos datos.\n\n¿Me podrías indicar tu **nombre completo**?",
                }
            if not ctx.get("clientEmail"):
                return {
                    "type": "text",
                    "text": f"Gracias {ctx.get('clientName')}. ¿Cual es tu correo electrónico para enviarte la confirmación?",
                }
            if not ctx.get("clientPhone"):
                return {
                    "type": "text",
                    "text": "Por último, ¿me podrías dejar un número de teléfono de contacto?",
                }

            return ResponseBuilder.contact_info_message()

        elif tool_name == "confirmBooking":
            # Create the booking
            try:
                ctx = conversation.context

                # Validate required fields
                required = [
                    "serviceId",
                    "providerId",
                    "selectedSlot",
                    "clientName",
                    "clientEmail",
                ]
                missing = [f for f in required if not ctx.get(f)]
                if missing:
                    return ResponseBuilder.error_message(
                        f"Faltan datos para la reserva: {', '.join(missing)}"
                    )

                # Parse start_time (it's stored as ISO string in context)
                start_time_str = ctx["selectedSlot"]
                try:
                    if isinstance(start_time_str, str):
                        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                    else:
                        start_time = start_time_str
                except Exception as e:
                    print(f"Error parsing date {start_time_str}: {e}")
                    return ResponseBuilder.error_message("Error en el formato de fecha seleccionado.")

                if self.booking_service:
                    # Delegate to centralized service
                    booking = self.booking_service.create_booking(
                        tenant_id=conversation.tenant_id,
                        service_id=ctx["serviceId"],
                        provider_id=ctx["providerId"],
                        start=start_time,
                        end=start_time + timedelta(minutes=ctx.get("duration", 60)), # Will be validated inside service
                        client_name=ctx["clientName"],
                        client_email=ctx["clientEmail"],
                        client_phone=ctx.get("clientPhone"),
                        notes=ctx.get("notes"),
                        conversation_id=conversation.conversation_id
                    )

                    # Store booking id in context
                    conversation.context["bookingId"] = booking.booking_id
                    
                    # Construct success message
                    booking_dict = {
                        "bookingId": booking.booking_id,
                        "serviceName": ctx.get("serviceName", "Servicio"),
                        "providerName": ctx.get("providerName", "Profesional"),
                        "startTime": booking.start_time.isoformat(),
                        "clientName": ctx.get("clientName"),
                        "clientEmail": ctx.get("clientEmail"),
                    }
                    return ResponseBuilder.success_message(booking_dict)

                # [LEGACY FALLBACK] matches old behavior but should be avoided
                return ResponseBuilder.error_message("Error interno: Servicio de reservas no disponible.")

            except Exception as e:
                print(f"Booking Error: {e}")
                return ResponseBuilder.error_message(
                    f"No pudimos procesar tu reserva: {str(e)}"
                )

        return ResponseBuilder.error_message(f"Tool {tool_name} not implemented")
