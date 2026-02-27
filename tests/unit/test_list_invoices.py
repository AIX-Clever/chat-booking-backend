import unittest
from unittest.mock import MagicMock, patch
import json
import os

# Mock the environment and dependencies before importing the handler
with patch.dict(os.environ, {"SUBSCRIPTIONS_TABLE": "TestTable"}):
    from subscriptions.handlers.list_invoices import lambda_handler

class TestListInvoices(unittest.TestCase):
    @patch('subscriptions.handlers.list_invoices.SUBSCRIPTIONS_TABLE')
    def test_lambda_handler_success(self, mock_table):
        # Setup mock data
        tenant_id = "tenant-123"
        mock_items = [
            {
                'subscriptionId': 'PAYMENT#pay-001',
                'amount': '15000',
                'currency': 'CLP',
                'status': 'approved',
                'processedAt': '2026-02-26T10:00:00Z',
                'dteFolio': '101',
                'dtePdfUrl': 'http://pdf.url',
                'dteTrackId': 'track-001',
                'dteSiiStatus': 'ACEPTADO',
                'dteLastSync': '2026-02-26T12:00:00Z',
                'metadata': {'order': '123'}
            }
        ]
        mock_table.query.return_value = {'Items': mock_items}
        
        event = {'arguments': {'tenantId': tenant_id}}
        result = lambda_handler(event, None)
        
        # Verify mapping
        self.assertEqual(len(result), 1)
        invoice = result[0]
        self.assertEqual(invoice['invoiceId'], 'pay-001')
        self.assertEqual(invoice['amount'], 15000.0)
        self.assertEqual(invoice['dteTrackId'], 'track-001')
        self.assertEqual(invoice['dteSiiStatus'], 'ACEPTADO')
        self.assertEqual(invoice['dteLastSync'], '2026-02-26T12:00:00Z')
        self.assertEqual(invoice['dteFolio'], '101')
        
    @patch('subscriptions.handlers.list_invoices.SUBSCRIPTIONS_TABLE')
    def test_lambda_handler_empty(self, mock_table):
        mock_table.query.return_value = {'Items': []}
        event = {'arguments': {'tenantId': 'tenant-123'}}
        result = lambda_handler(event, None)
        self.assertEqual(result, [])

if __name__ == "__main__":
    unittest.main()
