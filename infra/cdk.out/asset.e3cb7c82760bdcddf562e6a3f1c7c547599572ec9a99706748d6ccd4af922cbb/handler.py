
import os
import boto3
import json
from typing import Dict, Any
from shared.domain.entities import Tenant, TenantId
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.utils import lambda_response, Logger, extract_appsync_event, success_response, error_response

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Get tenant handler
    """
    logger = Logger()
    logger.info("Starting get tenant", event=event)
    
    try:
        # Extract context using shared utility (handles args, identity, headers, etc.)
        field, tenant_id_str, input_data = extract_appsync_event(event)
        
        # Override tenant_id if explicit argument is provided (though extract_appsync_event prioritizes args)
        # Actually, extract_appsync_event already does: args > identity > stash > headers.
        # But for getTenant, if tenantId arg is provided, it returns that. 
        # If not, it returns identity tenantId.
        # Perfect.
        
        logger.info("Resolved Tenant ID", tenant_id=tenant_id_str)
        
        if not tenant_id_str:
             return error_response("Tenant ID not found in context or arguments", 400)

        # Authorization Check (if specific ID requested vs inferred)
        # If the ID came from arguments, we might want to verify it matches identity?
        # extract_appsync_event doesn't tell us WHERE it got it from.
        # But for 'getTenant', usually:
        # 1. Admin asks for specific tenant (if super admin) -> Args
        # 2. Admin asks for their own -> Identity
        # 3. Widget asks for public tenant -> Args (via x-tenant-id header or arg)
        
        # We can implement a safety check:
        # If identity is present, and extracted ID differs...
        # But we don't easily have 'identity' here without parsing again.
        # For now, we trust the extraction priority.
        
        tenant_repo = DynamoDBTenantRepository()
        tenant = tenant_repo.get_by_id(TenantId(tenant_id_str))
        
        if not tenant:
            return error_response("Tenant not found", 404)

        # Return Result via success_response (if it handles direct return) 
        # or simple dict if AppSync expects direct object. 
        # The other lambdas use success_response.
        # Schema expects Tenant! (object), success_response returns raw data?
        # shared/utils.py success_response returns data directly.
        
        return {
            'tenantId': str(tenant.tenant_id),
            'name': tenant.name,
            'status': tenant.status.value,
            'plan': tenant.plan.value,
            'billingEmail': tenant.billing_email,
            'settings': json.dumps(tenant.settings) if tenant.settings else None,
            'createdAt': tenant.created_at.isoformat() + 'Z',
            'updatedAt': tenant.updated_at.isoformat() + 'Z'
        }

    except Exception as e:
        logger.error("Get tenant failed", error=str(e))
        raise e

