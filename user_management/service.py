"""
User Management Service

Handles user invitation, role management, and removal using:
- AWS Cognito for authentication
- DynamoDB for role storage (flexible & auditable)
"""

import boto3
import secrets
import string
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime, timezone

from shared.infrastructure.notifications import EmailService
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.infrastructure.user_role_repository import DynamoDBUserRoleRepository
from shared.domain.entities import TenantId, UserRoleEntity, UserRole, UserStatus
from shared.utils import check_plan_limit

if TYPE_CHECKING:
    from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
    from shared.infrastructure.user_role_repository import DynamoDBUserRoleRepository

class UserManagementService:
    """Service for managing tenant users with Cognito + DynamoDB"""
    
    def __init__(
        self,
        tenant_repo: Optional['DynamoDBTenantRepository'] = None,
        user_role_repo: Optional['DynamoDBUserRoleRepository'] = None,
        email_service: Optional[EmailService] = None,
        cognito_client=None,
        user_pool_id: Optional[str] = None
    ):
        """Initialize service with repositories"""
        self.tenant_repo = tenant_repo or DynamoDBTenantRepository()
        self.user_role_repo = user_role_repo or DynamoDBUserRoleRepository()
        self.email_service = email_service or EmailService()
        self.cognito = cognito_client or boto3.client('cognito-idp')
        self.user_pool_id = user_pool_id or self._get_user_pool_id()
    
    def _get_user_pool_id(self) -> str:
        """Get user pool ID from environment"""
        import os
        pool_id = os.environ.get('USER_POOL_ID')
        if not pool_id:
            raise ValueError("USER_POOL_ID environment variable not set")
        return pool_id
    
    def invite_user(
        self,
        tenant_id: TenantId,
        email: str,
        name: Optional[str],
        role: str
    ) -> Dict[str, Any]:
        """
        Invite a new user to the tenant.
        
        Creates user in Cognito and stores role in DynamoDB.
        """
        # 1. Validate plan limits
        tenant = self.tenant_repo.get_by_id(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")
        
        # Count active users
        active_users = self.user_role_repo.count_active_users(tenant_id)
        
        # Check plan limit
        check_plan_limit(
            plan=tenant.plan.value,
            metric='max_users',
            current_usage=active_users
        )
        
        # 2. Create user in Cognito
        temp_password = self._generate_temp_password()
        
        user_attributes = [
            {'Name': 'email', 'Value': email},
            {'Name': 'email_verified', 'Value': 'true'},
            {'Name': 'custom:tenantId', 'Value': str(tenant_id)}
        ]
        
        if name:
            user_attributes.append({'Name': 'name', 'Value': name})
        
        try:
            response = self.cognito.admin_create_user(
                UserPoolId=self.user_pool_id,
                Username=email,
                UserAttributes=user_attributes,
                TemporaryPassword=temp_password,
                MessageAction='SUPPRESS',  # We'll send custom email later
                DesiredDeliveryMediums=['EMAIL']
            )
            
            user_sub = self._extract_user_sub(response['User'])
            
        except self.cognito.exceptions.UsernameExistsException:
            raise ValueError(f"User with email {email} already exists")
        
        # 3. Create role record in DynamoDB
        user_role = UserRoleEntity(
            user_id=user_sub or email,  # Use sub if available, fallback to email
            tenant_id=tenant_id,
            email=email,
            name=name,
            role=UserRole(role),
            status=UserStatus.PENDING_INVITATION,
            created_at=datetime.now(timezone.utc)
        )
        
        self.user_role_repo.create(user_role)
        
        # 4. Send invitation email
        self._send_invitation_email(email, temp_password, name or email)
        
        return user_role.to_dict()

    def _send_invitation_email(self, email: str, temp_password: str, name: str):
        """Send welcome email with temporary credentials"""
        try:
            # Login URL (could be from env)
            login_url = "https://admin.holalucia.cl"
            
            subject = "Bienvenido a Lucia - Tu Asistente de Reservas"
            
            body_html = f"""
            <html>
                <body>
                    <h2>Hola {name},</h2>
                    <p>Has sido invitado a administrar la cuenta de tu empresa en Lucia.</p>
                    <p>Tus credenciales temporales son:</p>
                    <ul>
                        <li><strong>Usuario:</strong> {email}</li>
                        <li><strong>Contraseña:</strong> {temp_password}</li>
                    </ul>
                    <p>Por favor inicia sesión y cambia tu contraseña inmediatamente:</p>
                    <p><a href="{login_url}">{login_url}</a></p>
                    <br>
                    <p>Saludos,<br>El equipo de Lucia</p>
                </body>
            </html>
            """
            
            body_text = f"""
            Hola {name},
            
            Has sido invitado a administrar la cuenta de tu empresa en Lucia.
            
            Tus credenciales temporales son:
            Usuario: {email}
            Contraseña: {temp_password}
            
            Inicia sesión aquí: {login_url}
            """
            
            # Send from verified domain
            import os
            sender = os.environ.get('FROM_EMAIL', 'no-reply@holalucia.cl')
            
            self.email_service.send_email(
                source=sender,
                to_addresses=[email],
                subject=subject,
                body_html=body_html,
                body_text=body_text
            )
        except Exception as e:
            # Log but don't fail the transaction
            print(f"Failed to send invitation email: {e}")
    
    def list_users(self, tenant_id: TenantId) -> List[Dict[str, Any]]:
        """
        List all users in a tenant.
        
        Returns combined data from Cognito + DynamoDB roles.
        """
        # Get all user roles from DynamoDB
        user_roles = self.user_role_repo.list_by_tenant(tenant_id)
        
        # Enrich with Cognito data (last login, etc)
        results = []
        for user_role in user_roles:
            user_data = user_role.to_dict()
            
            # Try to get additional info from Cognito
            try:
                cognito_user = self.cognito.admin_get_user(
                    UserPoolId=self.user_pool_id,
                    Username=user_role.user_id
                )
                
                # Add last login if available
                last_modified = cognito_user.get('UserLastModifiedDate')
                if last_modified:
                    user_data['lastLogin'] = last_modified.isoformat()
                
            except Exception as e:
                # User might be deleted from Cognito but still in DynamoDB
                print(f"Could not fetch Cognito data for {user_role.user_id}: {e}")
            
            results.append(user_data)
        
        return results
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific user by ID"""
        user_role = self.user_role_repo.get(user_id)
        
        if not user_role:
            return None
        
        return user_role.to_dict()
    
    def update_role(self, user_id: str, new_role: str) -> Dict[str, Any]:
        """
        Update a user's role.
        
        Only updates DynamoDB (not Cognito).
        """
        # Get existing user role
        user_role = self.user_role_repo.get(user_id)
        
        if not user_role:
            raise ValueError(f"User {user_id} not found")
        
        # Update role
        user_role.role = UserRole(new_role)
        
        # Save to DynamoDB
        updated = self.user_role_repo.update(user_role)
        
        return updated.to_dict()
    
    def remove_user(self, user_id: str) -> Dict[str, Any]:
        """
        Remove a user (soft delete).
        
        Disables in Cognito and marks as INACTIVE in DynamoDB.
        """
        # Get user role
        user_role = self.user_role_repo.get(user_id)
        
        if not user_role:
            raise ValueError(f"User {user_id} not found")
        
        # Disable in Cognito
        try:
            self.cognito.admin_disable_user(
                UserPoolId=self.user_pool_id,
                Username=user_id
            )
        except Exception as e:
            print(f"Could not disable Cognito user {user_id}: {e}")
            # Continue anyway - we'll mark as inactive in DynamoDB
        
        # Mark as inactive in DynamoDB
        user_role.status = UserStatus.INACTIVE
        updated = self.user_role_repo.update(user_role)
        
        return updated.to_dict()
    
    def reset_user_password(self, user_id: str) -> bool:
        """
        Reset a user's password via Cognito Admin flow.
        
        This triggers an email to the user with a code to reset their password.
        """
        try:
            self.cognito.admin_reset_user_password(
                UserPoolId=self.user_pool_id,
                Username=user_id
            )
            return True
        except self.cognito.exceptions.UserNotFoundException:
            raise ValueError(f"User {user_id} not found in Cognito")
        except Exception as e:
            print(f"Error resetting password for {user_id}: {e}")
            raise

    def _generate_temp_password(self) -> str:
        """Generate a secure temporary password"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(12))

    def _extract_user_sub(self, cognito_user: Dict) -> Optional[str]:
        """Extract user sub from Cognito response"""
        attributes = cognito_user.get('Attributes', [])
        for attr in attributes:
            if attr['Name'] == 'sub':
                return attr['Value']
        return None
