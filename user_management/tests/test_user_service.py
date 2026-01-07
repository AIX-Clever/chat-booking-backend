"""
Tests for User Management Service

Tests user invitation, listing, role updates, and removal with plan limits.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from shared.domain.entities import TenantId
from shared.plan_limits import PlanLimitExceeded
from user_management.service import UserManagementService


@pytest.fixture
def mock_tenant_repo():
    """Mock tenant repository."""
    repo = Mock()
    tenant = Mock()
    tenant.plan = 'PRO'
    repo.get.return_value = tenant
    return repo


@pytest.fixture
def mock_cognito():
    """Mock Cognito client."""
    return Mock()


@pytest.fixture
def user_service(mock_tenant_repo, mock_cognito):
    """Create UserManagementService with mocks."""
    return UserManagementService(
        tenant_repo=mock_tenant_repo,
        cognito_client=mock_cognito,
        user_pool_id='test-pool-id'
    )


class TestInviteUser:
    """Tests for invite_user functionality."""
    
    def test_invite_user_success(self, user_service, mock_cognito, mock_tenant_repo):
        """Test successful user invitation."""
        # Setup
        tenant_id = TenantId('test-tenant')
        email = 'newuser@test.com'
        role = 'ADMIN'
        
        # Mock Cognito response
        mock_cognito.admin_create_user.return_value = {
            'User': {
                'Username': email,
                'UserCreateDate': datetime.now(),
                'Attributes': []
            }
        }
        
        # Mock list_users to return 2 current users (PRO allows 5)
        user_service.list_users = Mock(return_value=[{'status': 'ACTIVE'}, {'status': 'ACTIVE'}])
        
        # Execute
        result = user_service.invite_user(tenant_id, email, 'Test User', role)
        
        # Verify
        assert result['userId'] == email
        assert result['role'] == role
        assert result['status'] == 'PENDING_INVITATION'
        mock_cognito.admin_create_user.assert_called_once()
        
        # Check custom attributes
        call_args = mock_cognito.admin_create_user.call_args
        attributes = call_args[1]['UserAttributes']
        assert any(attr['Name'] == 'custom:tenantId' and attr['Value'] == str(tenant_id) for attr in attributes)
        assert any(attr['Name'] == 'custom:role' and attr['Value'] == role for attr in attributes)
    
    def test_invite_user_exceeds_plan_limit(self, user_service, mock_tenant_repo):
        """Test that invitation fails when plan limit is reached."""
        # Setup PRO plan (max 5 users)
        tenant_id = TenantId('test-tenant')
        
        # Mock 5 active users already (at limit)
        user_service.list_users = Mock(return_value=[
            {'status': 'ACTIVE'} for _ in range(5)
        ])
        
        # Execute & Verify
        with pytest.raises(PlanLimitExceeded) as exc_info:
            user_service.invite_user(tenant_id, 'new@test.com', None, 'USER')
        
        assert 'PRO' in str(exc_info.value)
        assert '5' in str(exc_info.value)
    
    def test_invite_user_lite_plan_limit(self, user_service, mock_tenant_repo):
        """Test LITE plan allows only 1 user."""
        # Change to LITE plan
        tenant = mock_tenant_repo.get.return_value
        tenant.plan = 'LITE'
        
        tenant_id = TenantId('test-tenant')
        
        # Mock 1 active user (at LITE limit)
        user_service.list_users = Mock(return_value=[{'status': 'ACTIVE'}])
        
        # Execute & Verify
        with pytest.raises(PlanLimitExceeded):
            user_service.invite_user(tenant_id, 'second@test.com', None, 'USER')
    
    def test_invite_user_enterprise_unlimited(self, user_service, mock_tenant_repo, mock_cognito):
        """Test ENTERPRISE plan allows unlimited users."""
        # Change to ENTERPRISE plan
        tenant = mock_tenant_repo.get.return_value
        tenant.plan = 'ENTERPRISE'
        
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
        user_service.list_users = Mock(return_value=[{'status': 'ACTIVE'} for _ in range(100)])
        
        # Should still succeed
        result = user_service.invite_user(tenant_id, 'new@test.com', None, 'USER')
        assert result['userId'] == 'new@test.com'


class TestListUsers:
    """Tests for list_users functionality."""
    
    def test_list_users_success(self, user_service, mock_cognito):
        """Test listing users for a tenant."""
        tenant_id = TenantId('test-tenant')
        
        # Mock Cognito response
        mock_cognito.list_users.return_value = {
            'Users': [
                {
                    'Username': 'user1@test.com',
                    'Enabled': True,
                    'UserStatus': 'CONFIRMED',
                    'UserCreateDate': datetime.now(),
                    'Attributes': [
                        {'Name': 'email', 'Value': 'user1@test.com'},
                        {'Name': 'custom:tenantId', 'Value': str(tenant_id)},
                        {'Name': 'custom:role', 'Value': 'ADMIN'}
                    ]
                }
            ]
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
    
    def test_update_role_success(self, user_service, mock_cognito):
        """Test successful role update."""
        user_id = 'user@test.com'
        new_role = 'ADMIN'
        
        # Mock get_user response
        user_service.get_user = Mock(return_value={'userId': user_id, 'role': 'USER'})
        
        # Execute
        result = user_service.update_role(user_id, new_role)
        
        # Verify
        mock_cognito.admin_update_user_attributes.assert_called_once()
        call_args = mock_cognito.admin_update_user_attributes.call_args
        assert call_args[1]['UserAttributes'][0]['Value'] == new_role


class TestRemoveUser:
    """Tests for remove_user functionality."""
    
    def test_remove_user_success(self, user_service, mock_cognito):
        """Test successful user removal (disable)."""
        user_id = 'user@test.com'
        
        # Mock get_user response
        user_service.get_user = Mock(return_value={'userId': user_id, 'status': 'ACTIVE'})
        
        # Execute
        result = user_service.remove_user(user_id)
        
        # Verify
        mock_cognito.admin_disable_user.assert_called_once_with(
            UserPoolId='test-pool-id',
            Username=user_id
        )
        assert result['status'] == 'INACTIVE'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
