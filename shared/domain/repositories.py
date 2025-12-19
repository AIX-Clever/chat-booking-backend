"""
Repository Interfaces (Ports)

Following Hexagonal Architecture:
- Define contracts in domain layer
- Infrastructure implements these interfaces
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from .entities import (
    Tenant, TenantId, Service, Provider, ProviderAvailability,
    Booking, Conversation, ApiKey, TimeSlot, Category, FAQ
)


class ITenantRepository(ABC):
    """Port for Tenant persistence"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId) -> Optional[Tenant]:
        """Retrieve tenant by ID"""
        pass

    @abstractmethod
    def save(self, tenant: Tenant) -> None:
        """Persist tenant"""
        pass


class IApiKeyRepository(ABC):
    """Port for API Key operations"""

    @abstractmethod
    def find_by_hash(self, api_key_hash: str) -> Optional[ApiKey]:
        """Find API key by hash"""
        pass

    @abstractmethod
    def save(self, api_key: ApiKey) -> None:
        """Persist API key"""
        pass

    @abstractmethod
    def list_by_tenant(self, tenant_id: TenantId) -> List[ApiKey]:
        """List all API keys for tenant"""
        pass


class IServiceRepository(ABC):
    """Port for Service operations"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId, service_id: str) -> Optional[Service]:
        """Retrieve service by ID"""
        pass

    @abstractmethod
    def list_by_tenant(self, tenant_id: TenantId) -> List[Service]:
        """List all services for tenant"""
        pass

    @abstractmethod
    def search(self, tenant_id: TenantId, query: Optional[str] = None) -> List[Service]:
        """Search services"""
        pass

    @abstractmethod
    def save(self, service: Service) -> None:
        """Persist service"""
        pass

    @abstractmethod
    def delete(self, tenant_id: TenantId, service_id: str) -> None:
        """Delete service"""
        pass


class ICategoryRepository(ABC):
    """Port for Category operations"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId, category_id: str) -> Optional[Category]:
        """Retrieve category by ID"""
        pass

    @abstractmethod
    def list_by_tenant(self, tenant_id: TenantId, active_only: bool = False) -> List[Category]:
        """List all categories for tenant"""
        pass

    @abstractmethod
    def save(self, category: Category) -> None:
        """Persist category"""
        pass

    @abstractmethod
    def delete(self, tenant_id: TenantId, category_id: str) -> None:
        """Delete category"""
        pass

class IProviderRepository(ABC):
    """Port for Provider operations"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId, provider_id: str) -> Optional[Provider]:
        """Retrieve provider by ID"""
        pass

    @abstractmethod
    def list_by_tenant(self, tenant_id: TenantId) -> List[Provider]:
        """List all providers for tenant"""
        pass

    @abstractmethod
    def list_by_service(self, tenant_id: TenantId, service_id: str) -> List[Provider]:
        """List providers that offer specific service"""
        pass

    @abstractmethod
    def save(self, provider: Provider) -> None:
        """Persist provider"""
        pass

    @abstractmethod
    def delete(self, tenant_id: TenantId, provider_id: str) -> None:
        """Delete provider"""
        pass


class IAvailabilityRepository(ABC):
    """Port for Provider Availability operations"""

    @abstractmethod
    def get_provider_availability(
        self,
        tenant_id: TenantId,
        provider_id: str
    ) -> List[ProviderAvailability]:
        """Get weekly availability for provider"""
        pass

    @abstractmethod
    def save_availability(self, availability: ProviderAvailability) -> None:
        """Persist availability schedule"""
        pass

    @abstractmethod
    def get_provider_exceptions(self, tenant_id: TenantId, provider_id: str) -> List[str]:
        """Get provider exception dates"""
        pass

    @abstractmethod
    def save_provider_exceptions(self, tenant_id: TenantId, provider_id: str, exceptions: List[str]) -> None:
        """Save provider exception dates"""
        pass


class IBookingRepository(ABC):
    """Port for Booking operations"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId, booking_id: str) -> Optional[Booking]:
        """Retrieve booking by ID"""
        pass

    @abstractmethod
    def list_by_provider(
        self,
        tenant_id: TenantId,
        provider_id: str,
        from_date: datetime,
        to_date: datetime
    ) -> List[Booking]:
        """List bookings for provider in date range"""
        pass

    @abstractmethod
    def list_by_customer_email(
        self,
        tenant_id: TenantId,
        customer_email: str
    ) -> List[Booking]:
        """List bookings for customer by email"""
        pass

    @abstractmethod
    def save(self, booking: Booking) -> None:
        """
        Persist booking with overbooking prevention
        Raises: ConflictError if slot already taken
        """
        pass

    @abstractmethod
    def update(self, booking: Booking) -> None:
        """Update existing booking"""
        pass


class IConversationRepository(ABC):
    """Port for Conversation state operations"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId, conversation_id: str) -> Optional[Conversation]:
        """Retrieve conversation state"""
        pass

    @abstractmethod
    def save(self, conversation: Conversation) -> None:
        """Persist conversation state"""
        pass

    @abstractmethod
    def update(self, conversation: Conversation) -> None:
        """Update conversation state"""
        pass


class IFAQRepository(ABC):
    """Port for FAQ operations"""

    @abstractmethod
    def list_by_tenant(self, tenant_id: TenantId) -> List[FAQ]:
        """List all FAQs for tenant"""
        pass

    @abstractmethod
    def save(self, faq: FAQ) -> None:
        """Persist FAQ"""
        pass

    @abstractmethod
    def delete(self, tenant_id: TenantId, faq_id: str) -> None:
        """Delete FAQ"""
        pass
