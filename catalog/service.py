"""
Catalog Service (Application Layer)

Use Cases for managing services and providers catalog
Following Clean Architecture / Hexagonal Architecture
"""

from typing import List, Optional, Dict, Any
from shared.domain.entities import TenantId, Service, Provider, Category, Room
from shared.domain.repositories import IServiceRepository, IProviderRepository, ICategoryRepository, IRoomRepository  # , FileStorageRepository  # Temporarily removed
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
        provider_repository: IProviderRepository,
        category_repository: ICategoryRepository,
        room_repository: IRoomRepository
    ):
        """
        Dependency Injection: depends on abstractions
        """
        self.service_repo = service_repository
        self.provider_repo = provider_repository
        self.category_repo = category_repository
        self.room_repo = room_repository
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

    def list_categories(
        self,
        tenant_id: TenantId,
        active_only: bool = False
    ) -> List[Category]:
        """
        List categories for tenant
        """
        self.logger.info(
            "Listing categories",
            tenant_id=str(tenant_id),
            active_only=active_only
        )
        
        return self.category_repo.list_by_tenant(tenant_id, active_only)

    def list_rooms(self, tenant_id: TenantId) -> List[Room]:
        """List all rooms for tenant"""
        self.logger.info("Listing rooms", tenant_id=str(tenant_id))
        return self.room_repo.list_by_tenant(tenant_id)

    def get_room(self, tenant_id: TenantId, room_id: str) -> Room:
        """Get room by ID"""
        self.logger.info("Getting room", tenant_id=str(tenant_id), room_id=room_id)
        room = self.room_repo.get_by_id(tenant_id, room_id)
        if not room:
            raise EntityNotFoundError("Room", room_id)
        return room


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
        metadata: Optional[Dict[str, Any]] = None,
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
            metadata=metadata or {},
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
        metadata: Optional[Dict[str, Any]] = None,
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
        if metadata is not None:
            provider.metadata = metadata
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


class CategoryManagementService:
    """
    Service for managing categories (admin operations)
    """

    def __init__(self, category_repository: ICategoryRepository):
        self.category_repo = category_repository
        self.logger = Logger()

    def create_category(
        self,
        tenant_id: TenantId,
        category_id: str,
        name: str,
        description: Optional[str] = None,
        is_active: bool = True,
        display_order: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Category:
        """Create new category"""
        self.logger.info(
            "Creating category",
            tenant_id=str(tenant_id),
            name=name
        )

        category = Category(
            category_id=category_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            is_active=is_active,
            display_order=display_order,
            metadata=metadata or {}
        )

        self.category_repo.save(category)

        self.logger.info(
            "Category created",
            tenant_id=str(tenant_id),
            category_id=category_id
        )

        return category

    def update_category(
        self,
        tenant_id: TenantId,
        category_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        display_order: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Category:
        """Update existing category"""
        self.logger.info(
            "Updating category",
            tenant_id=str(tenant_id),
            category_id=category_id
        )

        category = self.category_repo.get_by_id(tenant_id, category_id)
        if not category:
            raise EntityNotFoundError("Category", category_id)

        if name is not None:
            category.name = name
        if description is not None:
            category.description = description
        if is_active is not None:
            category.is_active = is_active
        if display_order is not None:
            category.display_order = display_order
        if metadata is not None:
            category.metadata = metadata

        # Update timestamp
        from datetime import datetime, timezone
        category.updated_at = datetime.now(timezone.utc)

        self.category_repo.save(category)

        self.logger.info(
            "Category updated",
            tenant_id=str(tenant_id),
            category_id=category_id
        )

        return category

    def delete_category(
        self,
        tenant_id: TenantId,
        category_id: str
    ) -> None:
        """Delete category"""
        self.logger.info(
            "Deleting category",
            tenant_id=str(tenant_id),
            category_id=category_id
        )

        category = self.category_repo.get_by_id(tenant_id, category_id)
        if not category:
            raise EntityNotFoundError("Category", category_id)

        self.category_repo.delete(tenant_id, category_id)

        self.logger.info(
            "Category deleted",
            tenant_id=str(tenant_id),
            category_id=category_id
        )


class RoomManagementService:
    """Service for managing rooms."""

    def __init__(self, room_repository: IRoomRepository):
        self.room_repo = room_repository
        self.logger = Logger()

    def create_room(
        self,
        tenant_id: TenantId,
        room_id: str,
        name: str,
        description: Optional[str] = None,
        capacity: Optional[int] = None,
        status: str = "ACTIVE",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Room:
        """Create new room"""
        self.logger.info("Creating room", tenant_id=str(tenant_id), name=name)

        room = Room(
            room_id=room_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            capacity=capacity,
            status=status,
            metadata=metadata or {}
        )
        self.room_repo.save(room)
        return room

    def update_room(
        self,
        tenant_id: TenantId,
        room_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capacity: Optional[int] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Room:
        """Update existing room"""
        self.logger.info("Updating room", tenant_id=str(tenant_id), room_id=room_id)

        room = self.room_repo.get_by_id(tenant_id, room_id)
        if not room:
            raise EntityNotFoundError("Room", room_id)

        if name is not None:
            room.name = name
        if description is not None:
            room.description = description
        if capacity is not None:
            room.capacity = capacity
        if status is not None:
            room.status = status
        if metadata is not None:
            room.metadata = metadata

        from datetime import datetime, timezone
        room.updated_at = datetime.now(timezone.utc)

        self.room_repo.save(room)
        return room

    def delete_room(self, tenant_id: TenantId, room_id: str) -> None:
        """Delete room"""
        self.logger.info("Deleting room", tenant_id=str(tenant_id), room_id=room_id)
        
        # Verify exists
        room = self.room_repo.get_by_id(tenant_id, room_id)
        if not room:
            raise EntityNotFoundError("Room", room_id)

        self.room_repo.delete(tenant_id, room_id)


class AssetService:
    """
    Service for managing assets (files/images)
    """

    def __init__(self, file_storage_repository): 
        self.storage_repo = file_storage_repository
        self.logger = Logger()

    def generate_upload_url(
        self,
        tenant_id: TenantId,
        file_name: str,
        content_type: str
    ) -> str:
        """
        Generate presigned URL for uploading a file
        """
        self.logger.info(
            "Generating upload URL",
            tenant_id=str(tenant_id),
            file_name=file_name
        )

        # Validate content type
        if not content_type.startswith('image/'):
             raise ValidationError("Only image uploads are allowed")

        # Generate unique filename to prevent collisions (or rely on client?)
        # For professional photos, maybe use a prefix?
        # Ideally, we should receive the entity ID (provider_id) to organize folders.
        # For now, just pass the filename (S3 adapter handles raw/ prefix).
        
        url = self.storage_repo.generate_presigned_url(
            file_name=file_name,
            content_type=content_type,
            operation='put_object'
        )

        return url
