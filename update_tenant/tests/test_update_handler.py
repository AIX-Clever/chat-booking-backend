import pytest
import json
from unittest.mock import Mock, patch
from shared.domain.entities import Tenant, TenantId, TenantStatus, TenantPlan
from update_tenant.handler import lambda_handler


@pytest.fixture
def mock_tenant_repo():
    with patch("update_tenant.handler.DynamoDBTenantRepository") as mock:
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
        settings={"theme": "dark"},
    )
    mock_tenant_repo.get_by_id.return_value = existing_tenant

    event = {
        "identity": {"claims": {"custom:tenantId": "tenant-123"}},
        "arguments": {
            "input": {"name": "New Name", "settings": json.dumps({"theme": "light"})}
        },
    }

    # Execute
    result = lambda_handler(event, {})

    # Assert
    assert result["name"] == "New Name"
    assert result["tenantId"] == "tenant-123"

    # Check Repo
    mock_tenant_repo.save.assert_called_once()
    saved_tenant = mock_tenant_repo.save.call_args[0][0]
    assert saved_tenant.name == "New Name"
    assert saved_tenant.settings["theme"] == "light"



def test_update_tenant_unauthorized(mock_tenant_repo):
    event = {"identity": {"claims": {}}}  # Missing tenantId

    with pytest.raises(ValueError, match="Unauthorized"):
        lambda_handler(event, {})


def test_update_tenant_slug_success(mock_tenant_repo):
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
    )
    mock_tenant_repo.get_by_id.return_value = existing_tenant
    # Mock slug availability (None means available)
    mock_tenant_repo.get_by_slug.return_value = None

    event = {
        "identity": {"claims": {"custom:tenantId": "tenant-123"}},
        "arguments": {
            "input": {"slug": "new-slug"}
        },
    }

    # Execute
    result = lambda_handler(event, {})

    # Assert
    assert result["slug"] == "new-slug"
    mock_tenant_repo.get_by_slug.assert_called_with("new-slug")
    mock_tenant_repo.save.assert_called_once()


def test_update_tenant_slug_taken(mock_tenant_repo):
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
    )
    mock_tenant_repo.get_by_id.return_value = existing_tenant
    # Mock slug availability (Return object means taken)
    mock_tenant_repo.get_by_slug.return_value = Mock() 

    event = {
        "identity": {"claims": {"custom:tenantId": "tenant-123"}},
        "arguments": {
            "input": {"slug": "taken-slug"}
        },
    }

    # Execute & Assert
    with pytest.raises(ValueError, match="El link personalizado 'taken-slug' ya está en uso"):
        lambda_handler(event, {})

