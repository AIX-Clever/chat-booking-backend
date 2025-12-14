"""
Booking Lambda Handler (Adapter Layer)

AWS Lambda function for booking operations
"""

import json
from datetime import datetime

from shared.infrastructure.dynamodb_repositories import (
    DynamoDBBookingRepository,
    DynamoDBServiceRepository,
    DynamoDBProviderRepository,
    DynamoDBTenantRepository,
    DynamoDBConversationRepository
)
from shared.domain.entities import TenantId
from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError,
    TenantNotActiveError,
    ServiceNotAvailableError,
    ProviderNotAvailableError,
    SlotNotAvailableError,
    ConflictError
)
from shared.utils import Logger, success_response, error_response, parse_iso_datetime, extract_appsync_event

from service import BookingService, BookingQueryService


# Initialize dependencies (singleton pattern)
booking_repo = DynamoDBBookingRepository()
service_repo = DynamoDBServiceRepository()
provider_repo = DynamoDBProviderRepository()
tenant_repo = DynamoDBTenantRepository()
conversation_repo = DynamoDBConversationRepository()

booking_service = BookingService(
    booking_repo,
    service_repo,
    provider_repo,
    tenant_repo
)

booking_query_service = BookingQueryService(booking_repo, conversation_repo)

logger = Logger()


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for booking operations
    
    Supports operations:
    - createBooking: Create new booking with validation
    - confirmBooking: Confirm pending booking
    - cancelBooking: Cancel booking
    - getBooking: Get booking details
    - listBookingsByProvider: List bookings for provider
    - listBookingsByClient: List bookings for client
    - getBookingByConversation: Get booking from conversation
    """
    try:
        field, tenant_id_str, input_data = extract_appsync_event(event)

        tenant_id = TenantId(tenant_id_str)

        logger.info(
            "Booking operation",
            field=field,
            tenant_id=tenant_id_str
        )

        # Route to appropriate handler
        if field == 'createBooking':
            return handle_create_booking(tenant_id, input_data)
        
        elif field == 'confirmBooking':
            return handle_confirm_booking(tenant_id, input_data)
        
        elif field == 'cancelBooking':
            return handle_cancel_booking(tenant_id, input_data)
        
        elif field == 'getBooking':
            return handle_get_booking(tenant_id, input_data)
        
        elif field == 'listBookingsByProvider':
            return handle_list_by_provider(tenant_id, input_data)
        
        elif field == 'listBookingsByClient':
            return handle_list_by_client(tenant_id, input_data)
        
        elif field == 'getBookingByConversation':
            return handle_get_by_conversation(tenant_id, input_data)
        
        else:
            return error_response(f"Unknown operation: {field}", 400)

    except EntityNotFoundError as e:
        logger.warning("Entity not found", error=str(e))
        return error_response(str(e), 404)

    except (
        TenantNotActiveError,
        ServiceNotAvailableError,
        ProviderNotAvailableError,
        SlotNotAvailableError
    ) as e:
        logger.warning("Business rule violation", error=str(e))
        return error_response(str(e), 400)

    except ValidationError as e:
        logger.warning("Validation error", error=str(e))
        return error_response(str(e), 400)

    except ConflictError as e:
        logger.warning("Conflict error", error=str(e))
        return error_response(str(e), 409)

    except ValueError as e:
        logger.warning("Invalid input", error=str(e))
        return error_response(str(e), 400)

    except Exception as e:
        logger.error("Unexpected error", error=str(e))
        import traceback
        traceback.print_exc()
        return error_response(f"Internal server error: {str(e)}", 500)


def handle_create_booking(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Create a new booking
    
    Input:
    {
        "serviceId": "svc_123",
        "providerId": "pro_456",
        "start": "2025-12-05T10:00:00Z",
        "end": "2025-12-05T11:00:00Z",
        "clientName": "John Doe",
        "clientEmail": "john@example.com",
        "clientPhone": "+1234567890",
        "notes": "First time client",
        "conversationId": "conv_789"
    }
    """
    # Validate required fields
    required = ['serviceId', 'providerId', 'start', 'end', 'clientName', 'clientEmail']
    missing = [f for f in required if not input_data.get(f)]
    if missing:
        return error_response(f"Missing required fields: {', '.join(missing)}", 400)

    # Parse dates
    try:
        start = parse_iso_datetime(input_data['start'])
        end = parse_iso_datetime(input_data['end'])
    except ValueError as e:
        return error_response(f"Invalid date format: {e}", 400)

    # Create booking
    booking = booking_service.create_booking(
        tenant_id=tenant_id,
        service_id=input_data['serviceId'],
        provider_id=input_data['providerId'],
        start=start,
        end=end,
        client_name=input_data['clientName'],
        client_email=input_data['clientEmail'],
        client_phone=input_data.get('clientPhone'),
        notes=input_data.get('notes'),
        conversation_id=input_data.get('conversationId')
    )

    return success_response(booking_to_dict(booking))


def handle_confirm_booking(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Confirm a booking
    
    Input:
    {
        "bookingId": "bkg_123"
    }
    """
    booking_id = input_data.get('bookingId')
    if not booking_id:
        return error_response("Missing bookingId", 400)

    booking = booking_service.confirm_booking(tenant_id, booking_id)
    return success_response(booking_to_dict(booking))


def handle_cancel_booking(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Cancel a booking
    
    Input:
    {
        "bookingId": "bkg_123",
        "reason": "Client requested cancellation"
    }
    """
    booking_id = input_data.get('bookingId')
    if not booking_id:
        return error_response("Missing bookingId", 400)

    booking = booking_service.cancel_booking(
        tenant_id,
        booking_id,
        input_data.get('reason')
    )
    return success_response(booking_to_dict(booking))


def handle_get_booking(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Get booking details
    
    Input:
    {
        "bookingId": "bkg_123"
    }
    """
    booking_id = input_data.get('bookingId')
    if not booking_id:
        return error_response("Missing bookingId", 400)

    booking = booking_query_service.get_booking(tenant_id, booking_id)
    return success_response(booking_to_dict(booking))


def handle_list_by_provider(tenant_id: TenantId, input_data: dict) -> dict:
    """
    List bookings for provider in date range
    
    Input:
    {
        "providerId": "pro_456",
        "startDate": "2025-12-01T00:00:00Z",
        "endDate": "2025-12-31T23:59:59Z"
    }
    """
    provider_id = input_data.get('providerId')
    start_str = input_data.get('startDate')
    end_str = input_data.get('endDate')

    if not all([provider_id, start_str, end_str]):
        return error_response("Missing required fields: providerId, startDate, endDate", 400)

    try:
        start_date = parse_iso_datetime(start_str)
        end_date = parse_iso_datetime(end_str)
    except ValueError as e:
        return error_response(f"Invalid date format: {e}", 400)

    bookings = booking_query_service.list_by_provider(
        tenant_id,
        provider_id,
        start_date,
        end_date
    )

    return success_response([booking_to_dict(b) for b in bookings])


def handle_list_by_client(tenant_id: TenantId, input_data: dict) -> dict:
    """
    List bookings for client
    
    Input:
    {
        "clientEmail": "john@example.com"
    }
    """
    client_email = input_data.get('clientEmail')
    if not client_email:
        return error_response("Missing clientEmail", 400)

    bookings = booking_query_service.list_by_client(tenant_id, client_email)
    return success_response([booking_to_dict(b) for b in bookings])


def handle_get_by_conversation(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Get booking by conversation ID
    
    Input:
    {
        "conversationId": "conv_789"
    }
    """
    conversation_id = input_data.get('conversationId')
    if not conversation_id:
        return error_response("Missing conversationId", 400)

    booking = booking_query_service.get_booking_by_conversation(tenant_id, conversation_id)
    if not booking:
        return error_response("No booking found for this conversation", 404)

    return success_response(booking_to_dict(booking))


def booking_to_dict(booking) -> dict:
    """Convert Booking entity to dictionary"""
    return {
        'bookingId': booking.booking_id,
        'tenantId': booking.tenant_id.value,
        'serviceId': booking.service_id,
        'providerId': booking.provider_id,
        'start': booking.start.isoformat() + 'Z',
        'end': booking.end.isoformat() + 'Z',
        'status': booking.status.value,
        'clientName': booking.client_name,
        'clientEmail': booking.client_email,
        'clientPhone': booking.client_phone,
        'notes': booking.notes,
        'conversationId': booking.conversation_id,
        'paymentStatus': booking.payment_status.value,
        'totalAmount': booking.total_amount,
        'createdAt': booking.created_at.isoformat() + 'Z',
        'updatedAt': booking.updated_at.isoformat() + 'Z'
    }
