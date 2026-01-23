import sys
import os
import json
from unittest.mock import MagicMock, patch

# Add lambda directory to path
sys.path.append(os.path.abspath("get_public_profile"))

from handler import lambda_handler

# Mock environment variables
os.environ['TENANTS_TABLE'] = 'ChatBooking-Tenants'
os.environ['SERVICES_TABLE'] = 'ChatBooking-Services'
os.environ['PROVIDERS_TABLE'] = 'ChatBooking-Providers'

# Mock DynamoDB
mock_dynamodb = MagicMock()
mock_tenant_table = MagicMock()
mock_service_table = MagicMock()
mock_provider_table = MagicMock()

def mock_table(name):
    if name == 'ChatBooking-Tenants': return mock_tenant_table
    if name == 'ChatBooking-Services': return mock_service_table
    if name == 'ChatBooking-Providers': return mock_provider_table
    return MagicMock()

with patch('boto3.resource') as mock_resource:
    mock_resource.return_value.Table.side_effect = mock_table
    
    # Mock Tenant Response (clinica-davila)
    # Based on the user's error, the slug is likely "clinica-davila"
    mock_tenant_table.query.return_value = {
        'Items': [{
            'tenantId': 'test-tenant-id',
            'name': 'Clinica Davila',
            'slug': 'clinica-davila',
            'settings': json.dumps("null") # Simulate "null" string from DB
        }],
        'Count': 1
    }

    # Mock Services
    mock_service_table.scan.return_value = {'Items': []}

    # Mock Providers - mimicking the structure seen in the CLI scan
    # Important: The CLI scan showed providers active but map might fail if fields missing
    mock_provider_table.scan.return_value = {
        'Items': [
            {
                'providerId': 'p1',
                'name': 'Dr. Test',
                'active': True,
                # Missing timezone?
                # Missing services?
            }
        ]
    }

    # Execute
    event = {'slug': 'clinica-davila'}
    try:
        response = lambda_handler(event, {})
        print(json.dumps(response, indent=2))
    except Exception as e:
        print(f"Error: {e}")
