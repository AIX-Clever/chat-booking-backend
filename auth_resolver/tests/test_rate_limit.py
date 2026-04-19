"""
Tests for _check_rate_limit() in auth_resolver/handler.py

The rate limiter is tested in isolation using importlib + sys.path
to avoid the dependency on the local `service` module which requires
full DynamoDB + Cognito setup.
"""
import os
import sys
import importlib
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ["TENANT_USAGE_TABLE"] = "test-usage-table"
os.environ["RATE_LIMIT_MAX"] = "100"
os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "60"

# ---------------------------------------------------------------------------
# Extract _check_rate_limit without importing the full handler (which needs
# the local `service` module that has DynamoDB/Cognito deps at import time).
# ---------------------------------------------------------------------------
_HANDLER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "handler.py"
)


def _load_check_rate_limit():
    """Load _check_rate_limit by exec-ing the function definition only."""
    import hashlib
    import time

    # We compile _check_rate_limit's source directly.
    # Instead we just define a convenience wrapper that duplicates the logic
    # for testability, OR we patch the module imports before loading.
    # Simplest approach: use compile + exec on the isolated function after
    # patching its two dependencies (os.environ already set above).

    # Patch module-level imports that would fail
    import types
    import boto3  # noqa: actual dep we want to mock per test

    # Load the function by importing via modified sys.path
    auth_dir = os.path.join(os.path.dirname(__file__), "..")
    if auth_dir not in sys.path:
        sys.path.insert(0, auth_dir)

    # Patch `service` before import to avoid DynamoDB connection
    fake_service_mod = types.ModuleType("service")
    fake_auth_service_cls = Mock()
    fake_service_mod.AuthenticationService = fake_auth_service_cls
    sys.modules.setdefault("service", fake_service_mod)

    import importlib.util
    spec = importlib.util.spec_from_file_location("_handler_rl", _HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    with patch("shared.infrastructure.dynamodb_repositories.DynamoDBApiKeyRepository"), \
         patch("shared.infrastructure.dynamodb_repositories.DynamoDBTenantRepository"), \
         patch("shared.utils.Logger"):
        spec.loader.exec_module(mod)
    return mod._check_rate_limit


_check_rate_limit = _load_check_rate_limit()


class TestCheckRateLimit(unittest.TestCase):

    def _table_mock(self, count: int):
        tbl = Mock()
        tbl.update_item.return_value = {"Attributes": {"count": count}}
        return tbl

    @patch("boto3.resource")
    def test_within_limit_returns_true(self, mock_boto):
        """Requests within RATE_LIMIT_MAX should be allowed"""
        mock_boto.return_value.Table.return_value = self._table_mock(50)
        result = _check_rate_limit("sk_test_key")
        self.assertTrue(result)

    @patch("boto3.resource")
    def test_exactly_at_limit_returns_true(self, mock_boto):
        """Requests exactly at RATE_LIMIT_MAX should still be allowed"""
        mock_boto.return_value.Table.return_value = self._table_mock(100)
        result = _check_rate_limit("sk_test_key")
        self.assertTrue(result)

    @patch("boto3.resource")
    def test_over_limit_returns_false(self, mock_boto):
        """Requests over RATE_LIMIT_MAX should be throttled"""
        mock_boto.return_value.Table.return_value = self._table_mock(101)
        result = _check_rate_limit("sk_test_key")
        self.assertFalse(result)

    @patch("boto3.resource")
    def test_dynamodb_failure_fails_open(self, mock_boto):
        """If DynamoDB raises an error, rate limiter must fail open (allow traffic)"""
        mock_boto.return_value.Table.return_value.update_item.side_effect = Exception(
            "DynamoDB service unavailable"
        )
        result = _check_rate_limit("sk_test_key")
        self.assertTrue(result)  # Must fail open

    def test_no_table_env_var_fails_open(self):
        """If TENANT_USAGE_TABLE is not set, rate limiter is disabled"""
        with patch.dict(os.environ, {"TENANT_USAGE_TABLE": ""}):
            result = _check_rate_limit("sk_test_key")
        self.assertTrue(result)

    @patch("boto3.resource")
    def test_raw_api_key_not_stored_in_dynamodb(self, mock_boto):
        """The actual API key value must NOT appear as the DynamoDB primary key"""
        table_mock = self._table_mock(1)
        mock_boto.return_value.Table.return_value = table_mock

        raw_key = "sk_live_supersecret_12345"
        _check_rate_limit(raw_key)

        call_args = table_mock.update_item.call_args
        pk_used = call_args.kwargs["Key"]["pk"]

        self.assertTrue(pk_used.startswith("rate#"))
        self.assertNotIn(raw_key, pk_used)
        self.assertNotIn("supersecret", pk_used)

    @patch("boto3.resource")
    def test_different_keys_produce_different_pk(self, mock_boto):
        """Two different API keys must map to different DynamoDB PKs"""
        pks_used = []

        def capture_pk(**kwargs):
            pks_used.append(kwargs["Key"]["pk"])
            return {"Attributes": {"count": 1}}

        mock_boto.return_value.Table.return_value.update_item.side_effect = capture_pk

        _check_rate_limit("sk_key_aaaa")
        _check_rate_limit("sk_key_bbbb")

        self.assertEqual(len(pks_used), 2)
        self.assertNotEqual(pks_used[0], pks_used[1])

    @patch("boto3.resource")
    def test_same_key_produces_same_pk(self, mock_boto):
        """The same API key must always map to the same DynamoDB PK (deterministic)"""
        pks_used = []

        def capture_pk(**kwargs):
            pks_used.append(kwargs["Key"]["pk"])
            return {"Attributes": {"count": 1}}

        mock_boto.return_value.Table.return_value.update_item.side_effect = capture_pk

        _check_rate_limit("sk_same_key")
        _check_rate_limit("sk_same_key")

        self.assertEqual(pks_used[0], pks_used[1])


if __name__ == "__main__":
    unittest.main()
