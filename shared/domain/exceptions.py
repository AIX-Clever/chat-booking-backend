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

    def __init__(self, tenant_id: str):
        super().__init__(f"Tenant {tenant_id} is not active")


class ServiceNotAvailableError(DomainException):
    """Service cannot be booked"""

    def __init__(self, service_id: str):
        super().__init__(f"Service {service_id} is not available")


class ProviderNotAvailableError(DomainException):
    """Provider cannot provide service"""

    def __init__(self, provider_id: str, service_id: str):
        super().__init__(f"Provider {provider_id} cannot provide service {service_id}")


class SlotNotAvailableError(DomainException):
    """Time slot is already taken"""

    def __init__(self, start_time: str):
        super().__init__(f"Time slot starting at {start_time} is not available")


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
