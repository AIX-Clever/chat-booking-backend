"""
Finite State Machine (FSM) for Chat Agent

Implements conversational flow for booking process
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime

from shared.domain.entities import (
    Conversation,
    ConversationState,
    TenantId
)
from shared.domain.exceptions import ValidationError


class StateTransition:
    """
    Represents a state transition with validation
    """
    
    def __init__(
        self,
        from_state: ConversationState,
        to_state: ConversationState,
        required_fields: list[str] = None
    ):
        self.from_state = from_state
        self.to_state = to_state
        self.required_fields = required_fields or []
    
    def can_transition(self, conversation: Conversation) -> tuple[bool, Optional[str]]:
        """
        Check if transition is valid
        
        Returns:
            (can_transition, error_message)
        """
        if conversation.state != self.from_state:
            return False, f"Cannot transition from {conversation.state.value} to {self.to_state.value}"
        
        # Check required fields in context
        context = conversation.context or {}
        missing = [f for f in self.required_fields if not context.get(f)]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"
        
        return True, None


class ChatFSM:
    """
    Finite State Machine for chat booking flow
    
    States:
    1. INIT: Initial state
    2. SERVICE_PENDING: Waiting for service selection
    3. SERVICE_SELECTED: Service chosen
    4. PROVIDER_PENDING: Waiting for provider selection
    5. PROVIDER_SELECTED: Provider chosen
    6. SLOT_PENDING: Waiting for time slot selection
    7. CONFIRM_PENDING: Waiting for booking confirmation
    8. BOOKING_CONFIRMED: Booking created successfully
    
    SOLID:
    - SRP: Only handles state transitions
    - OCP: Extensible with new states/transitions
    - LSP: Can be subclassed for custom flows
    - DIP: Works with Conversation entity abstraction
    """
    
    # Define valid state transitions
    TRANSITIONS = {
        ConversationState.INIT: [
            StateTransition(
                ConversationState.INIT,
                ConversationState.SERVICE_PENDING
            )
        ],
        ConversationState.SERVICE_PENDING: [
            StateTransition(
                ConversationState.SERVICE_PENDING,
                ConversationState.SERVICE_SELECTED,
                required_fields=['serviceId']
            )
        ],
        ConversationState.SERVICE_SELECTED: [
            StateTransition(
                ConversationState.SERVICE_SELECTED,
                ConversationState.PROVIDER_PENDING,
                required_fields=['serviceId']
            )
        ],
        ConversationState.PROVIDER_PENDING: [
            StateTransition(
                ConversationState.PROVIDER_PENDING,
                ConversationState.PROVIDER_SELECTED,
                required_fields=['serviceId', 'providerId']
            )
        ],
        ConversationState.PROVIDER_SELECTED: [
            StateTransition(
                ConversationState.PROVIDER_SELECTED,
                ConversationState.SLOT_PENDING,
                required_fields=['serviceId', 'providerId']
            )
        ],
        ConversationState.SLOT_PENDING: [
            StateTransition(
                ConversationState.SLOT_PENDING,
                ConversationState.CONFIRM_PENDING,
                required_fields=['serviceId', 'providerId', 'selectedSlot']
            )
        ],
        ConversationState.CONFIRM_PENDING: [
            StateTransition(
                ConversationState.CONFIRM_PENDING,
                ConversationState.BOOKING_CONFIRMED,
                required_fields=[
                    'serviceId', 'providerId', 'selectedSlot',
                    'clientName', 'clientEmail', 'bookingId'
                ]
            )
        ]
    }
    
    @classmethod
    def can_transition(
        cls,
        conversation: Conversation,
        to_state: ConversationState
    ) -> tuple[bool, Optional[str]]:
        """
        Check if conversation can transition to target state
        
        Args:
            conversation: Current conversation
            to_state: Target state
        
        Returns:
            (can_transition, error_message)
        """
        current_state = conversation.state
        
        # Get valid transitions for current state
        transitions = cls.TRANSITIONS.get(current_state, [])
        
        # Find matching transition
        for transition in transitions:
            if transition.to_state == to_state:
                return transition.can_transition(conversation)
        
        return False, f"No valid transition from {current_state.value} to {to_state.value}"
    
    @classmethod
    def get_next_states(cls, current_state: ConversationState) -> list[ConversationState]:
        """
        Get valid next states from current state
        
        Args:
            current_state: Current state
        
        Returns:
            List of valid next states
        """
        transitions = cls.TRANSITIONS.get(current_state, [])
        return [t.to_state for t in transitions]
    
    @classmethod
    def get_required_fields(
        cls,
        from_state: ConversationState,
        to_state: ConversationState
    ) -> list[str]:
        """
        Get required fields for state transition
        
        Args:
            from_state: Source state
            to_state: Target state
        
        Returns:
            List of required field names
        """
        transitions = cls.TRANSITIONS.get(from_state, [])
        for transition in transitions:
            if transition.to_state == to_state:
                return transition.required_fields
        return []
    
    @classmethod
    def validate_context(
        cls,
        state: ConversationState,
        context: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate context has required fields for state
        
        Args:
            state: Conversation state
            context: Conversation context data
        
        Returns:
            (is_valid, error_message)
        """
        # Accumulate required fields based on state progression
        required_by_state = {
            ConversationState.INIT: [],
            ConversationState.SERVICE_PENDING: [],
            ConversationState.SERVICE_SELECTED: ['serviceId'],
            ConversationState.PROVIDER_PENDING: ['serviceId'],
            ConversationState.PROVIDER_SELECTED: ['serviceId', 'providerId'],
            ConversationState.SLOT_PENDING: ['serviceId', 'providerId'],
            ConversationState.CONFIRM_PENDING: [
                'serviceId', 'providerId', 'selectedSlot',
                'clientName', 'clientEmail'
            ],
            ConversationState.BOOKING_CONFIRMED: [
                'serviceId', 'providerId', 'selectedSlot',
                'clientName', 'clientEmail', 'bookingId'
            ]
        }
        
        required_fields = required_by_state.get(state, [])
        missing = [f for f in required_fields if not context.get(f)]
        
        if missing:
            return False, f"Missing required fields for {state.value}: {', '.join(missing)}"
        
        return True, None


class MessageType(Enum):
    """Message types for responses"""
    TEXT = "text"
    OPTIONS = "options"
    CALENDAR = "calendar"
    FORM = "form"
    CONFIRMATION = "confirmation"
    SUCCESS = "success"
    ERROR = "error"


class ResponseBuilder:
    """
    Builds chat responses based on conversation state
    
    SOLID:
    - SRP: Only builds responses
    - OCP: Extensible with new response types
    """
    
    @staticmethod
    def greeting_message() -> dict:
        """Initial greeting message"""
        return {
            'type': MessageType.TEXT.value,
            'text': '¡Hola! 👋 Bienvenido a nuestro sistema de reservas. ¿En qué puedo ayudarte hoy?',
            'quick_replies': [
                {'label': 'Hacer una reserva', 'value': 'book'},
                {'label': 'Ver mis reservas', 'value': 'my_bookings'}
            ]
        }
    
    @staticmethod
    def category_selection_message(categories: list[str]) -> dict:
        """Ask user to select category"""
        return {
            'type': MessageType.OPTIONS.value,
            'text': '¿Qué tipo de servicio te interesa?',
            'options': [
                {'label': cat, 'value': cat} for cat in categories
            ]
        }
    
    @staticmethod
    def service_selection_message(services: list[dict]) -> dict:
        """Ask user to select service"""
        return {
            'type': MessageType.OPTIONS.value,
            'text': 'Perfecto. ¿Qué servicio específico deseas?',
            'options': [
                {
                    'label': f"{s['name']} - ${s['price']} ({s['duration']} min)",
                    'value': s['serviceId'],
                    'description': s.get('description')
                }
                for s in services
            ]
        }
    
    @staticmethod
    def provider_selection_message(providers: list[dict]) -> dict:
        """Ask user to select provider"""
        return {
            'type': MessageType.OPTIONS.value,
            'text': '¿Con qué profesional te gustaría agendar?',
            'options': [
                {
                    'label': p['name'],
                    'value': p['providerId'],
                    'description': p.get('bio')
                }
                for p in providers
            ]
        }
    
    @staticmethod
    def date_selection_message(available_slots: list[dict]) -> dict:
        """Ask user to select date/time"""
        return {
            'type': MessageType.CALENDAR.value,
            'text': '¿Cuándo te gustaría tu cita?',
            'slots': available_slots
        }
    
    @staticmethod
    def contact_info_message() -> dict:
        """Ask user for contact information"""
        return {
            'type': MessageType.FORM.value,
            'text': 'Para finalizar, necesito tus datos de contacto.',
            'fields': [
                {
                    'name': 'clientName',
                    'label': 'Nombre completo',
                    'type': 'text',
                    'required': True
                },
                {
                    'name': 'clientEmail',
                    'label': 'Email',
                    'type': 'email',
                    'required': True
                },
                {
                    'name': 'clientPhone',
                    'label': 'Teléfono',
                    'type': 'tel',
                    'required': False
                },
                {
                    'name': 'notes',
                    'label': 'Notas adicionales',
                    'type': 'textarea',
                    'required': False
                }
            ]
        }
    
    @staticmethod
    def confirmation_message(booking_details: dict) -> dict:
        """Show booking confirmation"""
        return {
            'type': MessageType.CONFIRMATION.value,
            'text': '¿Confirmas los datos de tu reserva?',
            'details': booking_details,
            'actions': [
                {'label': 'Confirmar', 'value': 'confirm', 'style': 'primary'},
                {'label': 'Modificar', 'value': 'modify', 'style': 'secondary'},
                {'label': 'Cancelar', 'value': 'cancel', 'style': 'danger'}
            ]
        }
    
    @staticmethod
    def success_message(booking: dict) -> dict:
        """Booking created successfully"""
        return {
            'type': MessageType.SUCCESS.value,
            'text': f'¡Reserva confirmada! 🎉\n\nTu número de reserva es: {booking["bookingId"]}\n\nTe hemos enviado un email de confirmación a {booking["clientEmail"]}',
            'booking': booking
        }
    
    @staticmethod
    def error_message(error: str) -> dict:
        """Error message"""
        return {
            'type': MessageType.ERROR.value,
            'text': f'Lo siento, ocurrió un error: {error}',
            'actions': [
                {'label': 'Reintentar', 'value': 'retry'},
                {'label': 'Volver al inicio', 'value': 'restart'}
            ]
        }
    
    @staticmethod
    def no_availability_message() -> dict:
        """No slots available"""
        return {
            'type': MessageType.TEXT.value,
            'text': 'Lo siento, no hay disponibilidad para este profesional en las próximas semanas. ¿Te gustaría elegir otro profesional?',
            'quick_replies': [
                {'label': 'Elegir otro profesional', 'value': 'change_provider'},
                {'label': 'Volver al inicio', 'value': 'restart'}
            ]
        }
