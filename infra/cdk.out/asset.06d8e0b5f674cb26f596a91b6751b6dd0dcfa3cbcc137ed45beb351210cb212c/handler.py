"""
Catalog Lambda Handler (Adapter Layer)

AWS Lambda function for catalog queries (services and providers)
Handles both public widget queries and admin panel operations
"""

import json

from shared.infrastructure.dynamodb_repositories import (
    DynamoDBServiceRepository,
    DynamoDBProviderRepository
)
from shared.infrastructure.category_repository import DynamoDBCategoryRepository
from shared.domain.entities import TenantId
from shared.domain.exceptions import EntityNotFoundError, ValidationError
from shared.utils import Logger, success_response, error_response, generate_id, extract_appsync_event

from service import (
    CatalogService,
    ServiceManagementService,
    ProviderManagementService,
    CategoryManagementService
)


# Initialize dependencies (singleton pattern)
service_repo = DynamoDBServiceRepository()
provider_repo = DynamoDBProviderRepository()
category_repo = DynamoDBCategoryRepository()

catalog_service = CatalogService(service_repo, provider_repo, category_repo)
service_mgmt_service = ServiceManagementService(service_repo)
provider_mgmt_service = ProviderManagementService(provider_repo)
category_mgmt_service = CategoryManagementService(category_repo)

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
        
        else:
            return error_response(f"Unknown operation: {field}", 400)

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
    services = catalog_service.search_services(tenant_id, query)
    return success_response([service_to_dict(s) for s in services])


def handle_get_service(tenant_id: TenantId, input_data: dict) -> dict:
    """Get specific service"""
    service_id = input_data.get('serviceId')
    if not service_id:
        return error_response("Missing serviceId", 400)
    
    service = catalog_service.get_service(tenant_id, service_id)
    return success_response(service_to_dict(service))


def handle_list_services(tenant_id: TenantId) -> dict:
    """List all services"""
    services = catalog_service.list_all_services(tenant_id)
    return success_response([service_to_dict(s) for s in services])


def handle_list_providers_by_service(tenant_id: TenantId, input_data: dict) -> dict:
    """List providers for specific service"""
    service_id = input_data.get('serviceId')
    if not service_id:
        return error_response("Missing serviceId", 400)
    
    providers = catalog_service.list_providers_by_service(tenant_id, service_id)
    return success_response([provider_to_dict(p) for p in providers])


def handle_get_provider(tenant_id: TenantId, input_data: dict) -> dict:
    """Get specific provider"""
    provider_id = input_data.get('providerId')
    if not provider_id:
        return error_response("Missing providerId", 400)
    
    provider = catalog_service.get_provider(tenant_id, provider_id)
    return success_response(provider_to_dict(provider))


def handle_list_providers(tenant_id: TenantId) -> dict:
    """List all providers"""
    providers = catalog_service.list_all_providers(tenant_id)
    return success_response([provider_to_dict(p) for p in providers])



def handle_list_categories(tenant_id: TenantId, input_data: dict) -> dict:
    """List categories"""
    active_only = input_data.get('activeOnly', False)
    categories = catalog_service.list_categories(tenant_id, active_only)
    return success_response([category_to_dict(c) for c in categories])


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
        active=input_data.get('active', True)
    )
    return success_response(service_to_dict(service))


def handle_update_service(tenant_id: TenantId, input_data: dict) -> dict:
    """Update existing service"""
    service = service_mgmt_service.update_service(
        tenant_id=tenant_id,
        service_id=input_data['serviceId'],
        name=input_data.get('name'),
        description=input_data.get('description'),
        category=input_data.get('category'),
        duration_minutes=input_data.get('durationMinutes'),
        price=input_data.get('price'),
        active=input_data.get('active')
    )
    return success_response(service_to_dict(service))


def handle_delete_service(tenant_id: TenantId, input_data: dict) -> dict:
    """Delete service"""
    service_id = input_data.get('serviceId')
    if not service_id:
        return error_response("Missing serviceId", 400)
    
    # Get service before deleting (to return it)
    service = catalog_service.get_service(tenant_id, service_id)
    service_mgmt_service.delete_service(tenant_id, service_id)
    return success_response(service_to_dict(service))


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
        active=input_data.get('active', True)
    )
    return success_response(provider_to_dict(provider))


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
        active=input_data.get('active')
    )
    return success_response(provider_to_dict(provider))


def handle_delete_provider(tenant_id: TenantId, input_data: dict) -> dict:
    """Delete provider"""
    provider_id = input_data.get('providerId')
    if not provider_id:
        return error_response("Missing providerId", 400)
    
    # Get provider before deleting (to return it)
    provider = catalog_service.get_provider(tenant_id, provider_id)
    provider_mgmt_service.delete_provider(tenant_id, provider_id)
    return success_response(provider_to_dict(provider))


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
        'available': service.active
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
        'available': provider.active
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
