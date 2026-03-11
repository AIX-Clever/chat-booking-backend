"""
Waitlist API Lambda Handler (Adapter Layer)

AWS Lambda function for AppSync Waitlist API
"""

from shared.domain.exceptions import (
    EntityNotFoundError,
    ValidationError,
    TenantNotActiveError,
    ServiceNotAvailableError,
    ProviderNotAvailableError,
    ConflictError,
)
from shared.utils import (
    Logger,
    success_response,
    error_response,
    extract_appsync_event,
)
from shared.infrastructure.dynamodb_repositories import (
    DynamoDBWaitingListRepository,
    DynamoDBTenantRepository,
    DynamoDBProviderRepository,
    DynamoDBAvailabilityRepository,
    DynamoDBServiceRepository,
    DynamoDBBookingRepository,
    DynamoDBProviderIntegrationRepository
)
from shared.application.waitlist_service import WaitlistService
from shared.application.availability_service import AvailabilityService

# Initialize dependencies
waitlist_repo = DynamoDBWaitingListRepository()
tenant_repo = DynamoDBTenantRepository()
provider_repo = DynamoDBProviderRepository()
availability_repo = DynamoDBAvailabilityRepository()
service_repo = DynamoDBServiceRepository()
booking_repo = DynamoDBBookingRepository()
provider_integration_repo = DynamoDBProviderIntegrationRepository()

availability_service = AvailabilityService(
    availability_repo,
    booking_repo,
    service_repo,
    provider_repo,
    provider_integration_repo
)

waitlist_service = WaitlistService(
    waitlist_repo,
    tenant_repo,
    provider_repo,
    availability_service
)

logger = Logger()


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for Waitlist GraphQL API operations

    Supports operations:
    - getWaitingListByService: List waitlist for a specific service (Admin PRO)
    - addToWaitingList: Add a client to waitlist (Public/Chat Agent)
    - removeWaitingListEntry: Remove entry (Admin manual remove)
    """
    try:
        operation, arguments, identity = extract_appsync_event(event)
        logger.info(f"Waitlist API operation: {operation}")

        # Ensure tenantId is present in arguments or identity for specific operations
        if operation == "getWaitingListByService":
            # For admin, tenantId usually comes from Cognito identity or arguments
            tenant_id = arguments.get("tenantId")
            if not tenant_id and "claims" in identity:
                tenant_id = identity["claims"].get("custom:tenantId")

            if not tenant_id:
                raise ValidationError("tenantId missing")

            service_id = arguments.get("serviceId")
            if not service_id:
                raise ValidationError("serviceId missing")

            entries = waitlist_repo.list_by_service(tenant_id, service_id)
            # Convert to dict for AppSync
            result = [entry.__dict__ for entry in entries]
            return success_response(result)

        elif operation == "addToWaitingList":
            # Can be called by public widget (API key) or Chat Agent
            # arguments should contain input object
            input_data = arguments.get("input", {})
            
            tenant_id = input_data.get("tenantId")
            service_id = input_data.get("serviceId")
            client_id = input_data.get("clientId")
            provider_id = input_data.get("providerId")
            preferred_days = input_data.get("preferredDays")

            if not all([tenant_id, service_id, client_id]):
                raise ValidationError("Missing required fields (tenantId, serviceId, clientId)")

            entry = waitlist_service.add_to_waitlist(
                tenant_id=tenant_id,
                service_id=service_id,
                provider_id=provider_id,
                client_id=client_id,
                preferred_days=preferred_days
            )
            return success_response(entry.__dict__)

        elif operation == "removeWaitingListEntry":
            # Admin feature
            tenant_id = arguments.get("tenantId")
            if not tenant_id and "claims" in identity:
                tenant_id = identity["claims"].get("custom:tenantId")
                
            if not tenant_id:
                raise ValidationError("tenantId missing")
                
            waiting_list_id = arguments.get("waitingListId")
            if not waiting_list_id:
                raise ValidationError("waitingListId missing")

            waitlist_repo.delete(tenant_id, waiting_list_id)
            return success_response(True)

        else:
            logger.error(f"Unknown operation: {operation}")
            return error_response(f"Unknown operation: {operation}", 400)

    except ValidationError as e:
        logger.warning(f"Validation error: {str(e)}")
        return error_response(str(e), 400, "ValidationError")
    except ConflictError as e:
        logger.warning(f"Conflict error: {str(e)}")
        return error_response(str(e), 409, "ConflictError")
    except EntityNotFoundError as e:
        logger.warning(f"Not found: {str(e)}")
        return error_response(str(e), 404, "NotFoundError")
    except (TenantNotActiveError, ServiceNotAvailableError, ProviderNotAvailableError) as e:
        logger.warning(f"Entity not available: {str(e)}")
        return error_response(str(e), 400, "NotAvailableError")
    except Exception as e:
        logger.error(f"Internal server error: {str(e)}", exc_info=True)
        return error_response("Internal server error", 500, "InternalError")
