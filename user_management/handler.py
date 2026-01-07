"""
Lambda handler for user management operations.

Handles GraphQL queries and mutations for tenant user management.
"""

import json
import logging
from typing import Any, Dict
from shared.domain.entities import TenantId
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.plan_limits import PlanLimitExceeded
from user_management.service import UserManagementService

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize repositories
tenant_repo = DynamoDBTenantRepository()

# Initialize service
user_service = UserManagementService(tenant_repo=tenant_repo)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for user management operations.
    
    Routes to appropriate handler based on field name.
    """
    try:
        logger.info("User Management Event", extra={"event": event})
        
        # Extract tenant ID from identity claims
        identity = event.get('identity', {})
        claims = identity.get('claims', {})
        tenant_id = TenantId(claims.get('custom:tenantId'))
        
        if not tenant_id:
            return error_response("Unauthorized: No tenant ID in claims", 401)
        
        # Get field name to determine operation
        field_name = event.get('info', {}).get('fieldName')
        arguments = event.get('arguments', {})
        
        logger.info(f"Field: {field_name}, TenantId: {tenant_id}")
        
        # Route to appropriate handler
        if field_name == 'listTenantUsers':
            return handle_list_users(tenant_id)
        
        elif field_name == 'getTenantUser':
            user_id = arguments.get('userId')
            return handle_get_user(tenant_id, user_id)
        
        elif field_name == 'inviteUser':
            input_data = arguments.get('input', {})
            return handle_invite_user(tenant_id, input_data, claims)
        
        elif field_name == 'updateUserRole':
            input_data = arguments.get('input', {})
            return handle_update_role(tenant_id, input_data, claims)
        
        elif field_name == 'removeUser':
            user_id = arguments.get('userId')
            return handle_remove_user(tenant_id, user_id, claims)
        
        else:
            return error_response(f"Unknown field: {field_name}", 400)
    
    except Exception as e:
        logger.error(f"Error in user management handler: {str(e)}", exc_info=True)
        return error_response(str(e), 500)


def handle_list_users(tenant_id: TenantId) -> list:
    """
    List all users for a tenant.
    
    Returns raw list for AppSync.
    """
    try:
        users = user_service.list_users(tenant_id)
        logger.info(f"Listed {len(users)} users for tenant {tenant_id}")
        return users
    
    except Exception as e:
        logger.error(f"Error listing users: {str(e)}", exc_info=True)
        raise


def handle_get_user(tenant_id: TenantId, user_id: str) -> Dict:
    """Get a specific user."""
    try:
        user = user_service.get_user(user_id)
        
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        # Verify user belongs to this tenant
        if user.get('tenantId') != str(tenant_id):
            raise ValueError("User does not belong to this tenant")
        
        return user
    
    except Exception as e:
        logger.error(f"Error getting user: {str(e)}", exc_info=True)
        raise


def handle_invite_user(tenant_id: TenantId, input_data: Dict, claims: Dict) -> Dict:
    """
    Invite a new user to the tenant.
    
    Only OWNER role can invite users.
    """
    try:
        # Check if caller has OWNER role
        caller_role = claims.get('custom:role', 'USER')
        if caller_role != 'OWNER':
            raise ValueError("Only OWNER can invite users")
        
        email = input_data.get('email')
        name = input_data.get('name')
        role = input_data.get('role', 'USER')
        
        if not email:
            raise ValueError("Email is required")
        
        user = user_service.invite_user(
            tenant_id=tenant_id,
            email=email,
            name=name,
            role=role
        )
        
        logger.info(f"Invited user {email} with role {role} to tenant {tenant_id}")
        return user
    
    except PlanLimitExceeded as e:
        logger.warning(f"Plan limit exceeded: {str(e)}")
        raise ValueError(f"Plan limit exceeded: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error inviting user: {str(e)}", exc_info=True)
        raise


def handle_update_role(tenant_id: TenantId, input_data: Dict, claims: Dict) -> Dict:
    """
    Update a user's role.
    
    Only OWNER can change roles.
    """
    try:
        # Check if caller has OWNER role
        caller_role = claims.get('custom:role', 'USER')
        if caller_role != 'OWNER':
            raise ValueError("Only OWNER can change user roles")
        
        user_id = input_data.get('userId')
        new_role = input_data.get('role')
        
        if not user_id or not new_role:
            raise ValueError("userId and role are required")
        
        # Get user to verify they belong to this tenant
        user = user_service.get_user(user_id)
        if not user or user.get('tenantId') != str(tenant_id):
            raise ValueError("User not found or does not belong to this tenant")
        
        updated_user = user_service.update_role(user_id, new_role)
        
        logger.info(f"Updated user {user_id} role to {new_role}")
        return updated_user
    
    except Exception as e:
        logger.error(f"Error updating role: {str(e)}", exc_info=True)
        raise


def handle_remove_user(tenant_id: TenantId, user_id: str, claims: Dict) -> Dict:
    """
    Remove a user (disable their account).
    
    Only OWNER can remove users.
    """
    try:
        # Check if caller has OWNER role
        caller_role = claims.get('custom:role', 'USER')
        if caller_role != 'OWNER':
            raise ValueError("Only OWNER can remove users")
        
        # Get user to verify they belong to this tenant
        user = user_service.get_user(user_id)
        if not user or user.get('tenantId') != str(tenant_id):
            raise ValueError("User not found or does not belong to this tenant")
        
        # Prevent removing yourself
        caller_user_id = claims.get('sub') or claims.get('cognito:username')
        if user_id == caller_user_id:
            raise ValueError("Cannot remove yourself")
        
        removed_user = user_service.remove_user(user_id)
        
        logger.info(f"Removed user {user_id} from tenant {tenant_id}")
        return removed_user
    
    except Exception as e:
        logger.error(f"Error removing user: {str(e)}", exc_info=True)
        raise


def error_response(message: str, status_code: int = 400) -> Dict:
    """Create error response for AppSync."""
    return {
        "errorMessage": message,
        "errorType": "HandlerError"
    }
