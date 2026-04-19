
import pytest
import os
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from shared.domain.entities import Tenant, TenantId, TenantStatus, TenantPlan

# Set default region
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

from get_tenant.handler import lambda_handler

@pytest.fixture
def mock_tenant_repo():
    with patch("get_tenant.handler.DynamoDBTenantRepository") as mock:
        yield mock

@pytest.fixture
def mock_extract_event():
    with patch("get_tenant.handler.extract_appsync_event") as mock:
        yield mock

def test_get_tenant_success_includes_owner_user_id(mock_tenant_repo, mock_extract_event):
    # Setup
    tenant_id = "tenant-123"
    owner_id = "user-owner-001"
    
    # Mock extract_appsync_event to return our tenant_id
    # field, tenant_id_str, input_data
    mock_extract_event.return_value = ("tenantId", tenant_id, {})
    
    # Mock Repo returning a valid Tenant
    repo_instance = mock_tenant_repo.return_value
    expected_tenant = Tenant(
        tenant_id=TenantId(tenant_id),
        name="Test Company",
        slug="test-company",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.PRO,
        owner_user_id=owner_id,
        billing_email="test@example.com",
        created_at=datetime.now(timezone.utc)
    )
    repo_instance.get_by_id.return_value = expected_tenant

    event = {} # Mocked via extractor

    # Execute
    response = lambda_handler(event, {})

    # Assert
    assert response["tenantId"] == tenant_id
    assert response["ownerUserId"] == owner_id
    assert response["name"] == "Test Company"
    assert response["plan"] == "PRO"
