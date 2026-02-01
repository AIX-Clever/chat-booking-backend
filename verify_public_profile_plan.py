
import sys
import os
from unittest.mock import MagicMock, patch

# Mock boto3 before import
with patch('boto3.resource') as mock_resource:
    mock_dynamo = MagicMock()
    mock_resource.return_value = mock_dynamo
    
    mock_table = MagicMock()
    mock_dynamo.Table.return_value = mock_table
    
    # Mock Query Response
    mock_table.query.return_value = {
        'Items': [{
            'tenantId': 'tenant-123',
            'slug': 'test-slug',
            'name': 'Test Tenant',
            'plan': 'LITE',
            'active': True
        }]
    }
    
    # Mock Scan Response (Services/Providers)
    mock_table.scan.return_value = {'Items': []}

    # Import handler
    from get_public_profile.handler import lambda_handler

    event = {'slug': 'test-slug'}
    response = lambda_handler(event, {})
    
    print(f"Plan found: {response.get('tenantPlan')}")
    
    if response.get('tenantPlan') == 'LITE':
        print("SUCCESS: tenantPlan is present and correct.")
        sys.exit(0)
    else:
        print("FAILURE: tenantPlan missing or incorrect.")
        sys.exit(1)
