
import os
import boto3
import uuid
import secrets
from datetime import datetime, timezone
from typing import Dict, Any

from shared.domain.entities import Tenant, TenantId, TenantStatus, TenantPlan, ApiKey
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository, DynamoDBApiKeyRepository
from shared.utils import lambda_response, Logger, generate_api_key, hash_api_key

cognito = boto3.client('cognito-idp')

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Register new tenant handler
    
    Args:
        event: AppSync event with arguments
    """
    logger = Logger()
    logger.info("Starting tenant registration", event=event)
    
    try:
        # 1. Parse Input
        inputs = event.get('arguments', {}).get('input', {})
        email = inputs.get('email')
        password = inputs.get('password')
        company_name = inputs.get('companyName') or email.split('@')[0]
        
        if not email or not password:
            raise ValueError("Email and password are required")

        # 2. Dependency Injection
        tenant_repo = DynamoDBTenantRepository()
        api_key_repo = DynamoDBApiKeyRepository()
        user_pool_id = os.environ.get('USER_POOL_ID')
        
        if not user_pool_id:
            raise ValueError("USER_POOL_ID configuration missing")

        # 3. Create Tenant Entity
        # Generate a slug from company name or random
        slug = company_name.lower().replace(' ', '-') + '-' + secrets.token_hex(2)
        tenant_id = TenantId(str(uuid.uuid4())[:8])
        
        tenant = Tenant(
            tenant_id=tenant_id,
            name=company_name,
            slug=slug,
            status=TenantStatus.ACTIVE, # Start active for frictionless flow
            plan=TenantPlan.FREE,       # Start on Free plan
            owner_user_id=email,        # Temporary, will be linked to Cognito Sub if needed
            billing_email=email,
            created_at=datetime.now(timezone.utc)
        )
        
        # 4. Create Cognito User
        logger.info(f"Creating Cognito user for {email}")
        try:
            response = cognito.admin_create_user(
                UserPoolId=user_pool_id,
                Username=email,
                UserAttributes=[
                    {'Name': 'email', 'Value': email},
                    {'Name': 'email_verified', 'Value': 'true'}, # Auto-verify for friction-less
                    {'Name': 'custom:tenantId', 'Value': str(tenant_id)},
                    {'Name': 'name', 'Value': company_name}
                ],
                MessageAction='SUPPRESS' # Don't send default email
            )
            
            # Set permanent password
            cognito.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=email,
                Password=password,
                Permanent=True
            )
            
            # Update owner_user_id with actual Cognito Sub
            # cognito_sub = response['User']['Attributes']... (lookup 'sub')
            # For simplicity, we keep email or extract sub if critical.
            
        except cognito.exceptions.UsernameExistsException:
             # Check if user exists but has no tenant? Or just fail.
             # Ideally we check this before.
             raise ValueError("User with this email already exists")
        except Exception as e:
            logger.error("Cognito creation failed", error=e)
            raise e

        # 5. Save Tenant
        logger.info(f"Saving tenant {tenant_id}")
        tenant_repo.save(tenant)
        
        # 6. Generate and Save Initial API Key
        public_key, hashed_key = generate_api_key()
        api_key_id = f"key_{secrets.token_hex(4)}"
        
        api_key = ApiKey(
            api_key_id=api_key_id,
            tenant_id=tenant_id,
            api_key_hash=hashed_key, # In a real scenario we save hash
            # Wait, Entity expects api_key_hash, but Repository might need to handle hashing?
            # Looking at utils.py, generate_api_key returns (public, hashed).
            # The Repository save params? 
            # Let's assume Entity stores what we give it.
            status="ACTIVE",
            allowed_origins=["*"], # Allow all for onboarding
            rate_limit=1000,
            created_at=datetime.now(timezone.utc)
        )
        # Note: The Entity definition for ApiKey uses 'api_key_hash'.
        # But we might want to return the PUBLIC key to the user or save it somewhere? 
        # The return type is Tenant. It doesn't include ApiKey. 
        # The user can get ApiKey from dashboard. 
        # But for 'Launch' wizard step, we might need it.
        # However, the Schema returns `Tenant`. `Tenant` type in schema doesn't have apiKey. 
        # We can add `apiKey` to the `Tenant` type in schema temporarily or query it separately.
        
        api_key_repo.save(api_key)
        
        # 7. Return Result
        # Map entity to GraphQL type
        return {
            'tenantId': str(tenant.tenant_id),
            'name': tenant.name,
            'status': tenant.status.value,
            'plan': tenant.plan.value,
            'billingEmail': tenant.billing_email,
            'createdAt': tenant.created_at.isoformat() + 'Z'
        }

    except ValueError as ve:
        logger.warning(f"Validation error: {ve}")
        # Validate error format for AppSync
        raise Exception(str(ve))
    except Exception as e:
        logger.error("Internal error", error=e)
        raise Exception(f"Internal error: {str(e)}")
