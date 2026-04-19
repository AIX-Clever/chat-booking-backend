import sys
import os
import unittest
import json
from unittest.mock import MagicMock, patch

os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
os.environ['DTE_API_URL'] = 'http://mock-dte-api'

# Add layer path 
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repos_root = os.path.dirname(project_root)
layer_path = os.path.join(repos_root, 'chat-booking-layers', 'layer', 'python')

sys.path.insert(0, layer_path)
sys.path.append(project_root)

# Mocking stripe to avoid errors
sys.modules['stripe'] = MagicMock()

# Import the handler
from payment.dte_worker import lambda_handler
from shared.domain.entities import TenantId, PaymentStatus

class TestDteWorker(unittest.TestCase):

    def setUp(self):
        self.mock_repo = MagicMock()
        # Patch dependencies in dte_worker
        self.repo_patcher = patch('payment.dte_worker.booking_repo', self.mock_repo)
        self.repo_patcher.start()

    def tearDown(self):
        self.repo_patcher.stop()

    @patch('payment.dte_worker.requests.post')
    def test_dte_worker_success(self, mock_post):
        print("\n--- Testing DTE Worker ---")
        
        # 1. Mock DTE API Response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'success': True,
            'folio': 1234,
            'pdfUrl': 'http://mock.pdf'
        }
        mock_post.return_value = mock_response
        
        # 2. Mock Booking in Repo
        mock_booking = MagicMock()
        mock_booking.booking_id = 'bkg_1'
        self.mock_repo.get_by_id.return_value = mock_booking
        
        # 3. Simulate SQS Event
        payload = {
            "bookingId": "bkg_1",
            "tenantId": "tenant-A",
            "paymentId": "pi_123",
            "amount": 25000,
            "customer": {"name": "Juan"}
        }
        event = {
            'Records': [
                {
                    'body': json.dumps(payload)
                }
            ]
        }
        
        # 4. Execute
        response = lambda_handler(event, {})
        
        # 5. Verify
        self.assertEqual(response['statusCode'], 200)
        
        # Verify API Call
        mock_post.assert_called_once()
        
        # Verify Repo Update
        self.mock_repo.get_by_id.assert_called_once()
        self.mock_repo.update.assert_called_once()
        self.assertEqual(mock_booking.dte_folio, '1234')
        self.assertEqual(mock_booking.dte_pdf_url, 'http://mock.pdf')
        
        print("✅ DTE Worker correctly processed SQS message and updated DTE metadata")

    @patch('payment.dte_worker.requests.post')
    def test_dte_worker_retry_on_failure(self, mock_post):
        print("--- Testing DTE Worker Retry Logic ---")
        
        # 1. Mock DTE API Failure (SII Down)
        mock_post.side_effect = Exception("SII Connection Timeout")
        
        # 2. Simulate SQS Event
        event = {'Records': [{'body': json.dumps({"bookingId": "bkg_2", "tenantId": "A"})}]}
        
        # 3. Verify that it raises Exception (triggering SQS retry)
        with self.assertRaises(Exception):
            lambda_handler(event, {})
        
        print("✅ DTE Worker correctly raised exception on failure to trigger SQS retry")

if __name__ == '__main__':
    unittest.main()
