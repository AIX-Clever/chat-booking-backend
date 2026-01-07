"""
User Management Service for multi-tenant user administration.

Handles user invitations, role management, and Cognito integration.
"""

import os
import boto3
from datetime import datetime
from typing import List, Dict, Optional
from shared.domain.entities import TenantId
from shared.domain.repositories import ITenantRepository
from shared.plan_limits import check_plan_limit, PlanLimitExceeded


class UserManagementService:
    """Service for managing tenant users via AWS Cognito."""
    
    def __init__(
        self,
        tenant_repo: ITenantRepository,
        cognito_client=None,
        user_pool_id: Optional[str] = None
    ):
        self._tenant_repo = tenant_repo
        self._cognito = cognito_client or boto3.client('cognito-idp')
        self._user_pool_id = user_pool_id or os.environ.get('USER_POOL_ID')
        
        if not self._user_pool_id:
            raise ValueError("USER_POOL_ID environment variable is required")
    
    def invite_user(
        self,
        tenant_id: TenantId,
        email: str,
        name: Optional[str],
        role: str
    ) -> Dict:
        """
        Invite a new user to the tenant with Cognito temporary password.
        
        Args:
            tenant_id: Tenant ID
            email: User email
            name: User display name (optional)
            role: User role (OWNER, ADMIN, USER)
        
        Returns:
            Dictionary with user information
        
        Raises:
            PlanLimitExceeded: If tenant has reached user limit for their plan
        """
        # 1. Get tenant to check plan
        tenant = self._tenant_repo.get(tenant_id)
        
        # 2. Count current users for this tenant
        current_users = self._count_tenant_users(tenant_id)
        
        # 3. Check plan limits
        is_within_limit, max_allowed = check_plan_limit(
            tenant.plan,
            "max_users",
            current_users
        )
        
        if not is_within_limit:
            raise PlanLimitExceeded(
                f"Plan {tenant.plan} allows max {max_allowed} users. Currently have {current_users}.",
                plan=tenant.plan,
                limit_key="max_users",
                current=current_users,
                max_allowed=max_allowed
            )
        
        # 4. Create Cognito user with custom attributes
        user_attributes = [
            {'Name': 'email', 'Value': email},
            {'Name': 'email_verified', 'Value': 'true'},
            {'Name': 'custom:tenantId', 'Value': str(tenant_id)},
            {'Name': 'custom:role', 'Value': role},
        ]
        
        if name:
            user_attributes.append({'Name': 'name', 'Value': name})
        
        try:
            response = self._cognito.admin_create_user(
                UserPoolId=self._user_pool_id,
                Username=email,
                UserAttributes=user_attributes,
                DesiredDeliveryMediums=['EMAIL'],  # Send email with temp password
                MessageAction='SUPPRESS' if os.environ.get('SUPPRESS_INVITE_EMAIL') else 'RESEND'
            )
            
            user = response['User']
            
            return {
                "userId": user['Username'],
                "tenantId": str(tenant_id),
                "email": email,
                "name": name,
                "role": role,
                "status": "PENDING_INVITATION",
                "createdAt": user['UserCreateDate'].isoformat(),
                "lastLogin": None
            }
            
        except self._cognito.exceptions.UsernameExistsException:
            # User already exists in this user pool
            raise ValueError(f"User with email {email} already exists")
    
    def list_users(self, tenant_id: TenantId) -> List[Dict]:
        """
        List all users for a tenant from Cognito.
        
        Args:
            tenant_id: Tenant ID
        
        Returns:
            List of user dictionaries
        """
        users = []
        pagination_token = None
        
        # Query Cognito with filter for custom:tenantId
        filter_str = f'custom:tenantId = "{str(tenant_id)}"'
        
        while True:
            kwargs = {
                'UserPoolId': self._user_pool_id,
                'Filter': filter_str,
                'Limit': 60  # Max per page
            }
            
            if pagination_token:
                kwargs['PaginationToken'] = pagination_token
            
            response = self._cognito.list_users(**kwargs)
            
            for user in response.get('Users', []):
                users.append(self._cognito_user_to_dict(user))
            
            pagination_token = response.get('PaginationToken')
            if not pagination_token:
                break
        
        return users
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """
        Get a specific user by ID from Cognito.
        
        Args:
            user_id: Cognito username (usually email)
        
        Returns:
            User dictionary or None if not found
        """
        try:
            response = self._cognito.admin_get_user(
                UserPoolId=self._user_pool_id,
                Username=user_id
            )
            
            return self._cognito_user_to_dict(response)
            
        except self._cognito.exceptions.UserNotFoundException:
            return None
    
    def update_role(self, user_id: str, new_role: str) -> Dict:
        """
        Update a user's role.
        
        Args:
            user_id: Cognito username
            new_role: New role value (OWNER, ADMIN, USER)
        
        Returns:
            Updated user dictionary
        """
        # Update custom:role attribute
        self._cognito.admin_update_user_attributes(
            UserPoolId=self._user_pool_id,
            Username=user_id,
            UserAttributes=[
                {'Name': 'custom:role', 'Value': new_role}
            ]
        )
        
        # Return updated user
        return self.get_user(user_id)
    
    def remove_user(self, user_id: str) -> Dict:
        """
        Remove a user by disabling their account.
        
        Args:
            user_id: Cognito username
        
        Returns:
            Removed user dictionary
        """
        # Get user info before disabling
        user = self.get_user(user_id)
        
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        # Disable the user (soft delete)
        self._cognito.admin_disable_user(
            UserPoolId=self._user_pool_id,
            Username=user_id
        )
        
        user['status'] = 'INACTIVE'
        return user
    
    def _count_tenant_users(self, tenant_id: TenantId) -> int:
        """Count active users for a tenant."""
        users = self.list_users(tenant_id)
        # Count only active users (not disabled)
        return sum(1 for u in users if u.get('status') != 'INACTIVE')
    
    def _cognito_user_to_dict(self, cognito_user: Dict) -> Dict:
        """Convert Cognito user object to our TenantUser format."""
        attributes = {
            attr['Name']: attr['Value']
            for attr in cognito_user.get('Attributes', [])
        }
        
        # Determine status
        status = 'ACTIVE'
        if not cognito_user.get('Enabled', True):
            status = 'INACTIVE'
        elif cognito_user.get('UserStatus') == 'FORCE_CHANGE_PASSWORD':
            status = 'PENDING_INVITATION'
        
        return {
            "userId": cognito_user.get('Username'),
            "tenantId": attributes.get('custom:tenantId'),
            "email": attributes.get('email'),
            "name": attributes.get('name'),
            "role": attributes.get('custom:role', 'USER'),
            "status": status,
            "createdAt": cognito_user.get('UserCreateDate', datetime.now()).isoformat(),
            "lastLogin": cognito_user.get('UserLastModifiedDate', datetime.now()).isoformat()
        }
