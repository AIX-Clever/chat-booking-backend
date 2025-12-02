"""
Catalog Service (Application Layer)

Use Cases for managing services and providers catalog
Following Clean Architecture / Hexagonal Architecture
"""

import sys
import os

# Add parent directory to path for shared imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from typing import List, Optional
from shared.domain.entities import TenantId, Service, Provider
from shared.domain.repositories import IServiceRepository, IProviderRepository
from shared.domain.exceptions import EntityNotFoundError, ValidationError
from shared.utils import Logger


class CatalogService:
    """
    Application service for catalog operations
    Follows Single Responsibility Principle: only handles catalog queries
    """

    def __init__(
        self,
        service_repository: IServiceRepository,
        provider_repository: IProviderRepository
    ):
        """
        Dependency Injection: depends on abstractions
        """
        self.service_repo = service_repository
        self.provider_repo = provider_repository
        self.logger = Logger()

    def search_services(
        self,
        tenant_id: TenantId,
        query: Optional[str] = None
    ) -> List[Service]:
        """
        Search services for a tenant
        
        Args:
            tenant_id: Tenant identifier
            query: Optional search text (searches name, description, category)
            
        Returns:
            List of active services matching criteria
        """
        self.logger.info(
            "Searching services",
            tenant_id=str(tenant_id),
            query=query
        )

        services = self.service_repo.search(tenant_id, query)

        self.logger.info(
            "Services found",
            tenant_id=str(tenant_id),
            count=len(services)
        )

        return services

    def get_service(
        self,
        tenant_id: TenantId,
        service_id: str
    ) -> Service:
        """
        Get specific service by ID
        
        Args:
            tenant_id: Tenant identifier
            service_id: Service identifier
            
        Returns:
            Service entity
            
        Raises:
            EntityNotFoundError: Service doesn't exist
        """
        self.logger.info(
            "Getting service",
            tenant_id=str(tenant_id),
            service_id=service_id
        )

        service = self.service_repo.get_by_id(tenant_id, service_id)

        if not service:
            raise EntityNotFoundError("Service", service_id)

        return service

    def list_all_services(self, tenant_id: TenantId) -> List[Service]:
        """
        List all services for tenant (including inactive)
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of all services
        """
        self.logger.info("Listing all services", tenant_id=str(tenant_id))

        services = self.service_repo.list_by_tenant(tenant_id)

        return services

    def list_providers_by_service(
        self,
        tenant_id: TenantId,
        service_id: str
    ) -> List[Provider]:
        """
        List providers that offer specific service
        
        Args:
            tenant_id: Tenant identifier
            service_id: Service identifier
            
        Returns:
            List of active providers offering the service
            
        Raises:
            EntityNotFoundError: Service doesn't exist
        """
        self.logger.info(
            "Listing providers for service",
            tenant_id=str(tenant_id),
            service_id=service_id
        )

        # Verify service exists
        service = self.get_service(tenant_id, service_id)

        # Get providers
        providers = self.provider_repo.list_by_service(tenant_id, service_id)

        self.logger.info(
            "Providers found",
            tenant_id=str(tenant_id),
            service_id=service_id,
            count=len(providers)
        )

        return providers

    def get_provider(
        self,
        tenant_id: TenantId,
        provider_id: str
    ) -> Provider:
        """
        Get specific provider by ID
        
        Args:
            tenant_id: Tenant identifier
            provider_id: Provider identifier
            
        Returns:
            Provider entity
            
        Raises:
            EntityNotFoundError: Provider doesn't exist
        """
        self.logger.info(
            "Getting provider",
            tenant_id=str(tenant_id),
            provider_id=provider_id
        )

        provider = self.provider_repo.get_by_id(tenant_id, provider_id)

        if not provider:
            raise EntityNotFoundError("Provider", provider_id)

        return provider

    def list_all_providers(self, tenant_id: TenantId) -> List[Provider]:
        """
        List all providers for tenant (including inactive)
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            List of all providers
        """
        self.logger.info("Listing all providers", tenant_id=str(tenant_id))

        providers = self.provider_repo.list_by_tenant(tenant_id)

        return providers


class ServiceManagementService:
    """
    Service for managing services (admin operations)
    Open/Closed Principle: separated from read-only catalog service
    """

    def __init__(self, service_repository: IServiceRepository):
        self.service_repo = service_repository
        self.logger = Logger()

    def create_service(
        self,
        tenant_id: TenantId,
        service_id: str,
        name: str,
        description: Optional[str],
        category: str,
        duration_minutes: int,
        price: Optional[float],
        active: bool = True
    ) -> Service:
        """
        Create new service
        
        Validates business rules before creating
        """
        self.logger.info(
            "Creating service",
            tenant_id=str(tenant_id),
            name=name
        )

        # Validate
        if duration_minutes <= 0:
            raise ValidationError("Duration must be positive")

        if price is not None and price < 0:
            raise ValidationError("Price cannot be negative")

        # Create entity
        service = Service(
            service_id=service_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            category=category,
            duration_minutes=duration_minutes,
            price=price,
            active=active
        )

        # Persist
        self.service_repo.save(service)

        self.logger.info(
            "Service created",
            tenant_id=str(tenant_id),
            service_id=service_id
        )

        return service

    def update_service(
        self,
        tenant_id: TenantId,
        service_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        price: Optional[float] = None,
        active: Optional[bool] = None
    ) -> Service:
        """
        Update existing service
        """
        self.logger.info(
            "Updating service",
            tenant_id=str(tenant_id),
            service_id=service_id
        )

        # Get existing
        service = self.service_repo.get_by_id(tenant_id, service_id)
        if not service:
            raise EntityNotFoundError("Service", service_id)

        # Update fields
        if name is not None:
            service.name = name
        if description is not None:
            service.description = description
        if category is not None:
            service.category = category
        if duration_minutes is not None:
            if duration_minutes <= 0:
                raise ValidationError("Duration must be positive")
            service.duration_minutes = duration_minutes
        if price is not None:
            if price < 0:
                raise ValidationError("Price cannot be negative")
            service.price = price
        if active is not None:
            service.active = active

        # Persist
        self.service_repo.save(service)

        self.logger.info(
            "Service updated",
            tenant_id=str(tenant_id),
            service_id=service_id
        )

        return service

    def delete_service(
        self,
        tenant_id: TenantId,
        service_id: str
    ) -> None:
        """
        Delete service
        """
        self.logger.info(
            "Deleting service",
            tenant_id=str(tenant_id),
            service_id=service_id
        )

        # Verify exists
        service = self.service_repo.get_by_id(tenant_id, service_id)
        if not service:
            raise EntityNotFoundError("Service", service_id)

        # Delete
        self.service_repo.delete(tenant_id, service_id)

        self.logger.info(
            "Service deleted",
            tenant_id=str(tenant_id),
            service_id=service_id
        )


class ProviderManagementService:
    """
    Service for managing providers (admin operations)
    """

    def __init__(self, provider_repository: IProviderRepository):
        self.provider_repo = provider_repository
        self.logger = Logger()

    def create_provider(
        self,
        tenant_id: TenantId,
        provider_id: str,
        name: str,
        bio: Optional[str],
        service_ids: List[str],
        timezone: str,
        active: bool = True
    ) -> Provider:
        """
        Create new provider
        """
        self.logger.info(
            "Creating provider",
            tenant_id=str(tenant_id),
            name=name
        )

        # Validate
        if not service_ids:
            raise ValidationError("Provider must offer at least one service")

        # Create entity
        provider = Provider(
            provider_id=provider_id,
            tenant_id=tenant_id,
            name=name,
            bio=bio,
            service_ids=service_ids,
            timezone=timezone,
            active=active
        )

        # Persist
        self.provider_repo.save(provider)

        self.logger.info(
            "Provider created",
            tenant_id=str(tenant_id),
            provider_id=provider_id
        )

        return provider

    def update_provider(
        self,
        tenant_id: TenantId,
        provider_id: str,
        name: Optional[str] = None,
        bio: Optional[str] = None,
        service_ids: Optional[List[str]] = None,
        timezone: Optional[str] = None,
        active: Optional[bool] = None
    ) -> Provider:
        """
        Update existing provider
        """
        self.logger.info(
            "Updating provider",
            tenant_id=str(tenant_id),
            provider_id=provider_id
        )

        # Get existing
        provider = self.provider_repo.get_by_id(tenant_id, provider_id)
        if not provider:
            raise EntityNotFoundError("Provider", provider_id)

        # Update fields
        if name is not None:
            provider.name = name
        if bio is not None:
            provider.bio = bio
        if service_ids is not None:
            if not service_ids:
                raise ValidationError("Provider must offer at least one service")
            provider.service_ids = service_ids
        if timezone is not None:
            provider.timezone = timezone
        if active is not None:
            provider.active = active

        # Persist
        self.provider_repo.save(provider)

        self.logger.info(
            "Provider updated",
            tenant_id=str(tenant_id),
            provider_id=provider_id
        )

        return provider

    def delete_provider(
        self,
        tenant_id: TenantId,
        provider_id: str
    ) -> None:
        """
        Delete provider
        """
        self.logger.info(
            "Deleting provider",
            tenant_id=str(tenant_id),
            provider_id=provider_id
        )

        # Verify exists
        provider = self.provider_repo.get_by_id(tenant_id, provider_id)
        if not provider:
            raise EntityNotFoundError("Provider", provider_id)

        # Delete
        self.provider_repo.delete(tenant_id, provider_id)

        self.logger.info(
            "Provider deleted",
            tenant_id=str(tenant_id),
            provider_id=provider_id
        )
