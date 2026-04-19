import os
import sys
import json
from datetime import datetime

# Add layer path
sys.path.append(os.path.join(os.getcwd(), 'layer/python'))

try:
    from metrics.handler import lambda_handler
    from shared.metrics import MetricsService
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

# Mock event for getDashboardMetrics
event = {
    "info": {
        "fieldName": "getDashboardMetrics"
    },
    "identity": {
        "claims": {
            "custom:tenantId": "tenant-123"
        }
    }
}

print("--- Testing getDashboardMetrics ---")
try:
    # Inject mock data if needed (optional, as we are testing the handler logic)
    # Ideally we should mock boto3 too, but for now let's see if it runs
    # We will likely need to mock boto3 in the local environment if no AWS creds,
    # BUT the user has AWS creds (expired, but maybe refreshed?).
    # Actually, better to mock boto3 resource to avoid network calls
    
    import boto3
    from unittest.mock import MagicMock, patch
    
    with patch('boto3.resource') as mock_dynamodb:
        # Mock Table
        mock_table = MagicMock()
        mock_dynamodb.return_value.Table.return_value = mock_table
        
        # Mock Query Response
        mock_table.query.return_value = {
            'Items': [
                {'SK': f'MONTH#{datetime.now().strftime("%Y-%m")}', 'bookings': 10, 'messages': 50, 'revenue': 1000},
                {'SK': f'DAY#{datetime.now().strftime("%Y-%m-%d")}', 'bookings': 2, 'messages': 10},
                {'SK': f'SVC#svc_1#{datetime.now().strftime("%Y-%m")}', 'name': 'Service A', 'bookings': 5},
                {'SK': f'PROV#pro_1#{datetime.now().strftime("%Y-%m")}', 'name': 'Provider B', 'bookings': 6},
                {'SK': f'STATUS#CONFIRMED#{datetime.now().strftime("%Y-%m")}', 'count': 8},
                {'SK': f'STATUS#CANCELLED#{datetime.now().strftime("%Y-%m")}', 'count': 2},
            ]
        }
        
        result = lambda_handler(event, {})
        print(json.dumps(result, indent=2))
        
        # Verify structure
        assert 'summary' in result
        assert result['summary']['bookings'] == 10
        assert result['summary']['revenue'] == 1000
        assert len(result['topServices']) == 1
        assert len(result['bookingStatus']) == 4
        print("✅ Dashboard structure verified!")

except Exception as e:
    print(f"❌ Error: {e}")
