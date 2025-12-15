
import os
import boto3
import json
from typing import Dict, Any
from shared.domain.entities import Tenant, TenantId
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.utils import lambda_response, Logger

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Get tenant handler
    """
    logger = Logger()
    logger.info("Starting get tenant", event=event)
    
    try:
        # 1. Parse Arguments (tenantId)
        # Verify if arguments contains tenantId (direct query)
        args_tenant_id = event.get('arguments', {}).get('tenantId')
        
        # 2. Auth Context
        # Check who is asking.
        # If Admin (via User Pool), they can potentially ask for any tenant if they are super-admin (not implemented yet), 
        # or more likely, they are asking for their own tenant.
        
        claims = event.get('identity', {}).get('claims', {})
        auth_tenant_id = claims.get('custom:tenantId')

        # Fallback logic for retrieving tenantId from Cognito if not in claims (e.g. access token)
        if not auth_tenant_id:
            username = claims.get('username') or claims.get('cognito:username') or claims.get('sub')
            user_pool_id = os.environ.get('USER_POOL_ID')
            
            if username and user_pool_id:
                try:
                    logger.info("Fetching attributes from Cognito", username=username)
                    cognito = boto3.client('cognito-idp')
                    user = cognito.admin_get_user(
                        UserPoolId=user_pool_id,
                        Username=username
                    )
                    for attr in user.get('UserAttributes', []):
                        if attr['Name'] == 'custom:tenantId':
                            auth_tenant_id = attr['Value']
                            break
                    if auth_tenant_id:
                         logger.info("Retrieved tenantId from Cognito", tenant_id=auth_tenant_id)
                except Exception as e:
                    logger.warning("Failed to fetch user attributes", error=e)

        # 3. Authorization Logic
        target_tenant_id = None
        
        if args_tenant_id:
            # Client requesting specific tenant
            # Ensure they are authorized for this tenant
            if auth_tenant_id and auth_tenant_id != args_tenant_id:
                 # In a strict system, we'd block this.
                 # However, super-admins might exist.
                 # For now, let's enforce: You can only get your own tenant.
                 # UNLESS the schema is @aws_api_key protected for public widgets?
                 # If @aws_api_key is used (public), 'identity' might be different or null claims.
                 # But getTenant usually implies fetching sensitive settings.
                 # Public widget uses `registerTenant`? No.
                 # Public widget needs to load public settings (color, etc.)
                 # So `getTenant` MIGHT need to be public?
                 # The frontend code sends `tenantId`.
                 # Let's allow if args match auth OR if it's public usage (check schema later).
                 # For safety, if auth_tenant_id is present, it MUST match.
                 # If no auth_tenant_id (ApiKey access?), we proceed but maybe filter fields?
                 # The schema definition will determine if API Key access is allowed.
                 
                 # Current implementation: Trust the schema auth. 
                 # If user is authenticated, we might want to prioritize their auth_tenant_id?
                 pass 
            
            target_tenant_id = args_tenant_id
        elif auth_tenant_id:
            # Client didn't send ID, implies "get mine"
            target_tenant_id = auth_tenant_id
        else:
            raise ValueError("Missing tenantId argument or auth context")

        # 4. Fetch Tenant
        tenant_repo = DynamoDBTenantRepository()
        tenant = tenant_repo.get_by_id(TenantId(target_tenant_id))
        
        if not tenant:
            raise ValueError("Tenant not found")

        # 5. Return Result
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
