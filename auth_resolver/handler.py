"""
Auth Resolver Lambda Handler (Adapter Layer)

AWS Lambda function that acts as AppSync authorizer
Resolves tenantId from API Key in request headers
"""

import json
import sys
import os

# Add parent directory to path for shared imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from shared.infrastructure.dynamodb_repositories import (
    DynamoDBApiKeyRepository,
    DynamoDBTenantRepository
)
from shared.domain.exceptions import (
    InvalidApiKeyError,
    OriginNotAllowedError,
    TenantNotActiveError,
    EntityNotFoundError
)
from shared.utils import Logger

from service import AuthenticationService


# Initialize dependencies (singleton pattern)
api_key_repo = DynamoDBApiKeyRepository()
tenant_repo = DynamoDBTenantRepository()
auth_service = AuthenticationService(api_key_repo, tenant_repo)
logger = Logger()


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for AppSync custom authorizer
    
    Input event format:
    {
        "authorizationToken": "sk_...",
        "requestContext": {
            "apiId": "xxx",
            "requestId": "xxx"
        },
        "headers": {
            "origin": "https://example.com"
        }
    }
    
    Output format:
    {
        "isAuthorized": true,
        "resolverContext": {
            "tenantId": "tenant_123"
        },
        "deniedFields": [],
        "ttlOverride": 300
    }
    """
    try:
        logger.info("Auth resolver invoked", request_id=event.get('requestContext', {}).get('requestId'))

        # Extract API key from authorization token
        api_key = event.get('authorizationToken', '')
        
        if not api_key:
            logger.warning("Missing authorization token")
            return unauthorized_response()

        # Extract origin from headers
        headers = event.get('headers', {})
        origin = headers.get('origin') or headers.get('Origin') or 'unknown'

        # Authenticate using service
        tenant_id = auth_service.authenticate_api_key(api_key, origin)

        # Return authorized response
        return authorized_response(str(tenant_id))

    except (InvalidApiKeyError, OriginNotAllowedError, TenantNotActiveError) as e:
        logger.warning("Authentication failed", error=str(e))
        return unauthorized_response(str(e))

    except EntityNotFoundError as e:
        logger.error("Entity not found during authentication", error=str(e))
        return unauthorized_response("Authentication failed")

    except Exception as e:
        logger.error("Unexpected error in auth resolver", error=e)
        return unauthorized_response("Internal error")


def authorized_response(tenant_id: str) -> dict:
    """Build authorized response for AppSync"""
    return {
        "isAuthorized": True,
        "resolverContext": {
            "tenantId": tenant_id
        },
        "deniedFields": [],
        "ttlOverride": 300  # Cache authorization for 5 minutes
    }


def unauthorized_response(reason: str = "Unauthorized") -> dict:
    """Build unauthorized response for AppSync"""
    return {
        "isAuthorized": False,
        "resolverContext": {
            "reason": reason
        }
    }
