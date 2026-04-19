import json
import pytest
from unittest.mock import MagicMock, patch
from get_public_profile.handler import lambda_handler

@pytest.fixture
def mock_dynamodb():
    with patch("boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        yield mock_table

def test_get_public_profile_provider_filtering(mock_dynamodb):
    # This tests the fix where direct provider links ONLY return that provider
    
    # 1. Mock Tenant not found by slug (falls back to provider scan)
    mock_dynamodb.query.return_value = {"Items": [], "Count": 0}
    
    # 2. Mock Provider Scan found "Felix"
    mock_provider_table = MagicMock()
    mock_provider_table.scan.return_value = {
        "Items": [
            {
                "providerId": "felix_id",
                "tenantId": "t1",
                "slug": "felix-marquez",
                "name": "Felix Marquez",
                "active": True
            }
        ]
    }
    
    # 3. Mock Tenant lookup for branding
    mock_dynamodb.get_item.return_value = {
        "Item": {
            "tenantId": "t1",
            "name": "Clinica Felix",
            "slug": "clinica",
            "settings": "{}"
        }
    }
    
    # 4. Mock Services Table
    mock_service_table = MagicMock()
    mock_service_table.scan.return_value = {"Items": []}
    
    # 5. Mock Providers Table list (Return MULTIPLE providers to check filtering)
    # This simulates "Mario", "Felix", and "Lucy" being in the tenant
    mock_provider_table_list = MagicMock()
    mock_provider_table_list.scan.return_value = {
        "Items": [
            {"providerId": "felix_id", "name": "Felix Marquez", "tenantId": "t1", "active": True},
            {"providerId": "mario_id", "name": "Mario Alvarez", "tenantId": "t1", "active": True},
            {"providerId": "lucy_id", "name": "Lucy Lisperguer", "tenantId": "t1", "active": True},
        ]
    }

    def mock_table_side_effect(name):
        if name == "ChatBooking-Services":
            return mock_service_table
        if name == "ChatBooking-Providers":
            # First call for scan(slug), second for scan(tenantId)
            # Actually, the handler creates new table resource each time or uses side effect
            return mock_provider_table_list
        return mock_dynamodb

    with patch("boto3.resource") as resource_mock:
        resource_mock.return_value.Table.side_effect = mock_table_side_effect
        
        # Override the scan for fallback slug search specifically
        mock_provider_table_list.scan.side_effect = [
            {"Items": [{"providerId": "felix_id", "tenantId": "t1", "slug": "felix-marquez", "name": "Felix Marquez", "active": True}]}, # Fallback scan
            {"Items": [ # List scan
                {"providerId": "felix_id", "name": "Felix Marquez", "tenantId": "t1", "active": True},
                {"providerId": "mario_id", "name": "Mario Alvarez", "tenantId": "t1", "active": True},
                {"providerId": "lucy_id", "name": "Lucy Lisperguer", "tenantId": "t1", "active": True},
            ]}
        ]

        event = {"slug": "felix-marquez"}
        response = lambda_handler(event, {})

        assert response["name"] == "Felix Marquez"
        assert response["preselectedProviderId"] == "felix_id"
        
        # [THE CRITICAL ASSERTION]
        # Should only have 1 provider in the list, even though the tenant has 3
        assert len(response["providers"]) == 1
        assert response["providers"][0]["providerId"] == "felix_id"
        assert response["providers"][0]["name"] == "Felix Marquez"

