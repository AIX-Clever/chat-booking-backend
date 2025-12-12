
import os
import boto3
import json
from typing import Dict, Any
from shared.domain.entities import Tenant, TenantId
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.utils import lambda_response, Logger, extract_tenant_id

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update tenant handler
    """
    logger = Logger()
    logger.info("Starting tenant update", event=event)
    
    try:
        # 1. Auth check & Tenant extraction
        # For User Pool auth, claims are in identity
        claims = event.get('identity', {}).get('claims', {})
        tenant_id_str = claims.get('custom:tenantId')
        
        # Fallback to arguments if testing or different auth mode (but ideally enforced)
        if not tenant_id_str:
            # Maybe passed in context?
            tenant_id_str = event.get('identity', {}).get('claims', {}).get('tenantId')

        if not tenant_id_str:
            logger.error("No tenantId in claims", claims=claims)
            raise ValueError("Unauthorized: Missing tenant context")

        tenant_id = TenantId(tenant_id_str)
        
        # 2. Parse Input
        inputs = event.get('arguments', {}).get('input', {})
        
        # 3. Dependency Injection
        tenant_repo = DynamoDBTenantRepository()
        
        # 4. Get Existing Tenant
        tenant = tenant_repo.get_by_id(tenant_id)
        if not tenant:
            raise ValueError("Tenant not found")
            
        # 5. Update Fields
        if 'name' in inputs:
            tenant.name = inputs['name']
        if 'billingEmail' in inputs:
            tenant.billing_email = inputs['billingEmail']
        if 'settings' in inputs:
            # Merge settings
            new_settings = json.loads(inputs['settings']) if isinstance(inputs['settings'], str) else inputs['settings']
            tenant.settings.update(new_settings)
            
        # 6. Save
        tenant_repo.save(tenant)
        
        # 7. Return Result
        return {
            'tenantId': str(tenant.tenant_id),
            'name': tenant.name,
            'status': tenant.status.value,
            'plan': tenant.plan.value,
            'billingEmail': tenant.billing_email,
            'createdAt': tenant.created_at.isoformat() + 'Z'
            # Note: Return settings if needed, but schema didn't define settings in Tenant type yet.
            # I should add 'settings: AWSJSON' to Tenant type in schema for consistency.
        }

    except Exception as e:
        logger.error("Update failed", error=e)
        raise e
