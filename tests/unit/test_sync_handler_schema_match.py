import unittest
import os
from unittest.mock import patch, MagicMock

# Set environment variables BEFORE importing the handler
os.environ['CLIENTS_TABLE'] = 'TestClientsTable'
os.environ['CLIENT_AUDIT_LOGS_TABLE'] = 'TestAuditTable'

from clients.sync_handler import lambda_handler


class TestSyncHandlerSchema(unittest.TestCase):
    @patch('clients.sync_handler.clients_table')
    @patch('clients.sync_handler.audit_table')
    @patch('clients.sync_handler._sync_client')
    def test_schema_mapping(self, mock_sync, mock_audit, mock_clients):
        # Simulate DynamoDB Stream event with structure matching BookingRepository
        event = {
            'Records': [
                {
                    'eventName': 'INSERT',
                    'dynamodb': {
                        'NewImage': {
                            'bookingId': {'S': 'bk-123'},
                            'tenantId': {'S': 'tenant-1'},
                            'clientEmail': {'S': 'test@example.com'},
                            'clientFirstName': {'S': 'Test'},
                            'clientLastName': {'S': 'User'},
                            'clientPhone': {'S': '+1234567890'},
                            'PK': {'S': 'tenant-1#prov-1'},
                            'SK': {'S': '2026-02-17T10:00:00'}
                        }
                    }
                }
            ]
        }

        lambda_handler(event, None)

        # Verify _sync_client was called with correct extracted data
        mock_sync.assert_called_once()
        args = mock_sync.call_args[0]
        tenant_id, booking_id, customer_info = args

        self.assertEqual(tenant_id, 'tenant-1')
        self.assertEqual(booking_id, 'bk-123')
        self.assertEqual(customer_info['email'], 'test@example.com')
        self.assertEqual(customer_info['firstName'], 'Test')
        self.assertEqual(customer_info['lastName'], 'User')
        self.assertEqual(customer_info['phone'], '+1234567890')

if __name__ == '__main__':
    unittest.main()
