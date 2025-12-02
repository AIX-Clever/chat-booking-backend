"""
Unit tests for chat agent FSM
"""

import pytest
from datetime import datetime
from shared.domain.entities import (
    TenantId,
    Conversation,
    ConversationState
)
from chat_agent.fsm import ChatFSM, StateTransition, ResponseBuilder, MessageType


class TestStateTransition:
    """Test StateTransition class"""
    
    def test_valid_transition_without_required_fields(self):
        """Test transition without required fields"""
        transition = StateTransition(
            ConversationState.INIT,
            ConversationState.SERVICE_PENDING
        )
        
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.INIT,
            context={},
            messages=[],
            channel="widget",
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        can_transition, error = transition.can_transition(conversation)
        assert can_transition
        assert error is None
    
    def test_valid_transition_with_required_fields(self):
        """Test transition with required fields present"""
        transition = StateTransition(
            ConversationState.SERVICE_SELECTED,
            ConversationState.PROVIDER_PENDING,
            required_fields=['serviceId']
        )
        
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.SERVICE_SELECTED,
            context={'serviceId': 'svc_123'},
            messages=[],
            channel="widget",
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        can_transition, error = transition.can_transition(conversation)
        assert can_transition
        assert error is None
    
    def test_invalid_transition_missing_fields(self):
        """Test transition with missing required fields"""
        transition = StateTransition(
            ConversationState.SERVICE_SELECTED,
            ConversationState.PROVIDER_PENDING,
            required_fields=['serviceId']
        )
        
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.SERVICE_SELECTED,
            context={},  # Missing serviceId
            messages=[],
            channel="widget",
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        can_transition, error = transition.can_transition(conversation)
        assert not can_transition
        assert "serviceId" in error


class TestChatFSM:
    """Test ChatFSM state machine"""
    
    def test_can_transition_valid_path(self):
        """Test valid state transition"""
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.INIT,
            context={},
            messages=[],
            channel="widget",
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        can_transition, error = ChatFSM.can_transition(
            conversation,
            ConversationState.SERVICE_PENDING
        )
        
        assert can_transition
        assert error is None
    
    def test_can_transition_invalid_path(self):
        """Test invalid state transition"""
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.INIT,
            context={},
            messages=[],
            channel="widget",
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        can_transition, error = ChatFSM.can_transition(
            conversation,
            ConversationState.BOOKING_CONFIRMED
        )
        
        assert not can_transition
        assert error is not None
    
    def test_get_next_states(self):
        """Test getting valid next states"""
        next_states = ChatFSM.get_next_states(ConversationState.INIT)
        
        assert len(next_states) > 0
        assert ConversationState.SERVICE_PENDING in next_states
    
    def test_get_required_fields(self):
        """Test getting required fields for transition"""
        fields = ChatFSM.get_required_fields(
            ConversationState.SERVICE_PENDING,
            ConversationState.SERVICE_SELECTED
        )
        
        assert 'serviceId' in fields
    
    def test_validate_context_valid(self):
        """Test context validation with valid data"""
        context = {
            'serviceId': 'svc_123',
            'providerId': 'pro_123',
            'selectedSlot': {'start': '2025-12-15T10:00:00Z'},
            'clientName': 'John Doe',
            'clientEmail': 'john@example.com'
        }
        
        is_valid, error = ChatFSM.validate_context(
            ConversationState.CONFIRM_PENDING,
            context
        )
        
        assert is_valid
        assert error is None
    
    def test_validate_context_missing_fields(self):
        """Test context validation with missing fields"""
        context = {
            'serviceId': 'svc_123'
            # Missing other required fields
        }
        
        is_valid, error = ChatFSM.validate_context(
            ConversationState.CONFIRM_PENDING,
            context
        )
        
        assert not is_valid
        assert error is not None


class TestResponseBuilder:
    """Test ResponseBuilder"""
    
    def test_greeting_message(self):
        """Test greeting message generation"""
        response = ResponseBuilder.greeting_message()
        
        assert response['type'] == MessageType.TEXT.value
        assert 'text' in response
        assert 'quick_replies' in response
    
    def test_service_selection_message(self):
        """Test service selection message"""
        services = [
            {
                'serviceId': 'svc_1',
                'name': 'Massage',
                'price': 50.0,
                'duration': 60,
                'description': '60 min massage'
            }
        ]
        
        response = ResponseBuilder.service_selection_message(services)
        
        assert response['type'] == MessageType.OPTIONS.value
        assert len(response['options']) == 1
        assert response['options'][0]['value'] == 'svc_1'
    
    def test_provider_selection_message(self):
        """Test provider selection message"""
        providers = [
            {
                'providerId': 'pro_1',
                'name': 'John Doe',
                'bio': 'Expert therapist'
            }
        ]
        
        response = ResponseBuilder.provider_selection_message(providers)
        
        assert response['type'] == MessageType.OPTIONS.value
        assert len(response['options']) == 1
    
    def test_contact_info_message(self):
        """Test contact info message"""
        response = ResponseBuilder.contact_info_message()
        
        assert response['type'] == MessageType.FORM.value
        assert len(response['fields']) >= 2
        
        # Check required fields
        field_names = [f['name'] for f in response['fields']]
        assert 'clientName' in field_names
        assert 'clientEmail' in field_names
    
    def test_confirmation_message(self):
        """Test confirmation message"""
        booking_details = {
            'service': 'Massage',
            'provider': 'John Doe',
            'datetime': '2025-12-15T10:00:00Z',
            'duration': 60,
            'price': 50.0
        }
        
        response = ResponseBuilder.confirmation_message(booking_details)
        
        assert response['type'] == MessageType.CONFIRMATION.value
        assert 'details' in response
        assert 'actions' in response
    
    def test_success_message(self):
        """Test success message"""
        booking = {
            'bookingId': 'bkg_123',
            'clientEmail': 'john@example.com'
        }
        
        response = ResponseBuilder.success_message(booking)
        
        assert response['type'] == MessageType.SUCCESS.value
        assert 'bkg_123' in response['text']
    
    def test_error_message(self):
        """Test error message"""
        response = ResponseBuilder.error_message("Something went wrong")
        
        assert response['type'] == MessageType.ERROR.value
        assert 'Something went wrong' in response['text']
        assert 'actions' in response
