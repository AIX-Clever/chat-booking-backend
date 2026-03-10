"""Unit tests for twilio_connect Lambda handler."""
import json
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_SECRET = {
    "account_sid": "ACmaster",
    "auth_token": "master_token",
    "api_key": "SK_TEST",
    "api_secret": "secret",
    "phone_number": "whatsapp:+14155238886",
    "connected_app_sid": "CA_TEST_SID",
    "connected_app_secret": "CA_TEST_SECRET",
}

GOOD_EVENT = {
    "queryStringParameters": {
        "code": "AUTH_CODE_123",
        "state": "tenant-abc",
    }
}


def _make_mock_urlopen(responses: list):
    """Returns a context-manager mock for multiple sequential urlopen calls."""
    mocks = []
    for payload in responses:
        m = MagicMock()
        m.__enter__ = lambda s, p=payload: s
        m.__exit__ = MagicMock(return_value=False)
        m.read.return_value = json.dumps(p).encode()
        mocks.append(m)
    side_effect_iter = iter(mocks)

    def _open(_req):
        return next(side_effect_iter)

    return _open


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTwilioConnectHandler:

    @patch("backend.twilio_connect.handler.DynamoDBTenantRepository")
    @patch("backend.twilio_connect.handler.urllib.request.urlopen")
    @patch("backend.twilio_connect.handler.boto3.client")
    def test_successful_connection(self, mock_boto_client, mock_urlopen, mock_repo_cls):
        """Full happy path: code exchange, sub-account fetch, phone fetch, DynamoDB save."""
        import importlib
        import backend.twilio_connect.handler as h
        importlib.reload(h)  # reset module-level cache

        # Secrets Manager
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": json.dumps(SAMPLE_SECRET)}
        mock_boto_client.return_value = mock_sm

        # urlopen responses: token, sub-account, phone numbers
        mock_urlopen.side_effect = _make_mock_urlopen([
            {"account_sid": "AC_SUB", "access_token": "tok"},        # token exchange
            {"auth_token": "sub_token"},                               # sub-account data
            {"incoming_phone_numbers": [{"phone_number": "+56991234567"}]},  # phone list
        ])

        # DynamoDB tenant
        mock_tenant = MagicMock()
        mock_tenant.settings = {}
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = mock_tenant
        mock_repo_cls.return_value = mock_repo

        result = h.lambda_handler(GOOD_EVENT, {})

        assert result["statusCode"] == 302
        assert "connected=true" in result["headers"]["Location"]
        # Verify credentials were saved
        mock_repo.save.assert_called_once()
        saved_settings = mock_tenant.settings
        assert saved_settings["twilio_account_sid"] == "AC_SUB"
        assert saved_settings["twilio_whatsapp_number"] == "whatsapp:+56991234567"

    @patch("backend.twilio_connect.handler.DynamoDBTenantRepository")
    @patch("backend.twilio_connect.handler.urllib.request.urlopen")
    @patch("backend.twilio_connect.handler.boto3.client")
    def test_missing_code_redirects_to_error(self, mock_boto_client, mock_urlopen, mock_repo_cls):
        """Missing 'code' param should redirect to error URL."""
        import backend.twilio_connect.handler as h
        bad_event = {"queryStringParameters": {"state": "tenant-abc"}}
        result = h.lambda_handler(bad_event, {})
        assert result["statusCode"] == 302
        assert "error=true" in result["headers"]["Location"]
        mock_urlopen.assert_not_called()

    @patch("backend.twilio_connect.handler.DynamoDBTenantRepository")
    @patch("backend.twilio_connect.handler.urllib.request.urlopen")
    @patch("backend.twilio_connect.handler.boto3.client")
    def test_missing_state_redirects_to_error(self, mock_boto_client, mock_urlopen, mock_repo_cls):
        """Missing 'state' (tenantId) should redirect to error URL."""
        import backend.twilio_connect.handler as h
        bad_event = {"queryStringParameters": {"code": "CODE_123"}}
        result = h.lambda_handler(bad_event, {})
        assert result["statusCode"] == 302
        assert "error=true" in result["headers"]["Location"]

    @patch("backend.twilio_connect.handler.DynamoDBTenantRepository")
    @patch("backend.twilio_connect.handler.urllib.request.urlopen")
    @patch("backend.twilio_connect.handler.boto3.client")
    def test_tenant_not_found_redirects_to_error(self, mock_boto_client, mock_urlopen, mock_repo_cls):
        """If tenant doesn't exist in DB, redirect to error URL."""
        import importlib
        import backend.twilio_connect.handler as h
        importlib.reload(h)

        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": json.dumps(SAMPLE_SECRET)}
        mock_boto_client.return_value = mock_sm

        mock_urlopen.side_effect = _make_mock_urlopen([
            {"account_sid": "AC_SUB", "access_token": "tok"},
            {"auth_token": "sub_token"},
            {"incoming_phone_numbers": []},
        ])

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        result = h.lambda_handler(GOOD_EVENT, {})
        assert result["statusCode"] == 302
        assert "error=true" in result["headers"]["Location"]

    @patch("backend.twilio_connect.handler.DynamoDBTenantRepository")
    @patch("backend.twilio_connect.handler.urllib.request.urlopen")
    @patch("backend.twilio_connect.handler.boto3.client")
    def test_phone_number_already_formatted(self, mock_boto_client, mock_urlopen, mock_repo_cls):
        """If the phone already has 'whatsapp:' prefix it should not be doubled."""
        import importlib
        import backend.twilio_connect.handler as h
        importlib.reload(h)

        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": json.dumps(SAMPLE_SECRET)}
        mock_boto_client.return_value = mock_sm

        mock_urlopen.side_effect = _make_mock_urlopen([
            {"account_sid": "AC_SUB", "access_token": "tok"},
            {"auth_token": "sub_token"},
            {"incoming_phone_numbers": [{"phone_number": "whatsapp:+56991234567"}]},
        ])

        mock_tenant = MagicMock()
        mock_tenant.settings = {}
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = mock_tenant
        mock_repo_cls.return_value = mock_repo

        h.lambda_handler(GOOD_EVENT, {})
        assert mock_tenant.settings["twilio_whatsapp_number"] == "whatsapp:+56991234567"
