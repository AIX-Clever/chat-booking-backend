
import pytest
import json
from unittest.mock import Mock, patch
from shared.domain.entities import Tenant, TenantId, TenantStatus, TenantPlan
from update_tenant.handler import lambda_handler

@pytest.fixture
def mock_tenant_repo():
    with patch('update_tenant.handler.DynamoDBTenantRepository') as mock:
        yield mock.return_value

def test_update_tenant_success(mock_tenant_repo):
    # Setup
    tenant_id = TenantId("tenant-123")
    existing_tenant = Tenant(
        tenant_id=tenant_id,
        name="Old Name",
        slug="old-name",
        owner_user_id="user-123",
        billing_email="old@test.com",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.LITE,
        settings={"theme": "dark"}
    )
    mock_tenant_repo.get_by_id.return_value = existing_tenant
    
    event = {
        'identity': {
            'claims': {
                'custom:tenantId': 'tenant-123'
            }
        },
        'arguments': {
            'input': {
                'name': 'New Name',
                'settings': json.dumps({'theme': 'light'})
            }
        }
    }
    
    # Execute
    result = lambda_handler(event, {})
    
    # Assert
    assert result['name'] == 'New Name'
    assert result['tenantId'] == 'tenant-123'
    
    # Check Repo
    mock_tenant_repo.save.assert_called_once()
    saved_tenant = mock_tenant_repo.save.call_args[0][0]
    assert saved_tenant.name == 'New Name'
    assert saved_tenant.settings['theme'] == 'light'

def test_update_tenant_unauthorized(mock_tenant_repo):
    event = {
        'identity': {
            'claims': {} # Missing tenantId
        }
    }
    
    with pytest.raises(ValueError, match="Unauthorized"):
        lambda_handler(event, {})
