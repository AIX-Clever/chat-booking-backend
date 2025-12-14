
import sys
import os

# Add layer to path
sys.path.append(os.path.join(os.getcwd(), 'layer/python'))

# MOCK boto3 to avoid ImportError
from unittest.mock import MagicMock
boto3 = MagicMock()
sys.modules['boto3'] = boto3
sys.modules['boto3.dynamodb'] = MagicMock()
sys.modules['boto3.dynamodb.conditions'] = MagicMock()
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.exceptions'] = MagicMock()

from shared.utils import extract_tenant_id

# Mock Event from AppSync (API Key Auth, simulate None values)
mock_event = {
    "request": {
        "headers": {
            "x-tenant-id": "demo-landing"
        }
    },
    "identity": None,
    "arguments": None,
    "info": {
        "selectionSetList": ["conversation", "response"],
        "parentTypeName": "Mutation",
        "fieldName": "startConversation"
    },
    "arguments": {
        "input": {
            "channel": "widget"
        }
    }
}

try:
    tenant_id = extract_tenant_id(mock_event)
    print(f"Extracted Tenant ID: {tenant_id}")
    if tenant_id == 'demo-landing':
        print("SUCCESS")
    else:
        print("FAILURE: Did not match demo-landing")
except Exception as e:
    print(f"EXCEPTION: {e}")
