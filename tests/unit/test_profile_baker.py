import json
import os

os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
import pytest
from unittest.mock import MagicMock, patch
from profile_baker.handler import lambda_handler


@pytest.fixture
def mock_s3():
    with patch("boto3.client") as mock_client:
        mock_s3 = MagicMock()

        def side_effect(service_name, **kwargs):
            if service_name == "s3":
                return mock_s3
            return MagicMock()  # For other clients if any (cloudfront handled below)

        mock_client.side_effect = side_effect
        yield mock_s3


@pytest.fixture
def mock_cloudfront():
    with patch("boto3.client") as mock_client:
        mock_cf = MagicMock()

        def side_effect(service_name, **kwargs):
            if service_name == "cloudfront":
                return mock_cf
            if (
                service_name == "s3"
            ):  # Need to handle s3 as well since both use boto3.client
                # This is tricky with multiple patches on same object.
                # Better to mock globally or per test inside the test function
                pass
            return MagicMock()

        # We will manually patch boto3.client in the test to control return values
        yield mock_cf


@pytest.fixture(autouse=True)
def mock_env():
    with patch.dict(
        os.environ,
        {
            "TENANTS_TABLE": "Tenants",
            "SERVICES_TABLE": "Services",
            "PROVIDERS_TABLE": "Providers",
            "LINK_BUCKET": "test-bucket",
            "DISTRIBUTION_ID": "TEST_DIST_ID",
        },
    ):
        yield


def test_profile_baker_provider_event():
    # Setup Mocks
    mock_s3 = MagicMock()
    mock_cloudfront = MagicMock()
    mock_dynamodb = MagicMock()

    # Mock S3 get_object response (Template)
    mock_s3.get_object.return_value = {
        "Body": MagicMock(
            read=lambda: b"<html><head><title>Original</title></head><body>{profile_data}</body></html>"
        )
    }

    # Mock DynamoDB Tables
    mock_tenants_table = MagicMock()
    mock_services_table = MagicMock()
    mock_providers_table = MagicMock()

    def get_table(name):
        if name == "Tenants":
            return mock_tenants_table
        if name == "Services":
            return mock_services_table
        if name == "Providers":
            return mock_providers_table
        return MagicMock()

    mock_dynamodb.Table.side_effect = get_table

    # Mock Tenant Data (for theme color)
    mock_tenants_table.get_item.return_value = {
        "Item": {
            "tenantId": "t1",
            "settings": json.dumps({"widgetConfig": {"primaryColor": "#FF5733"}}),
        }
    }

    # Mock services and providers fetch (scans)
    mock_services_table.scan.return_value = {"Items": []}
    mock_providers_table.scan.return_value = {"Items": []}

    # Patch module-level clients and variables
    with patch("profile_baker.handler.s3", mock_s3), patch(
        "profile_baker.handler.cloudfront", mock_cloudfront
    ), patch("profile_baker.handler.dynamodb", mock_dynamodb):

        # DynamoDB Provider Stream Event
        event = {
            "Records": [
                {
                    "eventName": "INSERT",
                    "dynamodb": {
                        "NewImage": {
                            "tenantId": {"S": "t1"},
                            "providerId": {"S": "p1"},
                            "slug": {"S": "dr-juan"},
                            "name": {"S": "Juan Perez"},
                            "bio": {"S": "Cardiologo"},
                            "photoUrl": {"S": "http://image.jpg"},
                        }
                    },
                }
            ]
        }

        # Execute
        response = lambda_handler(event, MagicMock(aws_request_id="req-123"))

        # Verify
        assert response["status"] == "success"

        # Verify Upload
        mock_s3.put_object.assert_called()
        _, kwargs = mock_s3.put_object.call_args
        assert kwargs["Key"] == "dr-juan/index.html"

        # Verify Content Injection (theme color and preselectedProviderId)
        uploaded_body = kwargs["Body"].decode("utf-8")
        assert "#FF5733" in uploaded_body
        assert "dr-juan" in uploaded_body
        assert '"preselectedProviderId": "p1"' in uploaded_body


def test_profile_baker_tenant_event():
    # Setup Mocks
    mock_s3 = MagicMock()
    mock_cloudfront = MagicMock()
    mock_dynamodb = MagicMock()

    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: b"<html><body>{profile_data}</body></html>")
    }

    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table
    mock_table.scan.return_value = {"Items": []}

    # Patch
    with patch("profile_baker.handler.s3", mock_s3), patch(
        "profile_baker.handler.cloudfront", mock_cloudfront
    ), patch("profile_baker.handler.dynamodb", mock_dynamodb), patch(
        "profile_baker.handler.LINK_BUCKET", "test-bucket"
    ), patch(
        "profile_baker.handler.DISTRIBUTION_ID", "TEST_DIST_ID"
    ):

        # DynamoDB Tenant Stream Event
        event = {
            "Records": [
                {
                    "eventName": "MODIFY",
                    "dynamodb": {
                        "NewImage": {
                            "tenantId": {"S": "t1"},
                            "slug": {"S": "clinica-acme"},
                            "name": {"S": "Clinica Acme"},
                        }
                    },
                }
            ]
        }

        # Execute
        response = lambda_handler(event, MagicMock(aws_request_id="req-456"))

        # Verify
        assert response["status"] == "success"
        assert mock_s3.put_object.called, "put_object was not called"
        assert (
            mock_cloudfront.create_invalidation.called
        ), "create_invalidation was not called"


def test_profile_baker_skip_no_slug_or_id():
    mock_s3 = MagicMock()
    mock_dynamodb = MagicMock()

    with patch("profile_baker.handler.s3", mock_s3), patch(
        "profile_baker.handler.dynamodb", mock_dynamodb
    ):
        # Event with neither providerId nor tenantId (unlikely, but for safety)
        event = {
            "Records": [
                {
                    "eventName": "MODIFY",
                    "dynamodb": {"NewImage": {"randomField": {"S": "nothing"}}},
                }
            ]
        }

        response = lambda_handler(event, {})
        assert response["status"] == "success"
        mock_s3.put_object.assert_not_called()


def test_profile_baker_provider_profession_in_seo():
    """Provider with a profession should have it reflected in baked SEO title."""
    mock_s3 = MagicMock()
    mock_cloudfront = MagicMock()
    mock_dynamodb = MagicMock()

    mock_s3.get_object.return_value = {
        "Body": MagicMock(
            read=lambda: b"<html><head><title>Original</title></head><body></body></html>"
        )
    }

    mock_tenants_table = MagicMock()
    mock_services_table = MagicMock()
    mock_providers_table = MagicMock()

    def get_table(name):
        if name == "Tenants":
            return mock_tenants_table
        if name == "Services":
            return mock_services_table
        if name == "Providers":
            return mock_providers_table
        return MagicMock()

    mock_dynamodb.Table.side_effect = get_table
    mock_tenants_table.get_item.return_value = {
        "Item": {
            "tenantId": "t1",
            "settings": json.dumps({"widgetConfig": {"primaryColor": "#3b82f6"}}),
        }
    }
    mock_services_table.scan.return_value = {"Items": []}
    mock_providers_table.scan.return_value = {"Items": []}

    with patch("profile_baker.handler.s3", mock_s3), patch(
        "profile_baker.handler.cloudfront", mock_cloudfront
    ), patch("profile_baker.handler.dynamodb", mock_dynamodb):

        event = {
            "Records": [
                {
                    "eventName": "INSERT",
                    "dynamodb": {
                        "NewImage": {
                            "tenantId": {"S": "t1"},
                            "providerId": {"S": "p1"},
                            "slug": {"S": "dr-mario"},
                            "name": {"S": "Dr. Mario"},
                            "bio": {"S": "Especialista en psicología"},
                            "photoUrl": {"S": "http://image.jpg"},
                            "profession": {"S": "Psicólogo"},
                        }
                    },
                }
            ]
        }

        response = lambda_handler(event, MagicMock(aws_request_id="req-789"))
        assert response["status"] == "success"

        _, kwargs = mock_s3.put_object.call_args
        uploaded_html = kwargs["Body"].decode("utf-8")

        # Profession should appear in the SEO title
        assert "Psicólogo" in uploaded_html
        assert "Dr. Mario — Psicólogo" in uploaded_html
        # preselectedProviderId should be set for provider pages
        assert '"preselectedProviderId": "p1"' in uploaded_html
