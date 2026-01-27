"""
Shared utilities

Common helper functions used across all lambdas
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


def generate_id(prefix: str) -> str:
    """Generate unique ID with prefix"""
    unique_id = str(uuid.uuid4())[:8]
    return f"{prefix}_{unique_id}"


def hash_api_key(api_key: str) -> str:
    """Hash API key using SHA256"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """
    Generate new API key
    Returns: (public_key, hashed_key)
    """
    public_key = f"sk_{secrets.token_urlsafe(32)}"
    hashed_key = hash_api_key(public_key)
    return public_key, hashed_key


def parse_iso_datetime(iso_string: str) -> datetime:
    """Parse ISO format datetime string"""
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))


def to_iso_string(dt: datetime) -> str:
    """Convert datetime to ISO string"""
    return dt.isoformat() + "Z" if dt.tzinfo is None else dt.isoformat()


def add_minutes(dt: datetime, minutes: int) -> datetime:
    """Add minutes to datetime"""
    return dt + timedelta(minutes=minutes)


def lambda_response(
    status_code: int, body: Any, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Standard Lambda response format
    """
    import json

    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,X-Api-Key",
        "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
    }

    if headers:
        default_headers.update(headers)

    return {
        "statusCode": status_code,
        "headers": default_headers,
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def success_response(data: Any) -> Dict[str, Any]:
    """Success response (200) - Adapted for AppSync Direct Resolver"""
    return data


def error_response(message: str, status_code: int = 400) -> Dict[str, Any]:
    """Error response - Adapted for AppSync Direct Resolver"""
    # Raising exception for AppSync to capture
    raise Exception(message)


def extract_tenant_id(event: Dict[str, Any]) -> Optional[str]:
    """Extract tenantId from Lambda event (AppSync context)"""
    # 1. From args (if passed explicitly and not null)
    if event.get("arguments") and event["arguments"].get("tenantId"):
        return event["arguments"]["tenantId"]

    # 2. From identity (User Pools)
    if event.get("identity") and event["identity"].get("claims"):
        claims = event["identity"]["claims"]
        if "custom:tenantId" in claims:
            return claims["custom:tenantId"]
        if "tenantId" in claims:
            return claims["tenantId"]
        if "website" in claims:
            return claims["website"]

    # 3. From stash (Lambda Auth / Pipeline)
    if event.get("stash") and "tenantId" in event["stash"]:
        return event["stash"]["tenantId"]

    # 4. Direct property (Direct invocation / Test)
    if "tenantId" in event:
        return event["tenantId"]

    # 5. From headers (API Key / Custom Auth)
    if event.get("request") and event["request"].get("headers"):
        headers = event["request"]["headers"]
        # Check standard custom header
        if "x-tenant-id" in headers:
            return headers["x-tenant-id"]
        if "X-Tenant-Id" in headers:
            return headers["X-Tenant-Id"]

    # 5. Fallback: Fetch from Cognito using Access Token from headers
    # (Required when Access Token is used but attribute is not in claims, e.g. standard attrs like website)
    if event.get("request") and event["request"].get("headers"):
        headers = event["request"]["headers"]
        auth_header = headers.get("authorization")
        if auth_header:
            # Handle "Bearer <token>" or just "<token>"
            token = (
                auth_header.replace("Bearer ", "")
                if auth_header.startswith("Bearer ")
                else auth_header
            )
            try:
                import boto3

                client = boto3.client("cognito-idp")
                user = client.get_user(AccessToken=token)
                # Convert list of dicts to dict
                attributes = {
                    attr["Name"]: attr["Value"] for attr in user["UserAttributes"]
                }

                # Check for tenantId in fetched attributes
                if "custom:tenantId" in attributes:
                    return attributes["custom:tenantId"]
                if "tenantId" in attributes:
                    return attributes["tenantId"]
                if "website" in attributes:
                    return attributes["website"]

            except Exception as e:
                # Log error but don't crash - allow returning None to fail functionally later
                print(f"Error fetching user attributes from Cognito: {str(e)}")

    return None


def extract_appsync_event(event: Dict[str, Any]) -> tuple[str, str, Dict[str, Any]]:
    """
    Extract field, tenant_id, and input from AppSync event

    Returns:
        (field, tenant_id, input_data)

    Raises:
        ValueError: If required data is missing
    """
    # Extract field name
    field = None
    if "info" in event and "fieldName" in event["info"]:
        field = event["info"]["fieldName"]
    elif "field" in event:
        field = event["field"]

    if not field:
        raise ValueError("Could not determine operation field name")

    # Extract tenant_id
    tenant_id = extract_tenant_id(event)
    if not tenant_id:
        raise ValueError("Missing tenantId in request context")

    # Extract input arguments
    input_data = {}
    if "arguments" in event:
        args = event["arguments"]
        # If 'input' wrapper is used (common pattern)
        if "input" in args:
            input_data = args["input"]
        else:
            input_data = args
    elif "input" in event:
        input_data = event["input"]

    return field, tenant_id, input_data


class Logger:
    """Simple structured logger"""

    @staticmethod
    def info(message: str, **kwargs):
        import json

        log_data = {"level": "INFO", "message": message, **kwargs}
        print(json.dumps(log_data))

    @staticmethod
    def error(message: str, error: Exception = None, **kwargs):
        import json

        log_data = {
            "level": "ERROR",
            "message": message,
            "error": str(error) if error else None,
            **kwargs,
        }
        print(json.dumps(log_data))

    @staticmethod
    def warning(message: str, **kwargs):
        import json

        log_data = {"level": "WARNING", "message": message, **kwargs}
        print(json.dumps(log_data))


def check_plan_limit(plan: str, metric: str, current_usage: int) -> None:
    """
    Check if a usage metric exceeds the limits for a given plan.

    Args:
        plan: The plan name (e.g. 'LITE', 'PRO', 'ENTERPRISE')
        metric: The metric to check (e.g. 'max_users')
        current_usage: The current usage count

    Raises:
        PlanLimitExceeded: If limit is exceeded
    """
    # Define Limits (Mock/Simple version)
    # in real app this might come from config or DB
    LIMITS = {
        "LITE": {"max_users": 1},
        "PRO": {"max_users": 5},
        "ENTERPRISE": {"max_users": 9999},
    }

    plan_limits = LIMITS.get(plan, {})
    limit = plan_limits.get(metric)

    if limit is not None and current_usage >= limit:
        from shared.domain.exceptions import PlanLimitExceeded

        raise PlanLimitExceeded(
            f"Plan {plan} limit exceeded for {metric}. Limit: {limit}, Current: {current_usage}"
        )
