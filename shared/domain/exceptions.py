"""
Domain Exceptions
"""

class DomainError(Exception):
    """Base domain exception"""
    pass


class EntityNotFoundError(DomainError):
    """Raised when an entity is not found"""
    def __init__(self, entity_name: str, entity_id: str):
        self.entity_name = entity_name
        self.entity_id = entity_id
        super().__init__(f"{entity_name} with ID {entity_id} not found")


class ValidationError(DomainError):
    """Raised when validation fails"""
    pass


class TenantNotActiveError(DomainError):
    """Raised when tenant is not active"""
    pass


class ServiceNotAvailableError(DomainError):
    """Raised when service is not available"""
    pass


class ProviderNotAvailableError(DomainError):
    """Raised when provider cannot provide service"""
    def __init__(self, provider_id: str, service_id: str):
        self.provider_id = provider_id
        self.service_id = service_id
        super().__init__(f"Provider {provider_id} cannot provide service {service_id}")


class SlotNotAvailableError(DomainError):
    """Raised when time slot is not available"""
    pass


class ConflictError(DomainError):
    """Raised when optimistic locking fails"""
    pass
