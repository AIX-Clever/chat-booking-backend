from functools import wraps
from shared.utils import extract_tenant_id, error_response


def require_tenant_context(func):
    """
    Decorator to ensure tenantId is present in the request context.
    Injects 'tenant_id' into the event dictionary.
    """

    @wraps(func)
    def wrapper(event, context):
        tenant_id = extract_tenant_id(event)
        if not tenant_id:
            return error_response("Missing tenant context", 401)

        # Inject into event for handler convenience
        if isinstance(event, dict):
            event["tenant_id"] = tenant_id

        return func(event, context)

    return wrapper
