"""
Custom Exceptions

Domain-specific exceptions that represent business rule violations
"""


class DomainException(Exception):
    """Base exception for domain errors"""

    pass


class EntityNotFoundError(DomainException):
    """Entity doesn't exist"""

    def __init__(self, entity_type: str, entity_id: str):
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} not found: {entity_id}")


class ConflictError(DomainException):
    """Resource conflict (e.g., overbooking)"""

    pass


class ValidationError(DomainException):
    """Invalid input data"""

    pass


class UnauthorizedError(DomainException):
    """Authentication/Authorization failed"""

    pass


class TenantNotActiveError(DomainException):
    """Tenant account is not active"""

    def __init__(self, code: str = "TENANT_NOT_ACTIVE"):
        super().__init__(code)


class ServiceNotAvailableError(DomainException):
    """Service cannot be booked"""

    def __init__(self, code: str = "SERVICE_NOT_AVAILABLE"):
        super().__init__(code)


class ProviderNotAvailableError(DomainException):
    """Provider cannot provide service"""

    def __init__(self, code: str = "PROVIDER_NOT_AVAILABLE"):
        super().__init__(code)


class SlotNotAvailableError(DomainException):
    """Time slot is already taken"""

    def __init__(self, code: str = "SLOT_NOT_AVAILABLE"):
        super().__init__(code)


class InvalidApiKeyError(UnauthorizedError):
    """API Key is invalid or revoked"""

    def __init__(self):
        super().__init__("Invalid or revoked API key")


class OriginNotAllowedError(UnauthorizedError):
    """Request origin is not in allowed list"""

    def __init__(self, origin: str):
        super().__init__(f"Origin not allowed: {origin}")


class RateLimitExceededError(DomainException):
    """Too many requests"""

    def __init__(self):
        super().__init__("Rate limit exceeded")


class PlanLimitExceeded(DomainException):
    """Plan limit exceeded (e.g. max users)"""

    pass
