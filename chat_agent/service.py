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
    IAvailabilityRepository
)
from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError
)
from shared.utils import generate_id, parse_iso_datetime

from fsm import ChatFSM, ResponseBuilder


class ChatAgentService:
    """
    Service for managing conversational booking flow
    
    Responsibilities:
    - Initialize conversations
    - Process user messages
    - Manage FSM state transitions
    - Coordinate with other services (catalog, availability, booking)
    - Generate appropriate responses
    
    SOLID:
    - SRP: Orchestrates conversation flow only
    - OCP: Extensible with new message handlers
    - LSP: Uses repository interfaces
    - ISP: Depends only on needed repositories
    - DIP: Depends on abstractions
    """
    
    def __init__(
        self,
        conversation_repo: IConversationRepository,
        service_repo: IServiceRepository,
        provider_repo: IProviderRepository,
        booking_repo: IBookingRepository,
        availability_repo: IAvailabilityRepository
    ):
        self._conversation_repo = conversation_repo
        self._service_repo = service_repo
        self._provider_repo = provider_repo
        self._booking_repo = booking_repo
        self._availability_repo = availability_repo
    
    def start_conversation(
        self,
        tenant_id: TenantId,
        channel: str = 'widget',
        metadata: Optional[Dict[str, Any]] = None
    ) -> tuple[Conversation, dict]:
        """
        Start a new conversation
        
        Args:
            tenant_id: Tenant identifier
            channel: Communication channel (widget, whatsapp, etc)
            metadata: Optional metadata (user_agent, referrer, etc)
        
        Returns:
            (conversation, response_message)
        """
        conversation_id = generate_id('conv')
        conversation = Conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            state=ConversationState.INIT
        )
        
        self._conversation_repo.save(conversation)
        
        # Transition to SERVICE_PENDING
        conversation.transition_to(ConversationState.SERVICE_PENDING)
        self._conversation_repo.save(conversation)
        
        # Generate greeting response
        response = ResponseBuilder.greeting_message()
        
        return conversation, response
    
    def process_message(
        self,
        tenant_id: TenantId,
        conversation_id: str,
        message: str,
        message_type: str = 'text',
        user_data: Optional[Dict[str, Any]] = None
    ) -> tuple[Conversation, dict]:
        """
        Process user message and advance conversation
        
        Args:
            tenant_id: Tenant identifier
            conversation_id: Conversation identifier
            message: User message content
            message_type: Type of message (text, selection, form_data, etc)
            user_data: Additional data from user (selections, form fields, etc)
        
        Returns:
            (updated_conversation, response_message)
        """
        # Load conversation
        conversation = self._conversation_repo.get_by_id(tenant_id, conversation_id)
        if not conversation:
            raise EntityNotFoundError(f"Conversation not found: {conversation_id}")
        
        # Add user message to history (would be stored separately in production)
        # conversation.messages.append({
        #     'role': 'user',
        #     'content': message,
        #     'type': message_type,
        #     'timestamp': datetime.now(UTC).isoformat()
        # })
        
        # Process based on current state
        current_state = conversation.state
        
        if current_state == ConversationState.SERVICE_PENDING:
            response = self._handle_service_selection(
                tenant_id,
                conversation,
                message,
                user_data
            )
        
        elif current_state == ConversationState.SERVICE_SELECTED:
            response = self._handle_provider_request(
                tenant_id,
                conversation
            )
        
        elif current_state == ConversationState.PROVIDER_PENDING:
            response = self._handle_provider_selection(
                tenant_id,
                conversation,
                message,
                user_data
            )
        
        elif current_state == ConversationState.PROVIDER_SELECTED:
            response = self._handle_slot_request(
                tenant_id,
                conversation
            )
        
        elif current_state == ConversationState.SLOT_PENDING:
            response = self._handle_slot_selection(
                tenant_id,
                conversation,
                message,
                user_data
            )
        
        elif current_state == ConversationState.CONFIRM_PENDING:
            response = self._handle_confirmation(
                tenant_id,
                conversation,
                message,
                user_data
            )
        
        elif current_state == ConversationState.BOOKING_CONFIRMED:
             # Reset conversation for new booking
             response = self._handle_post_booking_reset(
                 tenant_id,
                 conversation
             )
        
        else:
            response = ResponseBuilder.error_message(
                f"Estado no reconocido: {current_state.value}"
            )
        
        # Add bot response to history (would be stored separately in production)
        # conversation.messages.append({
        #     'role': 'assistant',
        #     'content': response.get('text', ''),
        #     'type': response.get('type', 'text'),
        #     'timestamp': datetime.now(UTC).isoformat()
        # })
        
        conversation.updated_at = datetime.now(UTC)
        self._conversation_repo.save(conversation)
        
        return conversation, response
    
    def _handle_service_selection(
        self,
        tenant_id: TenantId,
        conversation: Conversation,
        message: str,
        user_data: Optional[Dict[str, Any]]
    ) -> dict:
        """Handle service selection"""
        service_id = user_data.get('serviceId') if user_data else None
        
        # Try to find service by name if not explicitly selected
        services = self._service_repo.search(tenant_id)

        if not service_id:
            # Check if message matches any service name
            normalized_msg = message.lower().strip()
            for service in services:
                if service.name.lower() in normalized_msg:
                    service_id = service.service_id
                    break
        
        if not service_id:
            # Show available services
            services_list = [
                {
                    'serviceId': s.service_id,
                    'name': s.name,
                    'description': s.description,
                    'price': s.price,
                    'duration': s.duration_minutes
                }
                for s in services
            ]
            
            # If we are here, it means the user sent a message (this is process_message)
            # but it didn't match a service.
            feedback_text = f"Disculpa, no encontré un servicio relacionado con '{message}'.\nPor favor selecciona una de las opciones:"
            
            return ResponseBuilder.service_selection_message(services_list, text=feedback_text)
        
        # Validate service exists
        service = self._service_repo.get_by_id(tenant_id, service_id)
        if not service:
            return ResponseBuilder.error_message("Servicio no encontrado")
        
        # Update context and transition
        conversation.context['serviceId'] = service_id
        conversation.context['serviceName'] = service.name
        conversation.context['servicePrice'] = service.price
        conversation.context['serviceDuration'] = service.duration_minutes
        
        # Sync with entity attributes
        conversation.service_id = service_id
        
        conversation.transition_to(ConversationState.SERVICE_SELECTED)
        
        return {
            'type': 'text',
            'text': f'Excelente elección: {service.name}. Ahora busquemos un profesional disponible.'
        }
    
    def _handle_provider_request(
        self,
        tenant_id: TenantId,
        conversation: Conversation
    ) -> dict:
        """Show available providers for selected service"""
        service_id = conversation.context.get('serviceId')
        
        # Get providers that can provide this service
        providers = self._provider_repo.list_by_service(tenant_id, service_id)
        
        if not providers:
            return ResponseBuilder.error_message(
                "No hay profesionales disponibles para este servicio"
            )
        
        providers_list = [
            {
                'providerId': p.provider_id,
                'name': p.name,
                'bio': p.bio
            }
            for p in providers
        ]
        
        # Transition to PROVIDER_PENDING
        conversation.transition_to(ConversationState.PROVIDER_PENDING)
        
        return ResponseBuilder.provider_selection_message(providers_list)
    
    def _handle_provider_selection(
        self,
        tenant_id: TenantId,
        conversation: Conversation,
        message: str,
        user_data: Optional[Dict[str, Any]]
    ) -> dict:
        """Handle provider selection"""
        provider_id = user_data.get('providerId') if user_data else None
        
        if not provider_id:
            # Try to match provider name from message
            service_id = conversation.context.get('serviceId')
            if service_id:
                providers = self._provider_repo.list_by_service(tenant_id, service_id)
                normalized_msg = message.lower().strip()
                for provider in providers:
                    if provider.name.lower() in normalized_msg:
                        provider_id = provider.provider_id
                        break

        if not provider_id:
            # Re-fetch providers to show valid options again
            service_id = conversation.context.get('serviceId')
            providers = self._provider_repo.list_by_service(tenant_id, service_id)
            
            providers_list = [
                {
                    'providerId': p.provider_id,
                    'name': p.name,
                    'bio': p.bio
                }
                for p in providers
            ]
            
            feedback_text = f"No encontré un profesional llamado '{message}'. Por favor selecciona uno de la lista:"
            return ResponseBuilder.provider_selection_message(providers_list, text=feedback_text)
        
        # Validate provider
        provider = self._provider_repo.get_by_id(tenant_id, provider_id)
        if not provider:
            return ResponseBuilder.error_message("Profesional no encontrado")
        
        # Update context and transition
        conversation.context['providerId'] = provider_id
        conversation.context['providerName'] = provider.name
        
        # Sync with entity attributes
        conversation.provider_id = provider_id
        
        conversation.transition_to(ConversationState.PROVIDER_SELECTED)
        
        return {
            'type': 'text',
            'text': f'Perfecto, agendaremos con {provider.name}. Veamos la disponibilidad.'
        }
    
    def _handle_slot_request(
        self,
        tenant_id: TenantId,
        conversation: Conversation
    ) -> dict:
        """Show available time slots"""
        service_id = conversation.context.get('serviceId')
        provider_id = conversation.context.get('providerId')
        
        # Get availability for next 14 days
        from_date = datetime.now(UTC)
        to_date = from_date + timedelta(days=14)
        
        # This would call availability service (simplified here)
        # In real implementation, this would use AvailabilityService
        available_slots = []
        
        # For demo, create some sample slots
        # In production, this would come from availability Lambda
        for i in range(7):
            date = from_date + timedelta(days=i)
            for hour in [9, 10, 11, 14, 15, 16]:
                slot_start = date.replace(hour=hour, minute=0, second=0, microsecond=0)
                available_slots.append({
                    'start': slot_start.isoformat() + 'Z',
                    'end': (slot_start + timedelta(minutes=60)).isoformat() + 'Z',
                    'available': True
                })
        
        if not available_slots:
            conversation.transition_to(ConversationState.PROVIDER_SELECTED)
            return ResponseBuilder.no_availability_message()
        
        # Transition to SLOT_PENDING
        conversation.transition_to(ConversationState.SLOT_PENDING)
        
        return ResponseBuilder.date_selection_message(available_slots)
    
    def _handle_slot_selection(
        self,
        tenant_id: TenantId,
        conversation: Conversation,
        message: str,
        user_data: Optional[Dict[str, Any]]
    ) -> dict:
        """Handle time slot selection"""
        selected_slot = user_data.get('selectedSlot') if user_data else None
        
        if not selected_slot:
            return ResponseBuilder.error_message("Debes seleccionar un horario")
        
        # Validate slot format
        try:
            start_time = parse_iso_datetime(selected_slot.get('start'))
            end_time = parse_iso_datetime(selected_slot.get('end'))
        except (ValueError, AttributeError):
            return ResponseBuilder.error_message("Formato de horario inválido")
        
        # Update context
        conversation.context['selectedSlot'] = selected_slot
        
        # Sync with entity attributes
        conversation.slot_start = start_time
        conversation.slot_end = end_time
        
        conversation.transition_to(ConversationState.CONFIRM_PENDING)
        
        # Ask for contact info (or check if we already have it to skip to confirmation)
        # For simplicity, we always ask/verify contact info next, via the form or context chcek
        return ResponseBuilder.contact_info_message()
    
    def _handle_confirmation(
        self,
        tenant_id: TenantId,
        conversation: Conversation,
        message: str,
        user_data: Optional[Dict[str, Any]]
    ) -> dict:
        """Handle booking confirmation"""
        if not user_data:
            return ResponseBuilder.error_message("Faltan datos de contacto")
        
        # Extract contact info
        client_name = user_data.get('clientName')
        client_email = user_data.get('clientEmail')
        client_phone = user_data.get('clientPhone')
        notes = user_data.get('notes')
        
        if not client_name or not client_email:
            return ResponseBuilder.error_message(
                "Nombre y email son obligatorios"
            )
        
        # Update context
        conversation.context['clientName'] = client_name
        conversation.context['clientEmail'] = client_email
        if client_phone:
            conversation.context['clientPhone'] = client_phone
        if notes:
            conversation.context['notes'] = notes
        
        # Show confirmation
        booking_details = {
            'service': conversation.context.get('serviceName'),
            'provider': conversation.context.get('providerName'),
            'datetime': conversation.context.get('selectedSlot', {}).get('start'),
            'duration': conversation.context.get('serviceDuration'),
            'price': conversation.context.get('servicePrice'),
            'clientName': client_name,
            'clientEmail': client_email,
            'clientPhone': client_phone
        }
        
        return ResponseBuilder.confirmation_message(booking_details)
    
    def confirm_booking(
        self,
        tenant_id: TenantId,
        conversation_id: str
    ) -> tuple[Conversation, dict]:
        """
        Confirm and create the booking
        
        This should be called after user confirms booking details
        """
        conversation = self._conversation_repo.get_by_id(tenant_id, conversation_id)
        if not conversation:
            raise EntityNotFoundError(f"Conversation not found: {conversation_id}")
        
        # Validate conversation is ready for booking
        if not conversation.is_ready_for_booking():
            raise ValidationError("Conversation not ready for booking")
        
        context = conversation.context
        
        # Extract booking data
        service_id = context.get('serviceId')
        provider_id = context.get('providerId')
        selected_slot = context.get('selectedSlot')
        client_name = context.get('clientName')
        client_email = context.get('clientEmail')
        client_phone = context.get('clientPhone')
        notes = context.get('notes')
        
        # Parse slot times
        start = parse_iso_datetime(selected_slot['start'])
        end = parse_iso_datetime(selected_slot['end'])
        
        # Create booking entity
        booking_id = generate_id('bkg')
        booking = Booking(
            booking_id=booking_id,
            tenant_id=tenant_id,
            service_id=service_id,
            provider_id=provider_id,
            customer_info=CustomerInfo(
                customer_id=None,
                name=client_name,
                email=client_email,
                phone=client_phone
            ),
            start_time=start,
            end_time=end,
            status=BookingStatus.CONFIRMED,
            conversation_id=conversation_id
        )

        # Save booking using repository (handles collision checks)
        try:
            self._booking_repo.save(booking)
        except Exception as e:
            # If booking fails (e.g. collision), revert state or error
            # For now, simplistic error handling
            raise ValidationError(f"Could not create booking: {str(e)}")
        
        # Update context
        conversation.context['bookingId'] = booking_id
        conversation.transition_to(ConversationState.BOOKING_CONFIRMED)
        self._conversation_repo.save(conversation)
        
        # Generate success response
        booking_dict = {
            'bookingId': booking_id,
            'serviceId': service_id,
            'providerId': provider_id,
            'start': start.isoformat() + 'Z',
            'end': end.isoformat() + 'Z',
            'clientName': client_name,
            'clientEmail': client_email,
            'clientPhone': client_phone,
            'notes': notes
        }
        
        response = ResponseBuilder.success_message(booking_dict)
        
        return conversation, response

    def _handle_post_booking_reset(
        self,
        tenant_id: TenantId,
        conversation: Conversation
    ) -> dict:
        """
        Reset conversation state after a completed booking
        to allow the user to start over.
        """
        # Clear booking-specific context but preserve user info if desired (optional)
        # For now, we clear everything to ensure a clean slate
        conversation.context = {}

        # Transition to SERVICE_PENDING (skipping INIT as we are already "chatting")
        conversation.transition_to(ConversationState.SERVICE_PENDING)
        
        # We could return a specific "New Booking" message, or just the Greeting
        # Let's return a message inviting to book again
        return {
             'type': 'text',
             'text': '¿Te gustaría realizar una nueva reserva? Aquí tienes nuestros servicios disponibles.',
             'quick_replies': [
                 {'label': 'Sí, ver servicios', 'value': 'book'}
             ]
        }
