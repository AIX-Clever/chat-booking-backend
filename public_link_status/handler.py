"""
Public Link Status Handler

Manages the public page publication status for tenants.
Provides query getPublicLinkStatus and mutation setPublicLinkStatus.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from shared.domain.entities import TenantId, TenantPlan
from shared.infrastructure.dynamodb_repositories import (
    DynamoDBTenantRepository,
    DynamoDBServiceRepository,
    DynamoDBProviderRepository,
)
from shared.infrastructure.availability_repository import DynamoDBAvailabilityRepository
from shared.utils import (
    Logger,
    extract_appsync_event,
    error_response,
)

# Base URL for public profile
PUBLIC_LINK_BASE_URL = os.environ.get("PUBLIC_LINK_BASE_URL", "https://agendar.holalucia.cl")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handler for public link status operations.
    """
    logger = Logger()
    logger.info("Public Link Status Handler", event=event)

    try:
        # Use project standard helper for event extraction
        field, tenant_id_str, input_data = extract_appsync_event(event)
        
        tenant_id = TenantId(tenant_id_str)
        
        if field == "getPublicLinkStatus":
            # get providerId from arguments
            provider_id = event.get("arguments", {}).get("providerId")
            return handle_get_status(tenant_id, provider_id, logger)
        elif field == "setPublicLinkStatus":
            is_published = input_data.get("isPublished")
            return handle_set_status(tenant_id, is_published, logger)
        else:
            return error_response(f"Unknown field: {field}", 400)
            
    except Exception as e:
        logger.error("Public link status handler failed", error=str(e))
        # AppSync expects the exception message as the error
        raise e


def handle_get_status(tenant_id: TenantId, provider_id: Optional[str], logger: Logger) -> Dict[str, Any]:
    """Get current publication status with dynamic checklist."""
    
    tenant_repo = DynamoDBTenantRepository()
    tenant = tenant_repo.get_by_id(tenant_id)
    
    if not tenant:
        return error_response("Tenant not found", 404)
    
    # Build dynamic checklist based on requirements
    checklist = build_comprehensive_checklist(tenant_id, tenant, provider_id, logger)
    
    # Calculate percentage based on required items
    required_items = [item for item in checklist if item.get("isRequired", True)]
    complete_required = sum(1 for item in required_items if item["status"] == "COMPLETE")
    total_required = len(required_items)
    
    percentage = int((complete_required / total_required) * 100) if total_required > 0 else 0
    
    # Determine Public Slug
    # Default: Tenant Slug
    public_slug = tenant.slug
    
    # Logic for resolving the target slug:
    # 1. If provider_id is specified, prioritize that professional's slug.
    # 2. If LITE plan and no provider_id, take the first active provider's slug (solopreneur).
    # 3. Fallback to center slug.
    
    try:
        active_providers = []
        if provider_id or tenant.plan == TenantPlan.LITE:
            provider_repo = DynamoDBProviderRepository()
            providers = provider_repo.list_by_tenant(tenant_id)
            active_providers = [p for p in providers if p.active]

        target_provider = None
        if provider_id:
            # If specific provider requested, look for it
            target_provider = next((p for p in active_providers if p.provider_id == provider_id), None)
        elif tenant.plan == TenantPlan.LITE and active_providers:
            # For LITE, if no specific provider requested, take the first one with a slug
            target_provider = next((p for p in active_providers if p.slug), None)
        
        if target_provider and target_provider.slug:
            public_slug = target_provider.slug
            logger.info(f"Using Provider Slug: {public_slug}", provider_id=target_provider.provider_id)
            
    except Exception as e:
        logger.warning("Failed to resolve provider slug for public link", error=str(e))
        # Fallback to tenant.slug is already set
    
    # Build public URL
    public_url = f"{PUBLIC_LINK_BASE_URL}/{public_slug}" if public_slug else None
    
    return {
        "isPublished": tenant.is_published,
        "publishedAt": tenant.published_at.isoformat() + "Z" if tenant.published_at else None,
        "slug": public_slug,
        "publicUrl": public_url,
        "completenessChecklist": checklist,
        "completenessPercentage": percentage,
    }



def build_comprehensive_checklist(tenant_id: TenantId, tenant: Any, provider_id: Optional[str], logger: Logger) -> List[Dict[str, Any]]:
    """
    Builds a checklist as a Success Guide including:
    - Center data (Business Name, Slug, Rooms) -> Granular
    - Services & Categories
    - Professional specific data (Bio, Photo, Availability) -> Granular
    """
    checklist = []
    
    # 1. Base Business Configuration
    from shared.domain.entities import TenantPlan
    
    # Only show Business Name for non-LITE plans (Solopreneurs use their own name)
    if tenant.plan != TenantPlan.LITE:
        checklist.append({
            "item": "business_name",
            "status": "COMPLETE" if tenant.name else "MISSING",
            "label": "Nombre del negocio",
            "isRequired": True,
            "actionUrl": "/settings?tab=profile"
        })
    
    checklist.append({
        "item": "slug",
        "status": "COMPLETE" if tenant.slug else "MISSING",
        "label": "URL personalizada (slug)",
        "isRequired": True,
        "actionUrl": "/settings/profile"
    })

    # Logo (Center branding) - Optional for LITE
    if tenant.plan != TenantPlan.LITE:
        settings = tenant.settings or {}
        has_logo = bool(settings.get("photoUrl") or settings.get("logo"))
        checklist.append({
            "item": "logo",
            "status": "COMPLETE" if has_logo else "MISSING",
            "label": "Logo del Centro",
            "isRequired": False,
            "actionUrl": "/settings?tab=profile"
        })

    # 2. Services Infrastructure
    from shared.infrastructure.dynamodb_repositories import DynamoDBServiceRepository
    service_repo = DynamoDBServiceRepository()
    services = service_repo.list_by_tenant(tenant_id)
    active_services = [s for s in services if s.active]
    
    has_categories = any(s.category for s in services)
    
    # Categories are essential for organization
    checklist.append({
        "item": "categories",
        "status": "COMPLETE" if has_categories else "MISSING",
        "label": "Categorías de servicios",
        "isRequired": True,
        "actionUrl": "/services"
    })
    
    checklist.append({
        "item": "services",
        "status": "COMPLETE" if active_services else "MISSING",
        "label": "Servicios configurados",
        "isRequired": True,
        "actionUrl": "/services"
    })

    # 3. Rooms/Infrastructure (Exclude for LITE)
    from shared.domain.entities import TenantPlan
    if tenant.plan != TenantPlan.LITE:
        from shared.infrastructure.dynamodb_repositories import DynamoDBRoomRepository
        room_repo = DynamoDBRoomRepository()
        rooms = room_repo.list_by_tenant(tenant_id)
        checklist.append({
            "item": "rooms",
            "status": "COMPLETE" if rooms else "MISSING",
            "label": "Salas (boxes/consultorios)",
            "isRequired": True,
            "actionUrl": "/rooms"
        })

    # 4. Professional Specific Logic
    if provider_id:
        from shared.infrastructure.dynamodb_repositories import DynamoDBProviderRepository
        from shared.infrastructure.availability_repository import DynamoDBAvailabilityRepository
        
        provider_repo = DynamoDBProviderRepository()
        provider = provider_repo.get_by_id(tenant_id, provider_id)
        
        if provider:
            # Split Bio and Photo
            checklist.append({
                "item": "prof_bio",
                "status": "COMPLETE" if provider.bio else "MISSING",
                "label": f"Biografía de {provider.name}",
                "isRequired": True,
                "actionUrl": f"/users?providerId={provider_id}"
            })

            checklist.append({
                "item": "prof_photo",
                "status": "COMPLETE" if provider.photo_url else "MISSING",
                "label": f"Foto de {provider.name}",
                "isRequired": True,
                "actionUrl": f"/users?providerId={provider_id}"
            })
            
            # Professional availability
            availability_repo = DynamoDBAvailabilityRepository()
            avail = availability_repo.get_provider_availability(tenant_id, provider_id)
            checklist.append({
                "item": "prof_availability",
                "status": "COMPLETE" if avail and len(avail) > 0 else "MISSING",
                "label": f"Disponibilidad de {provider.name}",
                "isRequired": True,
                "actionUrl": f"/availability?providerId={provider_id}"
            })
            
            # Professional associated services
            checklist.append({
                "item": "prof_services",
                "status": "COMPLETE" if provider.service_ids else "MISSING",
                "label": f"Servicios asignados a {provider.name}",
                "isRequired": True,
                "actionUrl": f"/users?providerId={provider_id}"
            })
    else:
        # Global Center / Pro Version Checklist
        # At least one professional active
        from shared.infrastructure.dynamodb_repositories import DynamoDBProviderRepository
        provider_repo = DynamoDBProviderRepository()
        providers = provider_repo.list_by_tenant(tenant_id)
        active_providers = [p for p in providers if p.active]
        
        checklist.append({
            "item": "providers",
            "status": "COMPLETE" if active_providers else "MISSING",
            "label": "Al menos 1 profesional activo",
            "isRequired": True,
            "actionUrl": "/users"
        })
        
    return checklist


def handle_set_status(tenant_id: TenantId, is_published: bool, logger: Logger) -> Dict[str, Any]:
    """Toggle publication status with plan validation and rate limiting."""
    
    tenant_repo = DynamoDBTenantRepository()
    tenant = tenant_repo.get_by_id(tenant_id)
    
    if not tenant:
        return error_response("Tenant not found", 404)
    
    # Security: Validate tenant has active status
    from shared.domain.entities import TenantStatus
    if tenant.status not in [TenantStatus.ACTIVE, TenantStatus.TRIAL]:
        logger.warning("Attempt to publish with inactive status", 
                      tenant_id=str(tenant_id), 
                      status=tenant.status.value)
        return error_response(f"Cannot publish: tenant status is {tenant.status.value}", 403)
    
    # Security: Rate limiting - max 5 toggles per minute
    rate_limit_key = f"publish_toggle_{tenant_id}"
    if not check_rate_limit(rate_limit_key, max_requests=5, window_seconds=60):
        logger.warning("Rate limit exceeded for publish toggle", tenant_id=str(tenant_id))
        return error_response("Rate limit exceeded. Please wait before toggling again.", 429)
    
    # If publishing for the first time, set publishedAt
    published_at = tenant.published_at
    if is_published and not tenant.published_at:
        published_at = datetime.now(timezone.utc)
    
    # Update tenant
    tenant.is_published = is_published
    tenant.published_at = published_at
    
    tenant_repo.save(tenant)
    
    logger.info("Publication status updated", 
                tenant_id=str(tenant_id), 
                is_published=is_published)
    
    return {
        "success": True,
        "isPublished": is_published,
        "publishedAt": published_at.isoformat() + "Z" if published_at else None,
    }


# Simple in-memory rate limiter (for Lambda, consider DynamoDB for production)
_rate_limit_cache: Dict[str, List[float]] = {}

def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """
    Simple rate limiter using in-memory cache.
    Returns True if request is allowed, False if rate limit exceeded.
    
    Note: In Lambda, this is per-instance. For stricter limits, use DynamoDB.
    """
    import time
    current_time = time.time()
    
    if key not in _rate_limit_cache:
        _rate_limit_cache[key] = []
    
    # Clean old entries outside the window
    _rate_limit_cache[key] = [
        t for t in _rate_limit_cache[key] 
        if current_time - t < window_seconds
    ]
    
    # Check if under limit
    if len(_rate_limit_cache[key]) >= max_requests:
        return False
    
    # Add current request
    _rate_limit_cache[key].append(current_time)
    return True
