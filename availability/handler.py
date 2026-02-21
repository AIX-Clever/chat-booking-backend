"""
Availability Lambda Handler (Adapter Layer)

AWS Lambda function for availability operations
"""

import json
import os
from datetime import datetime

from shared.infrastructure.dynamodb_repositories import (
    DynamoDBServiceRepository,
    DynamoDBProviderRepository,
    DynamoDBBookingRepository,
    DynamoDBProviderIntegrationRepository,
)
from shared.infrastructure.availability_repository import DynamoDBAvailabilityRepository
from shared.domain.entities import TenantId
from shared.domain.exceptions import (
    EntityNotFoundError,
    ServiceNotAvailableError,
    ProviderNotAvailableError,
    ValidationError,
)
from shared.utils import (
    Logger,
    success_response,
    error_response,
    parse_iso_datetime,
    extract_appsync_event,
    to_iso_string,
)

from shared.application.availability_service import AvailabilityService, AvailabilityManagementService


# Initialize dependencies (singleton pattern)
availability_repo = DynamoDBAvailabilityRepository()
booking_repo = DynamoDBBookingRepository()
service_repo = DynamoDBServiceRepository()
provider_repo = DynamoDBProviderRepository()
provider_integration_repo = DynamoDBProviderIntegrationRepository()

# Read slot interval from environment (default 15 minutes)
slot_interval = int(os.environ.get("SLOT_INTERVAL_MINUTES", "15"))

availability_service = AvailabilityService(
    availability_repo,
    booking_repo,
    service_repo,
    provider_repo,
    provider_integration_repo,
    slot_interval_minutes=slot_interval,
)

availability_mgmt_service = AvailabilityManagementService(availability_repo)

logger = Logger()
logger.info("Availability Lambda initialized", version="1.1")


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for availability operations

    Supports operations:
    - getAvailableSlots: Calculate available time slots (widget/public)
    - setProviderAvailability: Set availability schedule (admin)
    """
    try:
        field, tenant_id_str, input_data = extract_appsync_event(event)

        tenant_id = TenantId(tenant_id_str)

        logger.info("Availability operation", field=field, tenant_id=tenant_id_str)

        # Route to appropriate handler
        if field == "getAvailableSlots":
            return handle_get_available_slots(tenant_id, input_data)

        elif field == "setProviderAvailability":
            return handle_set_availability(tenant_id, input_data)

        elif field == "getProviderAvailability":
            return handle_get_provider_availability(tenant_id, input_data)

        elif field == "setProviderExceptions":
            return handle_set_provider_exceptions(tenant_id, input_data)

        elif field == "getProviderExceptions":
            return handle_get_provider_exceptions(tenant_id, input_data)

        else:
            return error_response(f"Unknown operation: {field}", 400)

    except EntityNotFoundError as e:
        logger.warning("Entity not found", error=str(e))
        return error_response(str(e), 404)

    except (ServiceNotAvailableError, ProviderNotAvailableError) as e:
        logger.warning("Availability error", error=str(e))
        return error_response(str(e), 400)

    except ValidationError as e:
        logger.warning("Validation error", error=str(e))
        return error_response(str(e), 400)

    except ValueError as e:
        logger.warning("Invalid input", error=str(e))
        return error_response(str(e), 400)

    except Exception as e:
        logger.error("Unexpected error", error=e)
        raise e  # Re-raise to let AppSync handle it (or show the original error)


def handle_get_available_slots(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Get available time slots

    Input:
    {
        "serviceId": "svc_123",
        "providerId": "pro_456",
        "from": "2025-12-01T00:00:00Z",
        "to": "2025-12-07T23:59:59Z"
    }
    """
    # Validate required fields
    service_id = input_data.get("serviceId")
    provider_id = input_data.get("providerId")
    from_str = input_data.get("from")
    to_str = input_data.get("to")

    if not all([service_id, provider_id, from_str, to_str]):
        return error_response(
            "Missing required fields: serviceId, providerId, from, to", 400
        )

    # Parse dates
    try:
        from_date = parse_iso_datetime(from_str)
        to_date = parse_iso_datetime(to_str)
    except ValueError as e:
        return error_response(f"Invalid date format: {e}", 400)

    # Validate date range
    if from_date >= to_date:
        return error_response("from date must be before to date", 400)

    # Calculate slots
    slots = availability_service.get_available_slots(
        tenant_id, service_id, provider_id, from_date, to_date
    )

    # Convert to response format
    slots_data = [
        {
            "providerId": provider_id,
            "serviceId": service_id,
            "start": to_iso_string(slot.start),
            "end": to_iso_string(slot.end),
            "isAvailable": slot.is_available,
        }
        for slot in slots
    ]

    return success_response(slots_data)


def handle_set_availability(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Set provider availability schedule (admin operation)

    Input:
    {
        "providerId": "pro_456",
        "dayOfWeek": "MON",
        "timeRanges": [
            {"startTime": "09:00", "endTime": "13:00"},
            {"startTime": "15:00", "endTime": "19:00"}
        ],
        "breaks": [
            {"startTime": "11:00", "endTime": "11:15"}
        ]
    }
    """
    provider_id = input_data.get("providerId")
    day_of_week = input_data.get("dayOfWeek")
    time_ranges = input_data.get("timeRanges", [])
    breaks = input_data.get("breaks", [])
    exceptions = input_data.get("exceptions", [])

    logger.info("handle_set_availability input", input_data=input_data)

    if not all([provider_id, day_of_week]):  # time_ranges can be empty (e.g. day off)
        return error_response("Missing required fields: providerId, dayOfWeek", 400)

    # Validate day of week
    valid_days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    if day_of_week.upper() not in valid_days:
        return error_response(
            f"Invalid dayOfWeek. Must be one of: {', '.join(valid_days)}", 400
        )

    # Set availability
    availability = availability_mgmt_service.set_provider_availability(
        tenant_id, provider_id, day_of_week, time_ranges, breaks, exceptions
    )

    # Convert to response format
    response_data = {
        "providerId": availability.provider_id,
        "dayOfWeek": availability.day_of_week,
        "timeRanges": [
            {"startTime": tr.start_time, "endTime": tr.end_time}
            for tr in availability.time_ranges
        ],
        "breaks": [
            {"startTime": br.start_time, "endTime": br.end_time}
            for br in availability.breaks
        ],
        "exceptions": [
            {
                "date": ex if isinstance(ex, str) else ex.date,
                "timeRanges": [
                    {"startTime": tr.start_time, "endTime": tr.end_time}
                    for tr in (ex.time_ranges if not isinstance(ex, str) and hasattr(ex, "time_ranges") else [])
                ]
            }
            for ex in availability.exceptions
        ] if availability.exceptions else [],
    }

    return success_response(response_data)


def handle_get_provider_availability(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Get provider availability schedule

    Input:
    {
        "providerId": "pro_456"
    }
    """
    provider_id = input_data.get("providerId")

    if not provider_id:
        return error_response("Missing required field: providerId", 400)

    # Get availability from repository
    schedule = availability_repo.get_provider_availability(tenant_id, provider_id)

    # Get exceptions separately (now stored in dedicated item)
    exception_entities = availability_repo.get_provider_exceptions(
        tenant_id, provider_id
    )
    serialized_exceptions = []
    for ex in exception_entities:
        # Handle both dict and object (entity)
        if isinstance(ex, dict):
            serialized_exceptions.append({
                "date": ex.get("date"),
                "timeRanges": [
                    {"startTime": tr["startTime"], "endTime": tr["endTime"]} 
                    if isinstance(tr, dict) else 
                    {"startTime": tr.start_time, "endTime": tr.end_time}
                    for tr in ex.get("timeRanges", [])
                ]
            })
        else:
             serialized_exceptions.append({
                "date": ex.date,
                "timeRanges": [
                    {"startTime": tr.start_time, "endTime": tr.end_time}
                    for tr in ex.time_ranges
                ]
            })

    # Convert to response format
    response_data = []
    for avail in schedule:
        response_data.append(
            {
                "providerId": avail.provider_id,
                "dayOfWeek": avail.day_of_week,
                "timeRanges": [
                    {"startTime": tr.start_time, "endTime": tr.end_time}
                    for tr in avail.time_ranges
                ],
                "breaks": [
                    {"startTime": br.start_time, "endTime": br.end_time}
                    for br in avail.breaks
                ],
                "exceptions": serialized_exceptions,  # Include provider-level exceptions in first item
            }
        )

    return success_response(response_data)


def handle_set_provider_exceptions(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Set provider exception dates (days off)

    Input:
    {
        "providerId": "pro_456",
        "exceptions": [{"date": "2024-12-25", "timeRanges": []}]
    }
    """
    provider_id = input_data.get("providerId")
    exceptions = input_data.get("exceptions", [])

    if not provider_id:
        return error_response("Missing required field: providerId", 400)

    # Use Service Layer
    updated_exceptions = availability_mgmt_service.set_provider_exceptions(
        tenant_id, provider_id, exceptions
    )

    # Serialize entities for response
    logger.info(f"DEBUG: SERIALIZATION FIX V2 - Count: {len(updated_exceptions)}")
    
    final_exceptions_list = []
    for ex in updated_exceptions:
        if isinstance(ex, dict):
            final_exceptions_list.append({
                "date": ex.get("date"),
                "timeRanges": ex.get("timeRanges", [])
            })
        else:
            final_exceptions_list.append({
                "date": ex.date,
                "timeRanges": [{"startTime": tr.start_time, "endTime": tr.end_time} for tr in ex.time_ranges] if ex.time_ranges else []
            })

    result = {"providerId": provider_id, "exceptions": final_exceptions_list}
    logger.info("Returning result", result_keys=list(result.keys()))
    
    return success_response(result)


def handle_get_provider_exceptions(tenant_id: TenantId, input_data: dict) -> dict:
    """
    Get provider exception dates

    Input:
    {
        "providerId": "pro_456"
    }
    """
    provider_id = input_data.get("providerId")

    if not provider_id:
        return error_response("Missing required field: providerId", 400)

    # Use Service Layer
    exceptions = availability_mgmt_service.get_provider_exceptions(
        tenant_id, provider_id
    )

    # Deserialize entities for response
    # Deserialize entities for response
    serialized_exceptions = []
    for ex in exceptions:
         if isinstance(ex, dict):
            serialized_exceptions.append({
                "date": ex.get("date"),
                "timeRanges": [
                     {"startTime": tr["startTime"], "endTime": tr["endTime"]} 
                    if isinstance(tr, dict) else 
                    {"startTime": tr.start_time, "endTime": tr.end_time}
                    for tr in ex.get("timeRanges", [])
                ]
            })
         else:
            serialized_exceptions.append({
                "date": ex.date,
                "timeRanges": [
                    {"startTime": tr.start_time, "endTime": tr.end_time}
                    for tr in ex.time_ranges
                ],
            })

    # Return list directly to match GraphQL schema [ProviderException!]!
    return success_response(serialized_exceptions)
