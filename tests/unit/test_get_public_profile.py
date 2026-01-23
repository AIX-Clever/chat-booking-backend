import json
import pytest
from unittest.mock import MagicMock, patch
from get_public_profile.handler import lambda_handler

@pytest.fixture
def mock_dynamodb():
    with patch('boto3.resource') as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        yield mock_table

@pytest.fixture
def sample_tenant():
    return {
        'tenantId': '123',
        'name': 'Test Center',
        'slug': 'test-center',
        'bio': 'Test Bio',
        'photoUrl': 'http://example.com/logo.png',
        'themeColor': '#000000',
        'settings': json.dumps({
            'profile': {
                'profession': 'Medical Center',
                'specializations': ['Cardiology'],
                'operatingHours': '9-5',
                'fullAddress': '123 Main St'
            }
        })
    }

def test_get_public_profile_success(mock_dynamodb, sample_tenant):
    # Setup mocks
    mock_dynamodb.query.return_value = {
        'Items': [sample_tenant],
        'Count': 1
    }
    
    mock_service_table = MagicMock()
    mock_provider_table = MagicMock()
    
    # Mocking tables
    def mock_table_side_effect(name):
        if name == 'ChatBooking-Services':
            return mock_service_table
        if name == 'ChatBooking-Providers':
            return mock_provider_table
        return mock_dynamodb

    with patch('boto3.resource') as resource_mock:
         resource_mock.return_value.Table.side_effect = mock_table_side_effect
         
         # Mock services scan response
         mock_service_table.scan.return_value = {'Items': []}
         
         # Mock providers scan response
         mock_provider_table.scan.return_value = {'Items': [{
             'providerId': 'p1',
             'name': 'Dr. Test',
             'services': ['s1']
         }]}

         event = {'slug': 'test-center'}
         response = lambda_handler(event, {})
         
         assert response['name'] == 'Test Center'
         assert response['profession'] == 'Medical Center'
         assert response['specializations'] == ['Cardiology']
         assert response['operatingHours'] == '9-5'
         assert response['fullAddress'] == '123 Main St'
         assert len(response['providers']) == 1
         assert response['providers'][0]['name'] == 'Dr. Test'
         assert response['providers'][0]['available'] is True

def test_get_public_profile_not_found(mock_dynamodb):
    mock_dynamodb.query.return_value = {'Items': [], 'Count': 0}
    
    event = {'slug': 'unknown'}
    response = lambda_handler(event, {})
    
    assert response is None

def test_get_public_profile_with_null_settings(mock_dynamodb):
    # Mocking tables
    mock_service_table = MagicMock()
    mock_provider_table = MagicMock()
    
    def mock_table_side_effect(name):
        return mock_service_table if name == 'ChatBooking-Services' else (mock_provider_table if name in ['ChatBooking-Providers'] else mock_dynamodb)
    
    with patch('boto3.resource') as resource_mock:
         resource_mock.return_value.Table.side_effect = mock_table_side_effect
         
         # Tenant with settings="null"
         mock_dynamodb.query.return_value = {
             'Items': [{
                 'tenantId': 't1', 
                 'name': 'Test', 
                 'slug': 'test',
                 'settings': 'null' # This simulates the string "null" from DB
             }], 
             'Count': 1
         }
         mock_service_table.scan.return_value = {'Items': []}
         mock_provider_table.scan.return_value = {'Items': []}

         event = {'slug': 'test'}
         response = lambda_handler(event, {})
         
         # Should not raise exception
         assert response['name'] == 'Test'
         assert response['profession'] == '' # Default
         assert response['specializations'] == [] # Default

def test_get_public_profile_with_null_profile_section(mock_dynamodb):
    mock_service_table = MagicMock()
    mock_provider_table = MagicMock()
    
    def mock_table_side_effect(name):
        return mock_service_table if name == 'ChatBooking-Services' else (mock_provider_table if name in ['ChatBooking-Providers'] else mock_dynamodb)
    
    with patch('boto3.resource') as resource_mock:
         resource_mock.return_value.Table.side_effect = mock_table_side_effect
         
         # Tenant with settings={"profile": null}
         mock_dynamodb.query.return_value = {
             'Items': [{
                 'tenantId': 't2', 
                 'name': 'Test 2', 
                 'slug': 'test2',
                 'settings': '{"profile": null}' 
             }], 
             'Count': 1
         }
         mock_service_table.scan.return_value = {'Items': []}
         mock_provider_table.scan.return_value = {'Items': []}

         event = {'slug': 'test2'}
         response = lambda_handler(event, {})
         
         assert response['name'] == 'Test 2'
         assert response['profession'] == ''
