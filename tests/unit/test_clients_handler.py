
import unittest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
import os
import sys

# Set Mock credentials/config BEFORE importing handler to avoid NoRegionError
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["CLIENTS_TABLE"] = "ClientsTable"

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Add clients directory to path so 'import validation' works inside handler
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'clients'))

from clients import handler

class TestClientsHandler(unittest.TestCase):
    def setUp(self):
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        self.tenant_id = "tenant-123"
        self.client_id = "client-abc"
        
        # Mock DynamoDB Table
        self.mock_table = Mock()
        handler.clients_table = self.mock_table

    def test_create_client_success(self):
        # Arrange
        input_data = {
            "names": {"given": "Juan", "family": "Perez"},
            "identifiers": [{"type": "TAX_ID", "value": "11111111-1"}]
        }
        
        # Mock verification to always pass for this test
        with patch('clients.handler.validate_id', return_value=True):
             # Mock unique check (query returns empty items)
            self.mock_table.query.return_value = {"Items": [], "Count": 0}
            
            # Act
            result = handler.create_client(self.tenant_id, input_data)
            
            # Assert
            self.assertEqual(result["names"]["given"], "Juan")
            self.assertEqual(result["tenantId"], self.tenant_id)
            self.mock_table.put_item.assert_called_once()

    def test_create_client_security_failure(self):
        # Arrange
        input_data = {
            "tenantId": "hacker-tenant", # Mismatch
            "names": {"given": "Bad", "family": "Actor"}
        }
        
        # Act & Assert
        with self.assertRaises(ValueError) as context:
            handler.create_client(self.tenant_id, input_data)
        
        self.assertIn("Unauthorized", str(context.exception))

    def test_create_client_invalid_id(self):
        # Arrange
        input_data = {
            "names": {"given": "Juan", "family": "Perez"},
            "identifiers": [{"type": "TAX_ID", "value": "BAD-ID"}]
        }
        
        # Mock query needed for duplicate check which runs before validation
        self.mock_table.query.return_value = {"Items": [], "Count": 0}

        # Mock validation failure
        with patch('clients.handler.validate_id', return_value=False):
            # Act & Assert
            with self.assertRaises(ValueError) as context:
                handler.create_client(self.tenant_id, input_data)
            
            self.assertIn("Invalid identifier", str(context.exception))

    def test_get_client_success(self):
        # Arrange
        mock_item = {
            "id": self.client_id,
            "tenantId": self.tenant_id,
            "names": {"given": "Maria", "family": "Lopez"}
        }
        self.mock_table.get_item.return_value = {"Item": mock_item}
        
        # Act
        result = handler.get_client(self.tenant_id, self.client_id)
        
        # Assert
        self.assertEqual(result["names"]["given"], "Maria")
        self.mock_table.get_item.assert_called_with(
            Key={"tenantId": self.tenant_id, "id": self.client_id}
        )

    def test_get_client_not_found(self):
        # Arrange
        self.mock_table.get_item.return_value = {} # No Item
        
        # Act
        result = handler.get_client(self.tenant_id, "non-existent")
        
        # Assert
        self.assertIsNone(result)

    def test_list_clients(self):
        # Arrange
        mock_items = [
            {"id": "1", "tenantId": self.tenant_id, "names": {"given": "A"}},
            {"id": "2", "tenantId": self.tenant_id, "names": {"given": "B"}}
        ]
        self.mock_table.query.return_value = {"Items": mock_items}
        
        # Act
        result = handler.list_clients(self.tenant_id)
        
        # Assert
        self.assertEqual(len(result), 2)
        # Check that query was called with KeyConditionExpression
        self.mock_table.query.assert_called_once()
        call_kwargs = self.mock_table.query.call_args.kwargs
        self.assertIn('KeyConditionExpression', call_kwargs)

    def test_update_client_success(self):
        # Arrange
        mock_existing = {
            "id": self.client_id,
            "tenantId": self.tenant_id,
            "names": {"given": "Old", "family": "Name"}
        }
        self.mock_table.get_item.return_value = {"Item": mock_existing}
        
        update_input = {
            "id": self.client_id,
            "names": {"given": "New", "family": "Name"}
        }
        
        # Act
        result = handler.update_client(self.tenant_id, update_input)
        
        # Assert
        self.assertEqual(result["names"]["given"], "New")
        self.mock_table.put_item.assert_called_once()
