"""
Catalog Lambda Handler (Adapter Layer)

AWS Lambda function for catalog queries (services and providers)
Handles both public widget queries and admin panel operations
"""

import json

from shared.infrastructure.dynamodb_repositories import (
    DynamoDBServiceRepository,
    DynamoDBProviderRepository,
    DynamoDBRoomRepository
)
from shared.infrastructure.category_repository import DynamoDBCategoryRepository
from shared.infrastructure.s3_storage_adapter import S3FileStorageRepository
from shared.domain.entities import TenantId
from shared.domain.exceptions import EntityNotFoundError, ValidationError
from shared.utils import Logger, success_response, error_response, generate_id, extract_appsync_event
import os
import boto3

from service import (
    CatalogService,
    ServiceManagementService,
    ProviderManagementService,
    CategoryManagementService,
    RoomManagementService,
    AssetService
)


# Initialize dependencies (singleton pattern)
service_repo = DynamoDBServiceRepository()
provider_repo = DynamoDBProviderRepository()
category_repo = DynamoDBCategoryRepository()
room_repo = DynamoDBRoomRepository()

# Initialize asset service for S3 uploads
try:
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    env = os.environ.get('ENV', 'dev')
    bucket_name = f"chat-booking-assets-{env}-{account_id}"
    s3_repo = S3FileStorageRepository(bucket_name=bucket_name)
    asset_service = AssetService(s3_repo)
except Exception as e:
    logger.error("Failed to initialize AssetService", error=str(e))
    asset_service = None

catalog_service = CatalogService(service_repo, provider_repo, category_repo, room_repo)
service_mgmt_service = ServiceManagementService(service_repo)
provider_mgmt_service = ProviderManagementService(provider_repo)
category_mgmt_service = CategoryManagementService(category_repo)
room_mgmt_service = RoomManagementService(room_repo)

logger = Logger()





def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for catalog operations
    
    Supports multiple operations via 'field' parameter:
    - searchServices
    - getService
    - listServices
    - listProvidersByService
    - getProvider
    - listProviders
    - createService (admin)
    - updateService (admin)
    - deleteService (admin)
    - createProvider (admin)
    - updateProvider (admin)
    - deleteProvider (admin)
    - generatePresignedUrl (assets)
    """
    try:
        field, tenant_id_str, input_data = extract_appsync_event(event)

        tenant_id = TenantId(tenant_id_str)

        logger.info(
            "Catalog operation",
            field=field,
            tenant_id=tenant_id_str
        )

        # Route to appropriate handler
        if field == 'searchServices':
            return handle_search_services(tenant_id, input_data)
        
        elif field == 'getService':
            return handle_get_service(tenant_id, input_data)
        
        elif field == 'listServices':
            return handle_list_services(tenant_id)
        
        elif field == 'listProvidersByService':
            return handle_list_providers_by_service(tenant_id, input_data)
        
        elif field == 'getProvider':
            return handle_get_provider(tenant_id, input_data)
        
        elif field == 'listProviders':
            return handle_list_providers(tenant_id)

        elif field == 'listCategories':
            return handle_list_categories(tenant_id, input_data)
        
        elif field == 'createCategory':
            return handle_create_category(tenant_id, input_data)
        
        elif field == 'updateCategory':
            return handle_update_category(tenant_id, input_data)
        
        elif field == 'deleteCategory':
            return handle_delete_category(tenant_id, input_data)
        
        # Admin operations
        elif field == 'createService':
            return handle_create_service(tenant_id, input_data)
        
        elif field == 'updateService':
            return handle_update_service(tenant_id, input_data)
        
        elif field == 'deleteService':
            return handle_delete_service(tenant_id, input_data)
        
        elif field == 'createProvider':
            return handle_create_provider(tenant_id, input_data)
        
        elif field == 'updateProvider':
            return handle_update_provider(tenant_id, input_data)
        
        elif field == 'deleteProvider':
            return handle_delete_provider(tenant_id, input_data)

        elif field == 'listRooms':
            return handle_list_rooms(tenant_id)

        elif field == 'getRoom':
            return handle_get_room(tenant_id, input_data)

        elif field == 'createRoom':
            return handle_create_room(tenant_id, input_data)

        elif field == 'updateRoom':
            return handle_update_room(tenant_id, input_data)

        elif field == 'deleteRoom':
            return handle_delete_room(tenant_id, input_data)
            
        elif field == 'generatePresignedUrl':
             return handle_generate_presigned_url(tenant_id, input_data)
        
        else:
            # For unknown operations, raise exception directly or return error dict?
            # Since we want AppSync to see error, raise it.
            raise ValueError(f"Unknown operation: {field}")

    except EntityNotFoundError as e:
        logger.warning("Entity not found", error=str(e))
        return error_response(str(e), 404)

    except ValidationError as e:
        logger.warning("Validation error", error=str(e))
        return error_response(str(e), 400)

    except ValueError as e:
        logger.warning("Invalid input", error=str(e))
        return error_response(str(e), 400)

    except Exception as e:
        logger.error("Unexpected error", error=str(e))
        import traceback
        traceback.print_exc()
        return error_response(f"Internal error: {str(e)}", 500)


# Query handlers

def handle_search_services(tenant_id: TenantId, input_data: dict) -> dict:
    """Search services with optional query text"""
    query = input_data.get('text')
    active_only = input_data.get('availableOnly', False)
    services = catalog_service.search_services(tenant_id, query, active_only)
    return success_response([service_to_dict(s) for s in services])


def handle_get_service(tenant_id: TenantId, input_data: dict) -> dict:
    """Get specific service"""
    service_id = input_data.get('serviceId')
    if not service_id:
        return error_response("Missing serviceId", 400)
    
    service = catalog_service.get_service(tenant_id, service_id)
    return service_to_dict(service)


def handle_list_services(tenant_id: TenantId) -> dict:
    """List all services"""
    services = catalog_service.list_all_services(tenant_id)
    return [service_to_dict(s) for s in services]


def handle_list_providers_by_service(tenant_id: TenantId, input_data: dict) -> dict:
    """List providers for specific service"""
    service_id = input_data.get('serviceId')
    if not service_id:
        return error_response("Missing serviceId", 400)
    
    providers = catalog_service.list_providers_by_service(tenant_id, service_id)
    return [provider_to_dict(p) for p in providers]


def handle_get_provider(tenant_id: TenantId, input_data: dict) -> dict:
    """Get specific provider"""
    provider_id = input_data.get('providerId')
    if not provider_id:
        return error_response("Missing providerId", 400)
    
    provider = catalog_service.get_provider(tenant_id, provider_id)
    return provider_to_dict(provider)


def handle_list_providers(tenant_id: TenantId) -> dict:
    """List all providers"""
    providers = catalog_service.list_all_providers(tenant_id)
    return [provider_to_dict(p) for p in providers]



def handle_list_categories(tenant_id: TenantId, input_data: dict) -> dict:
    """List categories"""
    active_only = input_data.get('activeOnly', False)
    categories = catalog_service.list_categories(tenant_id, active_only)
    return [category_to_dict(c) for c in categories]


# Admin operation handlers

def handle_create_category(tenant_id: TenantId, input_data: dict) -> dict:
    """Create new category"""
    category = category_mgmt_service.create_category(
        tenant_id=tenant_id,
        category_id=generate_id('cat'),
        name=input_data['name'],
        description=input_data.get('description'),
        is_active=input_data.get('isActive', True),
        display_order=input_data.get('displayOrder', 0),
        metadata=input_data.get('metadata')
    )
    return category_to_dict(category)


def handle_update_category(tenant_id: TenantId, input_data: dict) -> dict:
    """Update existing category"""
    category = category_mgmt_service.update_category(
        tenant_id=tenant_id,
        category_id=input_data['categoryId'],
        name=input_data.get('name'),
        description=input_data.get('description'),
        is_active=input_data.get('isActive'),
        display_order=input_data.get('displayOrder'),
        metadata=input_data.get('metadata')
    )
    return category_to_dict(category)


def handle_delete_category(tenant_id: TenantId, input_data: dict) -> dict:
    """Delete category"""
    category_id = input_data.get('categoryId')
    if not category_id:
        return error_response("Missing categoryId", 400)
    
    # Get category before deleting
    category = category_repo.get_by_id(tenant_id, category_id)
    if not category:
        return error_response("Category not found", 404)

    category_mgmt_service.delete_category(tenant_id, category_id)
    return category_to_dict(category)


def handle_create_service(tenant_id: TenantId, input_data: dict) -> dict:
    """Create new service"""
    service = service_mgmt_service.create_service(
        tenant_id=tenant_id,
        service_id=generate_id('svc'),
        name=input_data['name'],
        description=input_data.get('description'),
        category=input_data['category'],
        duration_minutes=input_data['durationMinutes'],
        price=input_data.get('price'),
        active=input_data.get('active', True),
        required_room_ids=input_data.get('requiredRoomIds'),
        location_type=input_data.get('locationType')
    )
    return service_to_dict(service)


def handle_update_service(tenant_id: TenantId, input_data: dict) -> dict:
    """Update existing service"""
    logger.info(f"handle_update_service input: {input_data}")
    service = service_mgmt_service.update_service(
        tenant_id=tenant_id,
        service_id=input_data['serviceId'],
        name=input_data.get('name'),
        description=input_data.get('description'),
        category=input_data.get('category'),
        duration_minutes=input_data.get('durationMinutes'),
        price=input_data.get('price'),
        active=input_data.get('active') if 'active' in input_data else input_data.get('available'),
        required_room_ids=input_data.get('requiredRoomIds'),
        location_type=input_data.get('locationType')
    )
    logger.info(f"Service updated result: {service}")
    return service_to_dict(service)


def handle_delete_service(tenant_id: TenantId, input_data: dict) -> dict:
    """Delete service"""
    service_id = input_data.get('serviceId')
    if not service_id:
        return error_response("Missing serviceId", 400)
    
    # Get service before deleting (to return it)
    service = catalog_service.get_service(tenant_id, service_id)
    service_mgmt_service.delete_service(tenant_id, service_id)
    return service_to_dict(service)


def handle_create_provider(tenant_id: TenantId, input_data: dict) -> dict:
    """Create new provider"""
    provider = provider_mgmt_service.create_provider(
        tenant_id=tenant_id,
        provider_id=generate_id('pro'),
        name=input_data['name'],
        bio=input_data.get('bio'),
        service_ids=input_data['serviceIds'],
        timezone=input_data['timezone'],
        metadata=input_data.get('metadata'),
        active=input_data.get('active', True),
        photo_url=input_data.get('photoUrl'),
        photo_url_thumbnail=input_data.get('photoUrlThumbnail')
    )
    return provider_to_dict(provider)


def handle_update_provider(tenant_id: TenantId, input_data: dict) -> dict:
    """Update existing provider"""
    provider = provider_mgmt_service.update_provider(
        tenant_id=tenant_id,
        provider_id=input_data['providerId'],
        name=input_data.get('name'),
        bio=input_data.get('bio'),
        service_ids=input_data.get('serviceIds'),
        timezone=input_data.get('timezone'),
        metadata=input_data.get('metadata'), # Added metadata
        active=input_data.get('active') if 'active' in input_data else input_data.get('available'),
        photo_url=input_data.get('photoUrl'),
        photo_url_thumbnail=input_data.get('photoUrlThumbnail')
    )
    return provider_to_dict(provider)


def handle_delete_provider(tenant_id: TenantId, input_data: dict) -> dict:
    """Delete provider"""
    provider_id = input_data.get('providerId')
    if not provider_id:
        return error_response("Missing providerId", 400)
    
    # Get provider before deleting (to return it)
    provider = catalog_service.get_provider(tenant_id, provider_id)
    provider_mgmt_service.delete_provider(tenant_id, provider_id)
    return provider_to_dict(provider)


def handle_list_categories(tenant_id: TenantId, input_data: dict) -> dict:
    """List categories"""
    active_only = input_data.get('activeOnly', False)
    categories = catalog_service.list_categories(tenant_id, active_only)
    return success_response([category_to_dict(c) for c in categories])


def handle_create_category(tenant_id: TenantId, input_data: dict) -> dict:
    """Create new category"""
    category = category_mgmt_service.create_category(
        tenant_id=tenant_id,
        category_id=generate_id('cat'),
        name=input_data['name'],
        description=input_data.get('description'),
        is_active=input_data.get('isActive', True),
        display_order=input_data.get('displayOrder', 0),
        metadata=input_data.get('metadata')
    )
    return success_response(category_to_dict(category))


def handle_update_category(tenant_id: TenantId, input_data: dict) -> dict:
    """Update existing category"""
    category = category_mgmt_service.update_category(
        tenant_id=tenant_id,
        category_id=input_data['categoryId'],
        name=input_data.get('name'),
        description=input_data.get('description'),
        is_active=input_data.get('isActive'),
        display_order=input_data.get('displayOrder'),
        metadata=input_data.get('metadata')
    )
    return success_response(category_to_dict(category))


def handle_delete_category(tenant_id: TenantId, input_data: dict) -> dict:
    """Delete category"""
    category_id = input_data.get('categoryId')
    if not category_id:
        return error_response("Missing categoryId", 400)
    
    # Get category before deleting
    category = category_repo.get_by_id(tenant_id, category_id)
    if not category:
        return error_response("Category not found", 404)

    category_mgmt_service.delete_category(tenant_id, category_id)
    return success_response(category_to_dict(category))


# Serialization helpers

def service_to_dict(service) -> dict:
    """Convert Service entity to dict"""
    return {
        'serviceId': service.service_id,
        'name': service.name,
        'description': service.description,
        'category': service.category,
        'durationMinutes': service.duration_minutes,
        'price': service.price,
        'available': service.active,
        'requiredRoomIds': service.required_room_ids,
        'locationType': service.location_type
    }


def provider_to_dict(provider) -> dict:
    """Convert Provider entity to dict"""
    return {
        'providerId': provider.provider_id,
        'name': provider.name,
        'bio': provider.bio,
        'serviceIds': provider.service_ids,
        'timezone': provider.timezone,
        'metadata': provider.metadata,
        'available': provider.active,
        'photoUrl': provider.photo_url,
        'photoUrlThumbnail': provider.photo_url_thumbnail
    }



def category_to_dict(category) -> dict:
    """Convert Category entity to dict"""
    return {
        'categoryId': category.category_id,
        'tenantId': str(category.tenant_id),
        'name': category.name,
        'description': category.description,
        'isActive': category.is_active,
        'displayOrder': category.display_order,
        'metadata': category.metadata,
        'createdAt': category.created_at.isoformat(),
        'updatedAt': category.updated_at.isoformat()
    }


def room_to_dict(room) -> dict:
    """Convert Room entity to dict"""
    return {
        'roomId': room.room_id,
        'tenantId': str(room.tenant_id),
        'name': room.name,
        'description': room.description,
        'capacity': room.capacity,
        'status': room.status,
        'metadata': room.metadata,
        'createdAt': room.created_at.isoformat(),
        'updatedAt': room.updated_at.isoformat()
    }


def handle_list_rooms(tenant_id: TenantId) -> dict:
    """List all rooms"""
    rooms = catalog_service.list_rooms(tenant_id)
    return [room_to_dict(r) for r in rooms]


def handle_get_room(tenant_id: TenantId, input_data: dict) -> dict:
    """Get specific room"""
    room_id = input_data.get('roomId')
    if not room_id:
        return error_response("Missing roomId", 400)
    
    room = catalog_service.get_room(tenant_id, room_id)
    return success_response(room_to_dict(room))


def handle_create_room(tenant_id: TenantId, input_data: dict) -> dict:
    """Create new room"""
    room = room_mgmt_service.create_room(
        tenant_id=tenant_id,
        room_id=generate_id('rm'),
        name=input_data['name'],
        description=input_data.get('description'),
        capacity=input_data.get('capacity'),
        status=input_data.get('status', 'ACTIVE'),
        metadata=input_data.get('metadata')
    )
    return success_response(room_to_dict(room))


def handle_update_room(tenant_id: TenantId, input_data: dict) -> dict:
    """Update existing room"""
    room = room_mgmt_service.update_room(
        tenant_id=tenant_id,
        room_id=input_data['roomId'],
        name=input_data.get('name'),
        description=input_data.get('description'),
        capacity=input_data.get('capacity'),
        status=input_data.get('status'),
        metadata=input_data.get('metadata')
    )
    return success_response(room_to_dict(room))


def handle_delete_room(tenant_id: TenantId, input_data: dict) -> dict:
    """Delete room"""
    room_id = input_data.get('roomId')
    if not room_id:
        return error_response("Missing roomId", 400)
    
    # Get room before deleting
    room = catalog_service.get_room(tenant_id, room_id)
    
    room_mgmt_service.delete_room(tenant_id, room_id)
    return success_response(room_to_dict(room))


def handle_generate_presigned_url(tenant_id: TenantId, input_data: dict) -> dict:
    """Generate presigned URL for file upload"""
    if not asset_service:
        return error_response("Asset service not initialized", 500)
        
    file_name = input_data.get('fileName')
    content_type = input_data.get('contentType')
    
    if not file_name or not content_type:
        return error_response("Missing fileName or contentType", 400)
    
    try:
        url = asset_service.generate_upload_url(
            tenant_id=tenant_id,
            file_name=file_name,
            content_type=content_type
        )
        return str(url) # Return raw string as per schema
    except ValidationError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error("Error generating url", error=str(e))
        return error_response("Failed to generate URL", 500)
