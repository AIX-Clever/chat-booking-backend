import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add layer path to simulate Lambda environment
LAYER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../chat-booking-layers/layer/python'))
sys.path.append(LAYER_PATH)

from shared.domain.entities import Provider, TenantId
from shared.infrastructure.dynamodb_repositories import DynamoDBProviderRepository

class TestProviderPersistence(unittest.TestCase):
    
    def setUp(self):
        # Patch boto3.resource to prevent real connection / region check
        self.patcher = patch('boto3.resource')
        self.mock_db_resource = self.patcher.start()
        
        # Configure the mock to return our mock table
        self.mock_table = MagicMock()
        self.mock_db_resource.return_value.Table.return_value = self.mock_table
        
        # Initialize repo (will use the mocked boto3.resource)
        self.repo = DynamoDBProviderRepository("test-table")
    
    def tearDown(self):
        self.patcher.stop()

    def test_save_provider_with_photo(self):
        """
        Verify that saving a provider with photo_url correctly maps to the DynamoDB item.
        """
        provider = Provider(
            provider_id="pro_test_123",
            tenant_id=TenantId("tenant_123"),
            name="Test Provider",
            bio="Test Bio",
            service_ids=["svc_1"],
            timezone="UTC",
            active=True,
            photo_url="https://example.com/photo.jpg",
            photo_url_thumbnail="https://example.com/thumb.jpg"
        )

        # Execute save
        self.repo.save(provider)

        # Assert put_item was called
        self.mock_table.put_item.assert_called_once()
        
        # Verify the item passed to put_item contains photoUrl
        call_args = self.mock_table.put_item.call_args
        item_saved = call_args.kwargs['Item']
        
        self.assertEqual(item_saved['providerId'], "pro_test_123")
        self.assertEqual(item_saved['photoUrl'], "https://example.com/photo.jpg")
        self.assertEqual(item_saved['photoUrlThumbnail'], "https://example.com/thumb.jpg")
        
        print("\n✅ Verification Successful: 'photoUrl' and 'photoUrlThumbnail' persisted to DynamoDB item.")

    def test_item_to_entity_with_photo(self):
        """
        Verify that retrieving an item with photoUrl correctly maps back to the Entity.
        """
        item = {
            'tenantId': 'tenant_123',
            'providerId': 'pro_test_123',
            'name': 'Test Provider',
            'services': ['svc_1'],
            'timezone': 'UTC',
            'active': True,
            'photoUrl': "https://example.com/photo.jpg",
            'photoUrlThumbnail': "https://example.com/thumb.jpg"
        }

        # Use private method to test conversion logic
        provider = self.repo._item_to_entity(item)

        self.assertEqual(provider.photo_url, "https://example.com/photo.jpg")
        self.assertEqual(provider.photo_url_thumbnail, "https://example.com/thumb.jpg")
        
        print("✅ Verification Successful: 'photoUrl' correctly mapped back to Provider entity.")

if __name__ == '__main__':
    unittest.main()
