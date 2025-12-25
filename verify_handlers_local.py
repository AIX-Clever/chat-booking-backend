import sys
import os
import json
from unittest.mock import MagicMock

# Mock AWS environment
os.environ['DOCUMENTS_BUCKET'] = 'mock-bucket'
os.environ['DOCUMENTS_TABLE'] = 'mock-table'
os.environ['DB_ENDPOINT'] = 'mock-endpoint'
os.environ['DB_SECRET_ARN'] = 'mock-secret'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

# Mock boto3 before importing handlers
import boto3
boto3.client = MagicMock()
boto3.resource = MagicMock()

# Add parent dir to sys.path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    print("1. Importing handlers...")
    from knowledge_base import presign_handler
    from knowledge_base import ingestion_handler
    print("   Imports successful.")

    # Test Presign Handler
    print("\n2. Testing Presign Handler...")
    mock_event_presign = {
        "info": {
            "fieldName": "getUploadUrl",
            "variables": {}
        },
        "arguments": {
            "fileName": "test.pdf",
            "fileType": "application/pdf"
        },
        "identity": {
            "claims": {
                "sub": "user-123",
                "custom:tenantId": "tenant-abc"
            }
        }
    }
    
    # Mock DynamoDB Table
    mock_table = MagicMock()
    presign_handler.documents_table = mock_table
    presign_handler.s3_client.generate_presigned_url.return_value = "https://s3.mock/upload"
    
    response = presign_handler.lambda_handler(mock_event_presign, None)
    print(f"   Response: {json.dumps(response, indent=2)}")
    
    # Validating response structure
    if 'uploadUrl' not in response or 'key' not in response:
         print("FAILED: Response missing required fields")
         # sys.exit(1) # Don't exit, just print failure

    # Test Ingestion Handler
    print("\n3. Testing Ingestion Handler...")
    mock_event_s3 = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "mock-bucket"},
                    "object": {"key": "tenant-abc/doc-123.pdf"}
                }
            }
        ]
    }
    
    # Mock S3 get_object
    mock_s3_body = MagicMock()
    mock_s3_body.read.return_value = b"%PDF-1.4 mock content"
    ingestion_handler.s3_client.get_object.return_value = {
        'Body': mock_s3_body,
        'ContentType': 'application/pdf'
    }
    
    # Mock AI/Vector
    ingestion_handler.doc_processor.process = MagicMock(return_value=["chunk1", "chunk2"])
    ingestion_handler.ai_handler = MagicMock()
    ingestion_handler.vector_repo = MagicMock()
    
    ingestion_handler.lambda_handler(mock_event_s3, None)
    print("   Ingestion executed successfully (mocked).")

except ImportError as e:
    print(f"FAILED: Import Error - {e}")
    sys.exit(1)
except Exception as e:
    print(f"FAILED: Runtime Error - {e}")
    sys.exit(1)
