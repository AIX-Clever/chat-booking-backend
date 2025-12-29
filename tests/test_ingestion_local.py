import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import json

# Add project root AND knowledge_base to path to simulate Lambda environment
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'knowledge_base')))

# Mock boto3 before importing handler to prevent credential errors
with patch('boto3.client') as mock_boto:
    # Set env vars expected by IngestionFunction
    os.environ['DB_SECRET_ARN'] = 'arn:aws:secretsmanager:us-east-1:123:secret:db-123'
    os.environ['DB_ENDPOINT'] = 'arn:aws:rds:us-east-1:123:cluster:db-123'
    os.environ['DOCUMENTS_TABLE'] = 'ChatBooking-Documents'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    
    # Import the handler (this validates Imports work!)
    from knowledge_base.ingestion_handler import lambda_handler, process_record
    from shared.ai_handler import AIHandler
    from shared.infrastructure.vector_repository import VectorRepository

class TestIngestionExecution(unittest.TestCase):
    
    @patch('shared.infrastructure.vector_repository.VectorRepository._execute')
    @patch('boto3.client')
    def test_schema_intialization_and_dimensions(self, mock_boto, mock_execute):
        """
        Verify:
        1. ensure_schema is called (Table creation)
        2. AIHandler uses 1024 dimensions
        """
        # Setup Mocks
        mock_s3 = MagicMock()
        mock_bedrock = MagicMock()
        mock_boto.side_effect = lambda service, **kwargs: {
            's3': mock_s3,
            'bedrock-runtime': mock_bedrock,
            'rds-data': MagicMock(),
            'dynamodb': MagicMock()
        }.get(service, MagicMock())

        # Mock S3 Get Object
        mock_s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: b"Test content for embedding")
        }

        # Mock Bedrock Response with 1024 dimensions check
        def check_bedrock_call(*args, **kwargs):
            body = json.loads(kwargs['body'])
            # CRITICAL CHECK: Dimensions must be 1024
            if body.get('dimensions') != 1024:
                raise ValueError(f"CRITICAL: Dimensions set to {body.get('dimensions')}, expected 1024!")
            
            return {
                'body': MagicMock(read=lambda: json.dumps({'embedding': [0.1]*1024}).encode())
            }
        
        mock_bedrock.invoke_model.side_effect = check_bedrock_call
        
        # Initialize Repo & Handler
        # Note: In real Lambda these are global, here we institute them
        vector_repo = VectorRepository("arn:x", "arn:y")
        ai_handler = AIHandler(vector_repo)
        
        # Test 1: Check Schema Call
        vector_repo.ensure_schema()
        # Verify CREATE TABLE was called
        create_calls = [call for call in mock_execute.call_args_list if "CREATE TABLE" in call[0][0]]
        self.assertTrue(len(create_calls) > 0, "ensure_schema did not try to CREATE TABLE")
        print("✅ Unit Test: ensure_schema() correctly attempts table creation.")

        # Test 2: Check Embedding Dimensions
        try:
            ai_handler.get_embedding("Run test")
            print("✅ Unit Test: AIHandler.get_embedding() successfully called with 1024 dimensions.")
        except ValueError as e:
            self.fail(str(e))

if __name__ == '__main__':
    unittest.main()
