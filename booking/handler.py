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
from shared.metrics import MetricsService
from shared.infrastructure.notifications import EmailService
import os

from service import BookingService, BookingQueryService


# Initialize dependencies (singleton pattern)
booking_repo = DynamoDBBookingRepository()
service_repo = DynamoDBServiceRepository()
provider_repo = DynamoDBProviderRepository()
tenant_repo = DynamoDBTenantRepository()
conversation_repo = DynamoDBConversationRepository()
metrics_service = MetricsService()
email_service = EmailService(region_name=os.environ.get('AWS_REGION', 'us-east-1'))

booking_service = BookingService(
    booking_repo,
    service_repo,
    provider_repo,
    tenant_repo,
    limit_service=None, # TenantLimitService is opt-in for now or injected if available
    email_service=email_service
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
        
        elif field == 'markAsNoShow':
            return handle_mark_as_no_show(tenant_id, input_data)
        
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
    
    # Track booking metrics
    try:
        metrics_service.increment_booking(
            tenant_id=tenant_id.value,
            service_id=input_data['serviceId'],
            provider_id=input_data['providerId'],
            amount=booking.total_amount or 0
        )
        metrics_service.update_booking_status(tenant_id.value, None, booking.status.value)
    except Exception as e:
        logger.warning("Failed to track booking metrics", error=str(e))

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

    # Get old status before confirming
    old_booking = booking_query_service.get_booking(tenant_id, booking_id)
    old_status = old_booking.status.value if old_booking else None

    booking = booking_service.confirm_booking(tenant_id, booking_id)
    
    # Track status change
    try:
        metrics_service.update_booking_status(tenant_id.value, old_status, booking.status.value)
    except Exception as e:
        logger.warning("Failed to track booking status change", error=str(e))
    
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

    # Get old status before cancelling
    old_booking = booking_query_service.get_booking(tenant_id, booking_id)
    old_status = old_booking.status.value if old_booking else None

    booking = booking_service.cancel_booking(
        tenant_id,
        booking_id,
        input_data.get('reason')
    )
    
    # Track status change (old_status -> CANCELLED)
    try:
        metrics_service.update_booking_status(tenant_id.value, old_status, booking.status.value)
    except Exception as e:
        logger.warning("Failed to track booking cancellation", error=str(e))
    
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

    serialized_bookings = [booking_to_dict(b) for b in bookings]
    logger.info("Serialized Bookings Result", count=len(serialized_bookings), sample=serialized_bookings[0] if serialized_bookings else None)
    return success_response(serialized_bookings)


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


def handle_mark_as_no_show(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Mark a booking as no show
    
    Input:
    {
        "bookingId": "bkg_123"
    }
    """
    booking_id = input_data.get('bookingId')
    if not booking_id:
        return error_response("Missing bookingId", 400)

    # Get old status before update
    old_booking = booking_query_service.get_booking(tenant_id, booking_id)
    old_status = old_booking.status.value if old_booking else None

    booking = booking_service.mark_as_no_show(tenant_id, booking_id)
    
    # Track status change
    try:
        metrics_service.update_booking_status(tenant_id.value, old_status, booking.status.value)
    except Exception as e:
        logger.warning("Failed to track booking status change", error=str(e))
    
    return success_response(booking_to_dict(booking))


def booking_to_dict(booking) -> dict:
    """Convert Booking entity to dictionary"""
    # Ensure datetimes are timezone-aware for AppSync AWSDateTime compatibility
    from datetime import UTC
    
    start_time = booking.start_time
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=UTC)
    
    end_time = booking.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=UTC)
    
    created_at = booking.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    
    updated_at = booking.updated_at if booking.updated_at else booking.created_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    
    return {
        'bookingId': booking.booking_id,
        'tenantId': booking.tenant_id.value,
        'serviceId': booking.service_id,
        'providerId': booking.provider_id,
        'start': start_time.isoformat(),
        'end': end_time.isoformat(),
        'status': booking.status.value,
        'clientName': booking.customer_info.name or "Unknown Client",
        'clientEmail': booking.customer_info.email or "no-email@example.com",
        'clientPhone': booking.customer_info.phone,
        'notes': booking.notes,
        'conversationId': booking.conversation_id,
        'paymentStatus': booking.payment_status.value,
        'paymentIntentId': booking.payment_intent_id,
        'clientSecret': booking.payment_client_secret,
        'totalAmount': booking.total_amount if booking.total_amount is not None else 0.0,
        'createdAt': created_at.isoformat(),
        'updatedAt': updated_at.isoformat()
    }
