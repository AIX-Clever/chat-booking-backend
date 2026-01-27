import json
import os
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
import pytest
from unittest.mock import MagicMock, patch
from profile_baker.handler import lambda_handler

@pytest.fixture
def mock_s3():
    with patch('boto3.client') as mock_client:
        mock_s3 = MagicMock()
        def side_effect(service_name, **kwargs):
            if service_name == 's3':
                return mock_s3
            return MagicMock() # For other clients if any (cloudfront handled below)
        mock_client.side_effect = side_effect
        yield mock_s3

@pytest.fixture
def mock_cloudfront():
    with patch('boto3.client') as mock_client:
        mock_cf = MagicMock()
        def side_effect(service_name, **kwargs):
            if service_name == 'cloudfront':
                return mock_cf
            if service_name == 's3': # Need to handle s3 as well since both use boto3.client
                 # This is tricky with multiple patches on same object.
                 # Better to mock globally or per test inside the test function
                 pass
            return MagicMock()
        
        # We will manually patch boto3.client in the test to control return values
        yield mock_cf

def test_profile_baker_insert_event():
    # Setup Mocks
    mock_s3 = MagicMock()
    mock_cloudfront = MagicMock()
    
    # Mock S3 get_object response (Template)
    mock_s3.get_object.return_value = {
        'Body': MagicMock(read=lambda: b'<html><head><title>Original</title></head><body></body></html>')
    }

    # Patch module-level clients and variables
    with patch('profile_baker.handler.s3', mock_s3), \
         patch('profile_baker.handler.cloudfront', mock_cloudfront), \
         patch('profile_baker.handler.LINK_BUCKET', 'test-bucket'), \
         patch('profile_baker.handler.DISTRIBUTION_ID', 'TEST_DIST_ID'):
        
        # DynamoDB Stream Event
        event = {
            'Records': [
                {
                    'eventName': 'INSERT',
                    'dynamodb': {
                        'NewImage': {
                            'tenantId': {'S': 't1'},
                            'slug': {'S': 'doctor-who'},
                            'name': {'S': 'The Doctor'},
                            'bio': {'S': 'Time Lord'},
                            'photoUrl': {'S': 'http://tardis.com/image.jpg'}
                        }
                    }
                }
            ]
        }
        
        # Execute
        response = lambda_handler(event, MagicMock(aws_request_id='req-123'))
        
        # Verify
        assert response['status'] == 'success'
        
        # 1. Verify Template Read
        mock_s3.get_object.assert_called_with(Bucket='test-bucket', Key='index.html')
        
        # 2. Verify Upload (Baked HTML)
        call_args = mock_s3.put_object.call_args
        assert call_args is not None
        _, kwargs = call_args
        assert kwargs['Bucket'] == 'test-bucket'
        assert kwargs['Key'] == 'doctor-who/index.html'
        assert kwargs['ContentType'] == 'text/html'
        
        # Verify Content Injection
        uploaded_body = kwargs['Body'].decode('utf-8')
        assert '<title>Reserva con The Doctor | Lucia</title>' in uploaded_body
        assert 'content="Time Lord"' in uploaded_body
        assert 'content="http://tardis.com/image.jpg"' in uploaded_body
        
        # 3. Verify CloudFront Invalidation
        mock_cloudfront.create_invalidation.assert_called_once()
        _, cf_kwargs = mock_cloudfront.create_invalidation.call_args
        assert cf_kwargs['DistributionId'] == 'TEST_DIST_ID'
        assert cf_kwargs['InvalidationBatch']['Paths']['Items'] == ['/doctor-who*']

def test_profile_baker_skip_no_slug():
    mock_s3 = MagicMock()
    
    with patch('profile_baker.handler.s3', mock_s3), \
         patch('profile_baker.handler.LINK_BUCKET', 'test-bucket'):
        event = {
            'Records': [
                {
                    'eventName': 'MODIFY',
                    'dynamodb': {
                        'NewImage': {
                            'tenantId': {'S': 't2'},
                            # No slug
                            'name': {'S': 'No Slug'}
                        }
                    }
                }
            ]
        }
        
        response = lambda_handler(event, {})
        assert response['status'] == 'success'
        
        # Should NOT call S3 or CloudFront
        mock_s3.get_object.assert_not_called()
        mock_s3.put_object.assert_not_called()

def test_profile_baker_missing_template():
    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = Exception("NoSuchKey")
    
    with patch('profile_baker.handler.s3', mock_s3), \
         patch('profile_baker.handler.LINK_BUCKET', 'test-bucket'):
            event = {
                'Records': [
                    {
                        'eventName': 'INSERT',
                        'dynamodb': {
                            'NewImage': {
                                'slug': {'S': 'test'},
                                'name': {'S': 'Test'}
                            }
                        }
                    }
                ]
            }
            
            # Should catch exception and log error, preventing crash of the lambda handler loop?
            # The handler catches exception for individual record processing
            response = lambda_handler(event, {})
            assert response['status'] == 'success'
            
            mock_s3.get_object.assert_called()
            mock_s3.put_object.assert_not_called()
