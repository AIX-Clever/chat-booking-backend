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
    Tenant,
    TenantId,
    Service,
    Provider,
    ProviderAvailability,
    Booking,
    Conversation,
    ApiKey,
    TimeSlot,
    Category,
    FAQ,
    Workflow,
    Room,
    RoomAssignment,
    WaitingListEntry,
    ClientInfo,
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

    @abstractmethod
    def decrement_whatsapp_quota(self, tenant_id: TenantId) -> bool:
        """Atomically decrement whatsapp_quota if it's > 0."""
        pass

    @abstractmethod
    def increment_sms_quota(self, tenant_id: TenantId, amount: int) -> bool:
        """Atomically add amount credits to sms_quota."""
        pass

    @abstractmethod
    def decrement_sms_quota(self, tenant_id: TenantId) -> bool:
        """Atomically decrement sms_quota if it's > 0."""
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
    def list_by_tenant(
        self, tenant_id: TenantId, active_only: bool = False
    ) -> List[Category]:
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
        self, tenant_id: TenantId, provider_id: str
    ) -> List[ProviderAvailability]:
        """Get weekly availability for provider"""
        pass

    @abstractmethod
    def save_availability(self, availability: ProviderAvailability) -> None:
        """Persist availability schedule"""
        pass

    @abstractmethod
    def get_provider_exceptions(
        self, tenant_id: TenantId, provider_id: str
    ) -> List[dict]:
        """Get provider exception rules"""
        pass

    @abstractmethod
    def save_provider_exceptions(
        self, tenant_id: TenantId, provider_id: str, exceptions: List[dict]
    ) -> None:
        """Save provider exception rules"""
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
        to_date: datetime,
    ) -> List[Booking]:
        """List bookings for provider in date range"""
        pass

    @abstractmethod
    def list_by_customer_email(
        self, tenant_id: TenantId, customer_email: str
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

    @abstractmethod
    def soft_lock(
        self, tenant_id: TenantId, booking_id: str, ttl_minutes: int = 15
    ) -> None:
        """Mark slot as SOFT_LOCKED for ttl_minutes to reserve it for a waitlist candidate.
        No-op if the booking no longer exists or is already re-taken."""
        pass


class IConversationRepository(ABC):
    """Port for Conversation state operations"""

    @abstractmethod
    def get_by_id(
        self, tenant_id: TenantId, conversation_id: str
    ) -> Optional[Conversation]:
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


class IWorkflowRepository(ABC):
    """Port for Workflow operations"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId, workflow_id: str) -> Optional[Workflow]:
        """Retrieve workflow by ID"""
        pass

    @abstractmethod
    def list_by_tenant(self, tenant_id: TenantId) -> List[Workflow]:
        """List all workflows for tenant"""
        pass

    @abstractmethod
    def save(self, workflow: Workflow) -> None:
        """Persist workflow"""
        pass


class IRoomRepository(ABC):
    """Port for Room operations"""

    @abstractmethod
    def get_by_id(self, tenant_id: TenantId, room_id: str) -> Optional[Room]:
        """Retrieve room by ID"""
        pass

    @abstractmethod
    def list_by_tenant(self, tenant_id: TenantId) -> List[Room]:
        """List all rooms for tenant"""
        pass

    @abstractmethod
    def save(self, room: Room) -> None:
        """Persist room"""
        pass

    @abstractmethod
    def delete(self, tenant_id: TenantId, room_id: str) -> None:
        pass


class IRoomAssignmentRepository(ABC):
    """Port for RoomAssignment operations"""

    @abstractmethod
    def get(self, tenant_id: TenantId, room_id: str, provider_id: str) -> Optional[RoomAssignment]:
        pass

    @abstractmethod
    def list_by_room(self, tenant_id: TenantId, room_id: str) -> List[RoomAssignment]:
        pass

    @abstractmethod
    def list_by_provider(self, tenant_id: TenantId, provider_id: str) -> List[RoomAssignment]:
        pass

    @abstractmethod
    def save(self, assignment: RoomAssignment) -> None:
        pass

    @abstractmethod
    def delete(self, tenant_id: TenantId, room_id: str, provider_id: str) -> None:
        pass


class FileStorageRepository(ABC):
    """Port for file storage operations"""

    @abstractmethod
    def generate_presigned_url(
        self,
        file_name: str,
        content_type: str,
        operation: str = "put_object",
        expiration: int = 3600,
    ) -> str:
        """Generate a presigned URL for file operations"""
        pass


class IProviderIntegrationRepository(ABC):
    """Port for Provider Integration operations (e.g. Google Calendar)"""

    @abstractmethod
    def save_google_creds(
        self, tenant_id: TenantId, provider_id: str, credentials: dict
    ) -> None:
        """Save Google Calendar credentials"""
        pass

    @abstractmethod
    def get_google_creds(self, tenant_id: TenantId, provider_id: str) -> Optional[dict]:
        """Get Google Calendar credentials"""
        pass

    @abstractmethod
    def delete_google_creds(self, tenant_id: TenantId, provider_id: str) -> None:
        """Delete Google Calendar credentials"""
        pass


class IWaitingListRepository(ABC):
    """Port for Waiting List operations"""

    @abstractmethod
    def save(self, entry: WaitingListEntry) -> None:
        """Persist a waiting list entry"""
        pass

    @abstractmethod
    def get_by_id(
        self, tenant_id: TenantId, waiting_list_id: str
    ) -> Optional[WaitingListEntry]:
        """Retrieve a waiting list entry by ID"""
        pass

    @abstractmethod
    def list_by_service(
        self,
        tenant_id: TenantId,
        service_id: str,
        statuses: Optional[List[str]] = None,
    ) -> List[WaitingListEntry]:
        """List entries for a service ordered by createdAt ASC.
        statuses=None returns all; defaults to [PENDING] when not provided."""
        pass

    @abstractmethod
    def find_pending_by_client(
        self, tenant_id: TenantId, service_id: str, client_id: str
    ) -> Optional[WaitingListEntry]:
        """Check if client already has a pending entry for a service"""
        pass

    @abstractmethod
    def update_status(
        self, tenant_id: TenantId, waiting_list_id: str, status: str
    ) -> None:
        """Update entry contact status"""
        pass

    @abstractmethod
    def delete(self, tenant_id: TenantId, waiting_list_id: str) -> None:
        """Remove entry from waiting list"""
        pass


class IClientRepository(ABC):
    """Port for Client lookup (read-only projection for booking creation)"""

    @abstractmethod
    def find_by_phone(
        self, tenant_id: TenantId, phone: str
    ) -> Optional[ClientInfo]:
        """Find a client by phone number using phone-index GSI."""
        pass

    @abstractmethod
    def find_by_email(
        self, tenant_id: TenantId, email: str
    ) -> Optional[ClientInfo]:
        """Find a client by email using email-index GSI."""
        pass
