import pytest
import os
from unittest.mock import patch, MagicMock
from register_tenant.handler import lambda_handler

# Set default region for all tests
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture(autouse=True)
def mock_boto_base():
    """Base mock for boto3 to prevent real AWS calls during collection/setup"""
    with patch("boto3.client", return_value=MagicMock()), patch(
        "boto3.resource", return_value=MagicMock()
    ):
        yield


@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_xxxxxx"}):
        yield


@pytest.fixture
def mock_cognito():
    with patch("register_tenant.handler.cognito") as mock:
        yield mock


@pytest.fixture
def mock_workflows_table():
    with patch("register_tenant.handler.workflows_table") as mock:
        yield mock


@pytest.fixture
def mock_repositories():
    with patch(
        "register_tenant.handler.DynamoDBTenantRepository"
    ) as mock_tenant_repo, patch(
        "register_tenant.handler.DynamoDBApiKeyRepository"
    ) as mock_api_key_repo:

        tenant_repo_instance = mock_tenant_repo.return_value
        api_key_repo_instance = mock_api_key_repo.return_value

        yield tenant_repo_instance, api_key_repo_instance


def test_register_tenant_success(
    mock_env, mock_cognito, mock_workflows_table, mock_repositories
):
    # Setup
    tenant_repo, api_key_repo = mock_repositories

    event = {
        "arguments": {
            "input": {
                "email": "test@example.com",
                "password": "Password123!",
                "companyName": "Test Corp",
            }
        }
    }

    # Execute
    result = lambda_handler(event, {})

    # Assert
    assert result["billingEmail"] == "test@example.com"
    assert result["name"] == "Test Corp"
    assert result["status"] == "PENDING_PAYMENT"

    # Check Cognito calls
    mock_cognito.admin_create_user.assert_called_once()
    mock_cognito.admin_set_user_password.assert_called_once()

    # Check DB saves
    tenant_repo.save.assert_called_once()
    api_key_repo.save.assert_called_once()


def test_register_tenant_missing_input(
    mock_env, mock_cognito, mock_workflows_table
):
    event = {}
    with pytest.raises(Exception):
        lambda_handler(event, {})
