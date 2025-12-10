"""
Chat Agent Lambda Handler (Adapter Layer)

AWS Lambda function for conversational booking flow
"""

import json
import sys
import os

# Add parent directory to path for shared imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime
from shared.infrastructure.dynamodb_repositories import (
    DynamoDBConversationRepository,
    DynamoDBServiceRepository,
    DynamoDBProviderRepository,
    DynamoDBBookingRepository
)
from shared.infrastructure.availability_repository import DynamoDBAvailabilityRepository
from shared.domain.entities import TenantId
from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError
)
from shared.utils import Logger, success_response, error_response

from service import ChatAgentService


# Initialize dependencies (singleton pattern)
conversation_repo = DynamoDBConversationRepository()
service_repo = DynamoDBServiceRepository()
provider_repo = DynamoDBProviderRepository()
booking_repo = DynamoDBBookingRepository()
availability_repo = DynamoDBAvailabilityRepository()

chat_agent_service = ChatAgentService(
    conversation_repo,
    service_repo,
    provider_repo,
    booking_repo,
    availability_repo
)

logger = Logger()


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for chat agent operations
    
    Supports operations:
    - startConversation: Initialize new conversation
    - sendMessage: Process user message and advance FSM
    - confirmBooking: Finalize booking creation
    - getConversation: Get conversation state
    """
    try:
        field = event.get('field')
        tenant_id_str = event.get('tenantId')
        input_data = event.get('input', {})

        if not tenant_id_str:
            return error_response("Missing tenantId", 400)

        tenant_id = TenantId(tenant_id_str)

        logger.info(
            "Chat agent operation",
            field=field,
            tenant_id=tenant_id_str
        )

        # Route to appropriate handler
        if field == 'startConversation':
            return handle_start_conversation(tenant_id, input_data)
        
        elif field == 'sendMessage':
            return handle_send_message(tenant_id, input_data)
        
        elif field == 'confirmBooking':
            return handle_confirm_booking(tenant_id, input_data)
        
        elif field == 'getConversation':
            return handle_get_conversation(tenant_id, input_data)
        
        else:
            return error_response(f"Unknown operation: {field}", 400)

    except EntityNotFoundError as e:
        logger.warning("Entity not found", error=str(e))
        return error_response(str(e), 404)

    except ValidationError as e:
        logger.warning("Validation error", error=str(e))
        return error_response(str(e), 400)

    except ValueError as e:
        logger.warning("Invalid input", error=str(e))
        return error_response(str(e), 400)

    except Exception as e:
        logger.error("Unexpected error", error=e)
        return error_response("Internal server error", 500)


def handle_start_conversation(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Start a new conversation
    
    Input:
    {
        "channel": "widget",
        "metadata": {
            "userAgent": "...",
            "referrer": "..."
        }
    }
    """
    channel = input_data.get('channel', 'widget')
    metadata = input_data.get('metadata')
    
    conversation, response = chat_agent_service.start_conversation(
        tenant_id,
        channel,
        metadata
    )
    
    return success_response({
        'conversation': conversation_to_dict(conversation),
        'response': response
    })


def handle_send_message(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Process user message
    
    Input:
    {
        "conversationId": "conv_123",
        "message": "Quiero agendar una cita",
        "messageType": "text",
        "userData": {
            "serviceId": "svc_456",
            "providerId": "pro_789",
            "selectedSlot": {...},
            "clientName": "...",
            "clientEmail": "..."
        }
    }
    """
    conversation_id = input_data.get('conversationId')
    message = input_data.get('message')
    message_type = input_data.get('messageType', 'text')
    user_data = input_data.get('userData')
    
    if not conversation_id or not message:
        return error_response("Missing conversationId or message", 400)
    
    conversation, response = chat_agent_service.process_message(
        tenant_id,
        conversation_id,
        message,
        message_type,
        user_data
    )
    
    return success_response({
        'conversation': conversation_to_dict(conversation),
        'response': response
    })


def handle_confirm_booking(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Confirm booking creation
    
    Input:
    {
        "conversationId": "conv_123"
    }
    """
    conversation_id = input_data.get('conversationId')
    
    if not conversation_id:
        return error_response("Missing conversationId", 400)
    
    conversation, response = chat_agent_service.confirm_booking(
        tenant_id,
        conversation_id
    )
    
    return success_response({
        'conversation': conversation_to_dict(conversation),
        'response': response
    })


def handle_get_conversation(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Get conversation state
    
    Input:
    {
        "conversationId": "conv_123"
    }
    """
    conversation_id = input_data.get('conversationId')
    
    if not conversation_id:
        return error_response("Missing conversationId", 400)
    
    conversation = conversation_repo.get_by_id(tenant_id, conversation_id)
    if not conversation:
        return error_response("Conversation not found", 404)
    
    return success_response(conversation_to_dict(conversation))


def conversation_to_dict(conversation) -> dict:
    """Convert Conversation entity to dictionary"""
    return {
        'conversationId': conversation.conversation_id,
        'tenantId': conversation.tenant_id.value,
        'state': conversation.state.value,
        'context': conversation.context,
        'messages': conversation.messages,
        'channel': conversation.channel,
        'metadata': conversation.metadata,
        'createdAt': conversation.created_at.isoformat() + 'Z',
        'updatedAt': conversation.updated_at.isoformat() + 'Z'
    }
