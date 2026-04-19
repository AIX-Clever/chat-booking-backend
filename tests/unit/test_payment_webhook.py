import os
import sys
import unittest
import json
import hashlib
import hmac
from unittest.mock import MagicMock, patch

# Add path to sys to import lambda handlers
backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
layer_path = os.path.join(os.path.dirname(backend_path), 'chat-booking-layers', 'layer', 'python')

sys.path.insert(0, backend_path)
sys.path.insert(0, layer_path)

from payment.webhook_handler import lambda_handler

class TestPaymentWebhook(unittest.TestCase):

    def setUp(self):
        self.mock_env = patch.dict(os.environ, {
            'MP_WEBHOOK_SECRET': 'test_secret',
            'MP_ACCESS_TOKEN_PROD': 'test_token'
        })
        self.mock_env.start()

    def tearDown(self):
        self.mock_env.stop()

    def _generate_signature(self, data_id, req_id, ts, secret):
        manifest = f"id:{data_id};request-id:{req_id};ts:{ts};"
        return hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()

    @patch('payment.webhook_handler.booking_repo')
    @patch('payment.webhook_handler.requests.get')
    def test_valid_signature_and_payment_processing(self, mock_requests, mock_booking_repo):
        # 1. Mock MP API Response
        mock_requests.return_value.status_code = 200
        mock_requests.return_value.json.return_value = {
            'status': 'approved',
            'status_detail': 'accredited',
            'external_reference': 'tenant-123:booking-456'
        }

        # 2. Mock Booking Repo
        mock_booking = MagicMock()
        # We need to simulate the properties properly if strictly typed, but MagicMock handles access.
        # However, logic checks: if booking.payment_status == PaymentStatus.PAID
        # We need PaymentStatus enum or mock it?
        # Ideally we import PaymentStatus. But checks are equality.
        # Let's import entities to be safe.
        from shared.domain.entities import BookingStatus, PaymentStatus
        
        mock_booking.payment_status = PaymentStatus.PENDING
        mock_booking.status = BookingStatus.PENDING
        mock_booking_repo.get_by_id.return_value = mock_booking
        
        # 3. Generate Valid Signature
        ts = "12345"
        req_id = "uuid-123"
        data_id = "payment-123"
        secret = "test_secret"
        signature = self._generate_signature(data_id, req_id, ts, secret)
        
        event = {
            'headers': {
                'x-signature': f"ts={ts},v1={signature}",
                'x-request-id': req_id
            },
            'queryStringParameters': {
                'topic': 'payment',
                'id': data_id
            }
        }
        
        response = lambda_handler(event, {})
        
        # 4. Assertions
        self.assertEqual(response['statusCode'], 200)
        
        # Verify MP API was called
        mock_requests.assert_called()
        
        # Verify Booking was retrieved
        # tenant_id_str, booking_id = 'tenant-123', 'booking-456'
        # Can't easily check args for get_by_id without importing TenantId
        mock_booking_repo.get_by_id.assert_called()
        
        # Verify Booking was updated
        self.assertEqual(mock_booking.payment_status, PaymentStatus.PAID)
        self.assertEqual(mock_booking.status, BookingStatus.CONFIRMED)
        mock_booking_repo.update.assert_called_with(mock_booking)

    @patch('payment.webhook_handler.requests.get')
    def test_mp_api_failure(self, mock_requests):
        # Mock MP API Failure
        mock_requests.return_value.status_code = 400
        mock_requests.return_value.text = "Bad Request"
        
        ts = "12345"
        req_id = "uuid-fail"
        data_id = "payment-fail"
        secret = "test_secret"
        signature = self._generate_signature(data_id, req_id, ts, secret)
        
        event = {
            'headers': {
                'x-signature': f"ts={ts},v1={signature}",
                'x-request-id': req_id
            },
            'queryStringParameters': {
                'topic': 'payment',
                'id': data_id
            }
        }
        
        response = lambda_handler(event, {})
        # Should return 200 to acknowledge webhook even if fetch failed
        self.assertEqual(response['statusCode'], 200)

    @patch('payment.webhook_handler.requests.get')
    def test_payment_invalid_reference(self, mock_requests):
        # Mock MP API Success but invalid ref
        mock_requests.return_value.status_code = 200
        mock_requests.return_value.json.return_value = {
            'status': 'approved',
            'status_detail': 'accredited',
            'external_reference': 'invalid-format'
        }
        
        ts = "12345"
        req_id = "uuid-fail-ref"
        data_id = "payment-fail-ref"
        secret = "test_secret"
        signature = self._generate_signature(data_id, req_id, ts, secret)
        
        event = {
            'headers': {
                'x-signature': f"ts={ts},v1={signature}",
                'x-request-id': req_id
            },
            'queryStringParameters': {
                'topic': 'payment',
                'id': data_id
            }
        }
        
        response = lambda_handler(event, {})
        self.assertEqual(response['statusCode'], 200)

    def test_missing_token(self):
        with patch.dict(os.environ, {'MP_ACCESS_TOKEN_PROD': ''}):
            ts = "12345"
            req_id = "uuid-no-token"
            data_id = "payment-no-token"
            secret = "test_secret"
            signature = self._generate_signature(data_id, req_id, ts, secret)
            
            event = {
                'headers': {
                    'x-signature': f"ts={ts},v1={signature}",
                    'x-request-id': req_id
                },
                'queryStringParameters': {
                    'topic': 'payment',
                    'id': data_id
                }
            }
            
            response = lambda_handler(event, {})
            # process_payment returns 500 if token missing
            self.assertEqual(response['statusCode'], 500)
            self.assertEqual(response['body'], 'Config Error')

    def test_non_payment_topic(self):
         event = {'queryStringParameters': {'topic': 'subscription', 'id': '123'}}
         response = lambda_handler(event, {})
         self.assertEqual(response['statusCode'], 200)

    @patch('payment.webhook_handler.booking_repo')
    @patch('payment.webhook_handler.requests.get')
    def test_body_parsing_fallback(self, mock_requests, mock_booking_repo):
        # 1. Mock MP API Response
        mock_requests.return_value.status_code = 200
        mock_requests.return_value.json.return_value = {
            'status': 'approved',
            'status_detail': 'accredited',
            'external_reference': 'tenant-123:booking-456'
        }

        # 2. Mock Booking Repo
        mock_booking = MagicMock()
        from shared.domain.entities import BookingStatus, PaymentStatus
        mock_booking.payment_status = PaymentStatus.PENDING
        mock_booking.status = BookingStatus.PENDING
        mock_booking_repo.get_by_id.return_value = mock_booking
        
        # 3. Generate Valid Signature
        ts = "12345"
        req_id = "uuid-body"
        data_id = "payment-body"
        secret = "test_secret"
        signature = self._generate_signature(data_id, req_id, ts, secret)
        
        # Construct event with BODY instead of QueryParams
        body_payload = {
            'topic': 'payment',
            'data': {'id': data_id}
        }
        
        event = {
            'headers': {
                'x-signature': f"ts={ts},v1={signature}",
                'x-request-id': req_id
            },
            'queryStringParameters': None,
            'body': json.dumps(body_payload)
        }
        
        response = lambda_handler(event, {})
        
        # 4. Assertions
        self.assertEqual(response['statusCode'], 200)
        mock_requests.assert_called()
        mock_booking_repo.update.assert_called()

    def test_invalid_signature_rejected(self):
        ts = "12345"
        req_id = "uuid-123"
        data_id = "payment-123"
        signature = "invalid_hash"
        
        event = {
            'headers': {
                'x-signature': f"ts={ts},v1={signature}",
                'x-request-id': req_id
            },
            'queryStringParameters': {
                'topic': 'payment',
                'id': data_id
            }
        }
        
        response = lambda_handler(event, {})
        self.assertEqual(response['statusCode'], 200) # Returns 200 to ack but body says invalid
        self.assertIn("Invalid Signature", response['body'])

