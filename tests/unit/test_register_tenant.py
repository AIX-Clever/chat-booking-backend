import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add path to sys to import lambda handlers
backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
layer_path = os.path.join(os.path.dirname(backend_path), 'chat-booking-layers', 'layer', 'python')
sys.path.insert(0, backend_path)
sys.path.insert(0, layer_path)

from register_tenant.handler import lambda_handler

class TestRegisterTenant(unittest.TestCase):

    def setUp(self):
        self.mock_env = patch.dict(os.environ, {
            'USER_POOL_ID': 'dummy_pool',
            'USER_ROLES_TABLE': 'dummy_roles_table',
            'RECAPTCHA_SECRET_KEY': 'dummy_secret'
        })
        self.mock_env.start()

    def tearDown(self):
        self.mock_env.stop()

    @patch('shared.infrastructure.recaptcha_adapter.GoogleRecaptchaAdapter')
    @patch('register_tenant.handler.DynamoDBTenantRepository')
    @patch('register_tenant.handler.DynamoDBApiKeyRepository')
    @patch('register_tenant.handler.boto3.client')
    def test_register_success_with_valid_recaptcha(self, mock_boto, mock_api_repo, mock_tenant_repo, mock_recaptcha):
        # Setup Mocks
        mock_recaptcha_instance = mock_recaptcha.return_value
        mock_recaptcha_instance.verify.return_value = True
        
        # Configure Cognito Mock
        mock_cognito = MagicMock()
        mock_boto.return_value = mock_cognito
        mock_cognito.admin_create_user.return_value = {
            "User": {
                "Attributes": [
                    {"Name": "sub", "Value": "test-user-sub-uuid"}
                ]
            }
        }
        
        # We need to perform a reload or reset global if it was already initialized?
        # The handler uses a global 'cognito'. If it's None, it calls boto3.client using our mock.
        # But if tests run in same process, it might be already set. 
        # Ideally we patch the global variable or ensure teardown resets it.
        import register_tenant.handler
        register_tenant.handler.cognito = None 
        register_tenant.handler.workflows_table = MagicMock()
        register_tenant.handler.user_roles_table = MagicMock()
        register_tenant.handler.categories_table = MagicMock()
        
        event = {
            "arguments": {
                "input": {
                    'email': 'test@example.com',
                    'firstName': 'Test',
                    'lastName': 'User',
                    'password': 'Password123!',
                    'recaptchaToken': 'valid_token'
                }
            }
        }
        
        response = lambda_handler(event, {})
        
        # Assertions
        # AppSync resolver returns the object directly, not statusCode
        self.assertIn("tenantId", response)
        self.assertEqual(response["ownerUserId"], "test-user-sub-uuid")
        
        mock_recaptcha_instance.verify.assert_called_with('valid_token', 'signup')
        mock_tenant_repo.return_value.save.assert_called()
        mock_cognito.admin_create_user.assert_called()

    @patch('shared.infrastructure.recaptcha_adapter.GoogleRecaptchaAdapter')
    def test_register_failure_with_invalid_recaptcha(self, mock_recaptcha):
        # Setup Mocks
        mock_recaptcha_instance = mock_recaptcha.return_value
        mock_recaptcha_instance.verify.return_value = False
        
        event = {
            "arguments": {
                 "input": {
                    'email': 'test@example.com',
                    'firstName': 'Bot',
                    'lastName': 'User',
                    'password': 'Password123!',
                    'recaptchaToken': 'invalid_token'
                }
            }
        }
        
        # Handler catches ValueError and raises Exception for AppSync
        with self.assertRaises(Exception) as context:
            lambda_handler(event, {})
            
        self.assertIn("Security verification failed", str(context.exception))
