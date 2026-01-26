import pytest
from unittest.mock import MagicMock
import boto3
from shared.infrastructure.google_auth_service import GoogleAuthService
from shared.infrastructure.dynamodb_repositories import DynamoDBProviderIntegrationRepository
from shared.domain.entities import TenantId

from urllib.parse import urlparse, parse_qs

def test_google_auth_url_generation():
    service = GoogleAuthService("client_id", "client_secret", "http://localhost/callback")
    url = service.get_authorization_url("state_123")
    
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    
    assert params['client_id'][0] == 'client_id'
    assert params['redirect_uri'][0] == 'http://localhost/callback'
    assert params['state'][0] == 'state_123'
    assert params['access_type'][0] == 'offline'

def test_repo_save_google_creds(mocker):
    # Mock DynamoDB
    mock_boto = mocker.patch('boto3.resource')
    mock_table = MagicMock()
    mock_boto.return_value.Table.return_value = mock_table
    
    repo = DynamoDBProviderIntegrationRepository("TestTable")
    repo.table = mock_table 
    
    tenant_id = TenantId("tenant-1")
    provider_id = "prov-1"
    creds = {"access_token": "abc", "refresh_token": "def"}
    
    repo.save_google_creds(tenant_id, provider_id, creds)
    
    # Assert called with correct params
    mock_table.update_item.assert_called_once()
    call_args = mock_table.update_item.call_args[1]
    assert call_args['Key'] == {'tenantId': 'tenant-1', 'providerId': 'prov-1'}
    assert call_args['UpdateExpression'] == "SET googleIntegration = :c"
    assert call_args['ExpressionAttributeValues'] == {':c': creds}
