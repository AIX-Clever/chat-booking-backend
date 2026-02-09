"""
Public Link Status Handler

Manages the public page publication status for tenants.
Provides query getPublicLinkStatus and mutation setPublicLinkStatus.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, List

from shared.domain.entities import TenantId
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
    
    Supports:
    - getPublicLinkStatus: Query to get publication status and checklist
    - setPublicLinkStatus: Mutation to toggle publication status
    """
    logger = Logger()
    logger.info("Public Link Status Handler", event=event)

    try:
        field, tenant_id_str, input_data = extract_appsync_event(event)
        
        if not tenant_id_str:
            return error_response("Tenant ID not found in context", 400)
        
        tenant_id = TenantId(tenant_id_str)
        
        if field == "getPublicLinkStatus":
            return handle_get_status(tenant_id, logger)
        elif field == "setPublicLinkStatus":
            is_published = input_data.get("isPublished") if input_data else event.get("arguments", {}).get("isPublished")
            return handle_set_status(tenant_id, is_published, logger)
        else:
            return error_response(f"Unknown field: {field}", 400)
            
    except Exception as e:
        logger.error("Public link status handler failed", error=str(e))
        raise e


def handle_get_status(tenant_id: TenantId, logger: Logger) -> Dict[str, Any]:
    """Get current publication status with completeness checklist."""
    
    tenant_repo = DynamoDBTenantRepository()
    tenant = tenant_repo.get_by_id(tenant_id)
    
    if not tenant:
        return error_response("Tenant not found", 404)
    
    # Build completeness checklist
    checklist = build_completeness_checklist(tenant_id, tenant, logger)
    
    # Calculate percentage
    complete_items = sum(1 for item in checklist if item["status"] == "COMPLETE")
    total_items = len(checklist)
    percentage = int((complete_items / total_items) * 100) if total_items > 0 else 0
    
    # Build public URL
    public_url = f"{PUBLIC_LINK_BASE_URL}/{tenant.slug}" if tenant.slug else None
    
    return {
        "isPublished": tenant.is_published,
        "publishedAt": tenant.published_at.isoformat() + "Z" if tenant.published_at else None,
        "slug": tenant.slug,
        "publicUrl": public_url,
        "completenessChecklist": checklist,
        "completenessPercentage": percentage,
    }


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


def build_completeness_checklist(tenant_id: TenantId, tenant: Any, logger: Logger) -> List[Dict[str, str]]:
    """Build checklist of required/recommended items for publication."""
    
    checklist = []
    
    # 1. Business Name (required)
    checklist.append({
        "item": "business_name",
        "status": "COMPLETE" if tenant.name else "MISSING",
        "label": "Nombre del negocio",
    })
    
    # 2. Slug (required for URL)
    checklist.append({
        "item": "slug",
        "status": "COMPLETE" if tenant.slug else "MISSING",
        "label": "URL personalizada (slug)",
    })
    
    # 3. At least one active service (required)
    service_repo = DynamoDBServiceRepository()
    services = service_repo.list_by_tenant(tenant_id)
    active_services = [s for s in services if s.active]
    checklist.append({
        "item": "services",
        "status": "COMPLETE" if active_services else "MISSING",
        "label": "Al menos 1 servicio activo",
    })
    
    # 4. At least one active provider (required)
    provider_repo = DynamoDBProviderRepository()
    providers = provider_repo.list_by_tenant(tenant_id)
    active_providers = [p for p in providers if p.active]
    checklist.append({
        "item": "providers",
        "status": "COMPLETE" if active_providers else "MISSING",
        "label": "Al menos 1 profesional activo",
    })
    
    # 5. Provider availability configured (required)
    has_availability = False
    if active_providers:
        availability_repo = DynamoDBAvailabilityRepository()
        for provider in active_providers[:3]:  # Check first 3 providers max
            try:
                avail = availability_repo.get_by_provider(tenant_id, provider.provider_id)
                if avail and len(avail) > 0:
                    has_availability = True
                    break
            except Exception:
                pass
    
    checklist.append({
        "item": "availability",
        "status": "COMPLETE" if has_availability else "MISSING",
        "label": "Horarios configurados",
    })
    
    # 6. Logo/Photo (recommended)
    settings = tenant.settings or {}
    has_photo = bool(settings.get("photoUrl") or settings.get("logo"))
    checklist.append({
        "item": "photo",
        "status": "COMPLETE" if has_photo else "RECOMMENDED",
        "label": "Logo o foto de perfil",
    })
    
    # 7. Description/Bio (recommended)
    has_bio = bool(settings.get("bio") or settings.get("description"))
    checklist.append({
        "item": "bio",
        "status": "COMPLETE" if has_bio else "RECOMMENDED",
        "label": "Descripción del negocio",
    })
    
    return checklist
