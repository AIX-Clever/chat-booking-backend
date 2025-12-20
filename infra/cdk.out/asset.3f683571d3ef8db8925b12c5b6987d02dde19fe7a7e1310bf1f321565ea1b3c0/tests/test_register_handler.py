
import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from register_tenant.handler import lambda_handler

@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {'USER_POOL_ID': 'us-east-1_xxxxxx'}):
        yield

@pytest.fixture
def mock_cognito():
    with patch('register_tenant.handler.cognito') as mock:
        yield mock

@pytest.fixture
def mock_repositories():
    with patch('register_tenant.handler.DynamoDBTenantRepository') as mock_tenant_repo, \
         patch('register_tenant.handler.DynamoDBApiKeyRepository') as mock_api_key_repo:
        
        tenant_repo_instance = mock_tenant_repo.return_value
        api_key_repo_instance = mock_api_key_repo.return_value
        
        yield tenant_repo_instance, api_key_repo_instance

def test_register_tenant_success(mock_env, mock_cognito, mock_repositories):
    # Setup
    # mock_cognito is now the object 'cognito' in handler.py
    
    tenant_repo, api_key_repo = mock_repositories
    
    event = {
        'arguments': {
            'input': {
                'email': 'test@example.com',
                'password': 'Password123!',
                'companyName': 'Test Corp'
            }
        }
    }
    
    # Execute
    result = lambda_handler(event, {})
    
    # Assert
    assert result['billingEmail'] == 'test@example.com'
    assert result['name'] == 'Test Corp'
    assert result['status'] == 'ACTIVE'
    
    # Check Cognito calls
    mock_cognito.admin_create_user.assert_called_once()
    mock_cognito.admin_set_user_password.assert_called_once()
    
    # Check DB saves
    tenant_repo.save.assert_called_once()
    api_key_repo.save.assert_called_once()

def test_register_tenant_missing_input(mock_env):
    event = {}
    with pytest.raises(Exception):
        lambda_handler(event, {})
