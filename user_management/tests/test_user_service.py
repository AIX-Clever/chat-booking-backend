"""
Tests for User Management Service

Tests user invitation, listing, role updates, and removal with plan limits.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from shared.domain.entities import TenantId, UserRoleEntity, UserRole, UserStatus
from shared.domain.exceptions import PlanLimitExceeded
from user_management.service import UserManagementService


@pytest.fixture
def mock_tenant_repo():
    """Mock tenant repository."""
    repo = MagicMock()
    tenant = MagicMock()
    # Mock plan as an object with a .value attribute
    tenant.plan = MagicMock()
    tenant.plan.value = 'PRO'
    repo.get_by_id.return_value = tenant
    return repo


@pytest.fixture
def mock_cognito():
    """Mock Cognito client."""
    mock = MagicMock()
    # Create a mock exceptions object with a real exception class
    mock.exceptions = MagicMock()
    class UsernameExistsException(Exception): pass
    mock.exceptions.UsernameExistsException = UsernameExistsException
    return mock


@pytest.fixture
def mock_user_role_repo():
    """Mock user role repository."""
    return MagicMock()


@pytest.fixture
def user_service(mock_tenant_repo, mock_user_role_repo, mock_cognito):
    """Create UserManagementService with mocks."""
    return UserManagementService(
        tenant_repo=mock_tenant_repo,
        user_role_repo=mock_user_role_repo,
        cognito_client=mock_cognito,
        user_pool_id='test-pool-id'
    )


class TestInviteUser:
    """Tests for invite_user functionality."""
    
    def test_invite_user_success(self, user_service, mock_cognito, mock_tenant_repo, mock_user_role_repo):
        """Test successful user invitation."""
        # Setup
        tenant_id = TenantId('test-tenant')
        email = 'newuser@test.com'
        name = 'Test User'
        role = 'ADMIN'
        
        # Mock Cognito response
        mock_cognito.admin_create_user.return_value = {
            'User': {
                'Username': email,
                'UserCreateDate': datetime.now(),
                'Attributes': [{'Name': 'sub', 'Value': 'test-sub'}]
            }
        }
        
        # Mock repos
        mock_user_role_repo.count_active_users.return_value = 2
        
        # Execute
        result = user_service.invite_user(tenant_id, email, name, role)
        
        # Verify
        assert result['email'] == email
        assert result['role'] == role
        assert result['status'] == 'PENDING_INVITATION'
        mock_cognito.admin_create_user.assert_called_once()
        mock_user_role_repo.create.assert_called_once()
        
        # Check attributes passed to Cognito
        call_args = mock_cognito.admin_create_user.call_args
        attributes = call_args[1]['UserAttributes']
        assert any(attr['Name'] == 'custom:tenantId' and attr['Value'] == str(tenant_id) for attr in attributes)
        # Note: role is in DynamoDB, not Cognito custom:role currently
    
    def test_invite_user_exceeds_plan_limit(self, user_service, mock_user_role_repo):
        """Test that invitation fails when plan limit is reached."""
        # Setup PRO plan (max 5 users)
        tenant_id = TenantId('test-tenant')
        
        # Mock 5 active users already (at limit)
        mock_user_role_repo.count_active_users.return_value = 5
        
        # Execute & Verify
        with pytest.raises(PlanLimitExceeded) as exc_info:
            user_service.invite_user(tenant_id, 'new@test.com', None, 'USER')
        
        assert 'PRO' in str(exc_info.value)
        assert '5' in str(exc_info.value)
    
    def test_invite_user_lite_plan_limit(self, user_service, mock_tenant_repo, mock_user_role_repo):
        """Test LITE plan allows only 1 user."""
        # Change to LITE plan
        mock_tenant_repo.get_by_id.return_value.plan.value = 'LITE'
        tenant_id = TenantId('test-tenant')
        
        # Mock 1 active user (at LITE limit)
        mock_user_role_repo.count_active_users.return_value = 1
        
        # Execute & Verify
        with pytest.raises(PlanLimitExceeded):
            user_service.invite_user(tenant_id, 'second@test.com', None, 'USER')
    
    def test_invite_user_enterprise_unlimited(self, user_service, mock_tenant_repo, mock_cognito, mock_user_role_repo):
        """Test ENTERPRISE plan allows unlimited users."""
        # Change to ENTERPRISE plan
        mock_tenant_repo.get_by_id.return_value.plan.value = 'ENTERPRISE'
        tenant_id = TenantId('test-tenant')
        
        # Mock Cognito response
        mock_cognito.admin_create_user.return_value = {
            'User': {
                'Username': 'new@test.com',
                'UserCreateDate': datetime.now(),
                'Attributes': []
            }
        }
        
        # Mock 100 active users (way more than other plans)
        mock_user_role_repo.count_active_users.return_value = 100
        
        # Should still succeed
        result = user_service.invite_user(tenant_id, 'new@test.com', None, 'USER')
        assert result['userId'] == 'new@test.com'


class TestListUsers:
    """Tests for list_users functionality."""
    
    def test_list_users_success(self, user_service, mock_cognito, mock_user_role_repo):
        """Test listing users for a tenant."""
        tenant_id = TenantId('test-tenant')
        
        # Mock roles in DynamoDB
        mock_user_role_repo.list_by_tenant.return_value = [
            UserRoleEntity(
                user_id='user1-id',
                tenant_id=tenant_id,
                email='user1@test.com',
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
                created_at=datetime.now()
            )
        ]
        
        # Mock Cognito response for enrichment
        mock_cognito.admin_get_user.return_value = {
            'UserLastModifiedDate': datetime.now()
        }
        
        # Execute
        users = user_service.list_users(tenant_id)
        
        # Verify
        assert len(users) == 1
        assert users[0]['email'] == 'user1@test.com'
        assert users[0]['role'] == 'ADMIN'
        assert users[0]['status'] == 'ACTIVE'


class TestUpdateRole:
    """Tests for update_role functionality."""
    
    def test_update_role_success(self, user_service, mock_user_role_repo):
        """Test successful role update."""
        user_id = 'user-id'
        new_role = 'ADMIN'
        
        # Mock repo
        mock_user_role_repo.get.return_value = UserRoleEntity(
            user_id=user_id,
            tenant_id=TenantId('tenant-1'),
            email='u@t.com',
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
            created_at=datetime.now()
        )
        mock_user_role_repo.update.return_value = UserRoleEntity(
            user_id=user_id,
            tenant_id=TenantId('tenant-1'),
            email='u@t.com',
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            created_at=datetime.now()
        )
        
        # Execute
        result = user_service.update_role(user_id, new_role)
        
        # Verify
        assert result['role'] == 'ADMIN'
        mock_user_role_repo.update.assert_called_once()


class TestRemoveUser:
    """Tests for remove_user functionality."""
    
    def test_remove_user_success(self, user_service, mock_cognito, mock_user_role_repo):
        """Test successful user removal (disable)."""
        user_id = 'user-id'
        
        # Mock repo
        user_role = UserRoleEntity(
            user_id=user_id,
            tenant_id=TenantId('tenant-1'),
            email='u@t.com',
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
            created_at=datetime.now()
        )
        mock_user_role_repo.get.return_value = user_role
        mock_user_role_repo.update.return_value = user_role # Will be mutated
        
        # Execute
        result = user_service.remove_user(user_id)
        
        # Verify
        mock_cognito.admin_disable_user.assert_called_once()
        assert result['status'] == 'INACTIVE'
        mock_user_role_repo.update.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
