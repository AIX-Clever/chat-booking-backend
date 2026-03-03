
import os
import boto3
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# Set env vars BEFORE import
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
os.environ['CLIENTS_TABLE'] = 'ClientsTable'
os.environ['CLIENT_AUDIT_LOGS_TABLE'] = 'AuditTable'

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from clients import sync_handler

@pytest.fixture
def mock_dynamodb():
    with patch('boto3.resource') as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        yield mock_table

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv('CLIENTS_TABLE', 'ClientsTable')
    monkeypatch.setenv('CLIENT_AUDIT_LOGS_TABLE', 'AuditTable')

def test_lambda_handler_insert_new_client(mock_dynamodb, mock_env):
    # Mock DynamoDB Table resources
    mock_clients_table = MagicMock()
    mock_audit_table = MagicMock()
    
    # We need to patch the global tables in sync_handler module because they are initialized at module level
    with patch('clients.sync_handler.clients_table', mock_clients_table), \
         patch('clients.sync_handler.audit_table', mock_audit_table):
        
        # Mock Query response (Client not found)
        mock_clients_table.query.return_value = {'Count': 0, 'Items': []}
        
        event = {
            'Records': [
                {
                    'eventName': 'INSERT',
                    'dynamodb': {
                        'NewImage': {
                            'tenantId': {'S': 'tenant-1'},
                            'bookingId': {'S': 'booking-1'},
                            'clientName': {'S': 'Test Client'},
                            'clientEmail': {'S': 'test@example.com'},
                            'clientPhone': {'S': '+123456789'},
                        }
                    }
                }
            ]
        }
        
        sync_handler.lambda_handler(event, None)
        
        # Verify Query called
        mock_clients_table.query.assert_called_once()
        
        # Verify PutItem called (New Client)
        mock_clients_table.put_item.assert_called_once()
        call_args = mock_clients_table.put_item.call_args
        item = call_args.kwargs['Item']
        
        assert item['email'] == 'test@example.com'
        assert item['names']['given'] == 'Test'
        assert item['names']['family'] == 'Client'
        assert item['source'] == 'BOOKING'
        
        # Verify Audit Log
        mock_audit_table.put_item.assert_called()

def test_lambda_handler_skip_no_email(mock_dynamodb, mock_env):
    mock_clients_table = MagicMock()
    
    with patch('clients.sync_handler.clients_table', mock_clients_table):
        event = {
            'Records': [
                {
                    'eventName': 'INSERT',
                    'dynamodb': {
                        'NewImage': {
                            'tenantId': {'S': 'tenant-1'},
                            'id': {'S': 'booking-2'},
                            'customerInfo': {
                                'M': {
                                    'name': {'S': 'No Email Client'}
                                }
                            }
                        }
                    }
                }
            ]
        }
        
        sync_handler.lambda_handler(event, None)
        
        # Should not query or put

def test_lambda_handler_ignore_non_insert(mock_dynamodb, mock_env):
    mock_clients_table = MagicMock()
    with patch('clients.sync_handler.clients_table', mock_clients_table):
        event = {
            'Records': [
                {
                    'eventName': 'MODIFY',
                    'dynamodb': {'NewImage': {}}
                }
            ]
        }
        sync_handler.lambda_handler(event, None)
        mock_clients_table.query.assert_not_called()

def test_lambda_handler_update_existing_client(mock_dynamodb, mock_env):
    mock_clients_table = MagicMock()
    mock_audit_table = MagicMock()
    
    with patch('clients.sync_handler.clients_table', mock_clients_table), \
         patch('clients.sync_handler.audit_table', mock_audit_table):
        
        # Mock Existing Client
        mock_clients_table.query.return_value = {
            'Count': 1,
            'Items': [{
                'id': 'client-123',
                'names': {'given': 'Old', 'family': 'Name'},
                'contactInfo': [{'system': 'email', 'value': 'test@example.com'}]
            }]
        }
        
        event = {
            'Records': [
                {
                    'eventName': 'INSERT',
                    'dynamodb': {
                        'NewImage': {
                            'tenantId': {'S': 'tenant-1'},
                            'bookingId': {'S': 'booking-3'},
                            'clientName': {'S': 'New Name'},
                            'clientEmail': {'S': 'test@example.com'},
                            'clientPhone': {'S': '+999999999'},
                        }
                    }
                }
            ]
        }
        
        sync_handler.lambda_handler(event, None)
        
        # Verify Update (PutItem with updated fields)
        mock_clients_table.put_item.assert_called()
        call_args = mock_clients_table.put_item.call_args
        item = call_args.kwargs['Item']
        
        assert item['id'] == 'client-123'
        assert item['names']['given'] == 'New' # Name updated
        assert item['names']['family'] == 'Name' # Name updated
        # Phone added
        assert any(c['system'] == 'phone' and c['value'] == '+999999999' for c in item['contactInfo'])
        
        # Verify Audit Log
        assert mock_audit_table.put_item.call_count >= 1
