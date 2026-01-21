
import os
import boto3
import uuid
import json
import secrets
from datetime import datetime, timezone
from typing import Dict, Any

from shared.domain.entities import Tenant, TenantId, TenantStatus, TenantPlan, ApiKey
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository, DynamoDBApiKeyRepository
from shared.utils import lambda_response, Logger, generate_api_key, hash_api_key


# Lazy-initialized clients to avoid NoRegionError during test collection
cognito = None
workflows_table = None
user_roles_table = None

# Load Default Flow
try:
    with open(os.path.join(os.path.dirname(__file__), 'base_workflow.json'), 'r') as f:
        DEFAULT_FLOW = json.load(f)
except Exception as e:
    print(f"Warning: Could not load default flow from local file: {e}")
    DEFAULT_FLOW = {}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Register new tenant handler
    
    Args:
        event: AppSync event with arguments
    """
    global cognito, workflows_table, user_roles_table
    
    # Lazy initialization of boto3 clients
    if cognito is None:
        cognito = boto3.client('cognito-idp')
    if workflows_table is None:
        workflows_table = boto3.resource('dynamodb').Table(os.environ.get('WORKFLOWS_TABLE', 'ChatBooking-Workflows'))
    if user_roles_table is None:
        user_roles_table = boto3.resource('dynamodb').Table(os.environ.get('USER_ROLES_TABLE', 'ChatBooking-UserRoles'))
    
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
            plan=TenantPlan.LITE,       # Start on Lite plan
            owner_user_id=email,        # Temporary, will be linked to Cognito Sub if needed
            billing_email=email,
            created_at=datetime.now(timezone.utc)
        )
        
        # 4. Create Cognito User
        logger.info(f"Creating Cognito user for {email}")
        user_sub = email # Default fallback
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
            
            # Extract User Sub (UUID)
            for attr in response.get('User', {}).get('Attributes', []):
                if attr['Name'] == 'sub':
                    user_sub = attr['Value']    
                    break
            
            logger.info(f"Created Cognito user {email} with sub {user_sub}")

            # Set permanent password
            cognito.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=email,
                Password=password,
                Permanent=True
            )
            
        except cognito.exceptions.UsernameExistsException:
             # Check if user exists but has no tenant? Or just fail.
             # Ideally we check this before.
             raise ValueError("User with this email already exists")
        except Exception as e:
            logger.error("Cognito creation failed", error=e)
            raise e

        # Update Tenant with real owner_user_id (Sub)
        tenant.owner_user_id = user_sub

        # 5. Save Tenant
        logger.info(f"Saving tenant {tenant_id}")
        tenant_repo.save(tenant)
        
        # 6. Generate and Save Initial API Key
        public_key, hashed_key = generate_api_key()
        api_key_id = f"key_{secrets.token_hex(4)}"
        
        api_key = ApiKey(
            api_key_id=api_key_id,
            tenant_id=tenant_id,
            api_key_hash=hashed_key, 
            status="ACTIVE",
            allowed_origins=["*"], 
            rate_limit=1000,
            created_at=datetime.now(timezone.utc)
        )
        
        api_key_repo.save(api_key)

        # 7. Create Default Workflow
        if DEFAULT_FLOW:
            try:
                workflow_id = str(uuid.uuid4())
                current_time = datetime.now(timezone.utc).isoformat()
                
                # Clone and prepare item
                # IMPORTANT: In DynamoDB repository we store steps as a Map
                # DEFAULT_FLOW["steps"] is already a dict, which is perfect for DynamoDB Map
                
                workflow_item = {
                    'tenantId': str(tenant_id),
                    'workflowId': workflow_id,
                    'name': DEFAULT_FLOW.get('name', 'Default Flow'),
                    'description': DEFAULT_FLOW.get('description', ''),
                    'steps': DEFAULT_FLOW.get('steps', {}),
                    'isActive': True,
                    'createdAt': current_time,
                    'updatedAt': current_time,
                    'metadata': {}
                }
                
                logger.info(f"Creating default workflow for tenant {tenant_id}")
                workflows_table.put_item(Item=workflow_item)
            except Exception as w_error:
                # Don't fail registration if workflow creation fails, just log it
                logger.error(f"Failed to create default workflow: {w_error}")

        # 8. Create User Role (For Admin Panel Visibility)
        try:
             current_time = datetime.now(timezone.utc).isoformat()
             user_role_item = {
                 'userId': user_sub,  # Use Cognito Sub (UUID)
                 'tenantId': str(tenant_id),
                 'email': email,
                 'name': company_name,
                 'role': 'OWNER',
                 'status': 'ACTIVE',
                 'createdAt': current_time,
                 'updatedAt': current_time
             }
             logger.info(f"Creating owner user role for {email} (sub: {user_sub})")
             user_roles_table.put_item(Item=user_role_item)
        except Exception as u_error:
             # Don't fail registration, but log critical error
             logger.error(f"Failed to create user role for owner: {u_error}")
        
        # 9. Return Result
        # Map entity to GraphQL type
        return {
            'tenantId': str(tenant.tenant_id),
            'name': tenant.name,
            'slug': tenant.slug,
            'status': tenant.status.value,
            'plan': tenant.plan.value,
            'ownerUserId': user_sub,
            'billingEmail': tenant.billing_email,
            'settings': json.dumps(tenant.settings) if tenant.settings else None,
            'createdAt': tenant.created_at.isoformat(),
            'updatedAt': tenant.created_at.isoformat()
        }

    except ValueError as ve:
        logger.warning(f"Validation error: {ve}")
        # Validate error format for AppSync
        raise Exception(str(ve))
    except Exception as e:
        logger.error("Internal error", error=e)
        raise Exception(f"Internal error: {str(e)}")
