import unittest
from unittest.mock import MagicMock, patch
import os
from datetime import datetime

# Setup environment
with patch.dict(os.environ, {"SUBSCRIPTIONS_TABLE": "TestTable"}):
    from subscriptions.workers.sii_status_sync import lambda_handler, sync_document_status

class TestSiiStatusSync(unittest.TestCase):
    @patch('subscriptions.workers.sii_status_sync.SUBSCRIPTIONS_TABLE')
    def test_lambda_handler_finds_items_in_process(self, mock_table):
        # Setup mock for scan
        mock_table.scan.return_value = {
            'Items': [
                {'tenantId': 't1', 'subscriptionId': 'P#1', 'dteSiiStatus': 'EN_PROCESO', 'dteTrackId': 'track1'}
            ]
        }
        
        with patch('subscriptions.workers.sii_status_sync.sync_document_status') as mock_sync:
            lambda_handler({}, None)
            mock_sync.assert_called_once()
    
    @patch('subscriptions.workers.sii_status_sync.SUBSCRIPTIONS_TABLE')
    def test_sync_document_status_updates_db(self, mock_table):
        item = {
            'tenantId': 't1',
            'subscriptionId': 'P#1',
            'dteTrackId': 'track1'
        }
        
        sync_document_status(item)
        
        # Verify update_item was called with ACEPTADO (current placeholder logic)
        mock_table.update_item.assert_called_once()
        args, kwargs = mock_table.update_item.call_args
        self.assertEqual(kwargs['UpdateExpression'], "set dteSiiStatus = :s, dteLastSync = :now")
        self.assertEqual(kwargs['ExpressionAttributeValues'][':s'], 'ACEPTADO')

if __name__ == "__main__":
    unittest.main()
