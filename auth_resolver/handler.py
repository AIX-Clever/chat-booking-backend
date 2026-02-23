"""
Auth Resolver Lambda Handler (Adapter Layer)

AWS Lambda function that acts as AppSync authorizer
Resolves tenantId from API Key in request headers
"""

import os

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

        # Check IP Whitelist
        allowed_ips = os.environ.get('ALLOWED_IPS')
        if allowed_ips:
            request_context = event.get('requestContext', {})
            source_ip = request_context.get('identity', {}).get('sourceIp')

            if not source_ip:
                # Fallback: check X-Forwarded-For header
                headers = event.get('headers', {})
                source_ip = headers.get('x-forwarded-for') or headers.get('X-Forwarded-For')

            allowed_list = [ip.strip() for ip in allowed_ips.split(',') if ip.strip()]
            logger.info(f"Checking IP {source_ip} against whitelist")

            if source_ip and source_ip not in allowed_list:
                logger.warning(f"IP {source_ip} not in allowed list")
                return unauthorized_response("IP not allowed")

        # Extract origin from headers
        headers = event.get('headers', {})
        origin = headers.get('origin') or headers.get('Origin') or 'unknown'

        # Authenticate using service
        tenant_id = auth_service.authenticate_api_key(api_key, origin)

        # [RATE LIMIT] Check per-API-key rate limit after successful auth
        # Fail-open: if DynamoDB unavailable, traffic is not blocked
        if not _check_rate_limit(api_key):
            logger.warning("Rate limit exceeded", api_key_prefix=api_key[:8])
            return unauthorized_response("Rate limit exceeded. Please try again in 1 minute.")

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


def _check_rate_limit(api_key: str) -> bool:
    """
    Token-bucket rate limiter using DynamoDB atomic counter + TTL.

    DynamoDB item:
      pk:    "rate#<sha256[:16]>"
      sk:    "rate_limit"
      count: N  (atomic ADD, increments per request)
      ttl:   epoch + WINDOW_SECONDS  (DynamoDB TTL auto-deletes the item)

    Returns True if within limit, False if throttled.
    Fails OPEN if DynamoDB is unavailable (avoids blocking legitimate traffic).
    """
    import time
    import hashlib
    import boto3

    table_name = os.environ.get('TENANT_USAGE_TABLE')
    if not table_name:
        return True  # Fail open: rate limiting disabled if table not configured

    max_requests = int(os.environ.get('RATE_LIMIT_MAX', '100'))
    window_seconds = int(os.environ.get('RATE_LIMIT_WINDOW_SECONDS', '60'))

    # Short hash of API key as PK — avoids storing the raw key in DynamoDB
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    pk = f"rate#{key_hash}"
    now = int(time.time())
    expiry = now + window_seconds

    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)

        # Atomically increment. if_not_exists sets TTL only on first write (window start).
        response = table.update_item(
            Key={'pk': pk, 'sk': 'rate_limit'},
            UpdateExpression='ADD #cnt :one SET #ttl = if_not_exists(#ttl, :expiry)',
            ExpressionAttributeNames={'#cnt': 'count', '#ttl': 'ttl'},
            ExpressionAttributeValues={':one': 1, ':expiry': expiry},
            ReturnValues='UPDATED_NEW',
        )

        current_count = int(response['Attributes'].get('count', 1))

        if current_count > max_requests:
            logger.warning("Rate limit exceeded", key_hash=key_hash, count=current_count, max=max_requests)
            return False

        return True

    except Exception as e:
        # Fail open: don't block legitimate traffic if DynamoDB is degraded
        logger.error(f"Rate limit check failed (fail-open): {e}")
        return True


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
