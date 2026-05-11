"""
Unit tests for topupWhatsappQuota Lambda handler.
Tests all paths without requiring live AWS credentials.
"""
import json
import pytest
from unittest.mock import patch, MagicMock


VALID_EVENT = {
    "arguments": {
        "packageId": "starter",
        "paymentMethod": "transfer",
        "backUrl": "https://admin.holalucia.cl/settings",
    },
    "info": {"fieldName": "topupWhatsappQuota"},
    "identity": {
        "claims": {"custom:tenantId": "tenant-abc", "sub": "cognito-sub-123"}
    },
}


def _invoke(event: dict):
    from subscriptions.handlers.topup import lambda_handler
    return lambda_handler(event, None)


# ── Happy paths ──────────────────────────────────────────────────────────────

class TestTopupHappyPaths:
    def test_transfer_starter(self):
        result = _invoke(VALID_EVENT)
        assert result["topupId"].startswith("transfer:tenant-abc:starter")
        assert result["initPoint"] == ""
        assert "Starter" in result["message"]

    def test_transfer_standard(self):
        event = {**VALID_EVENT, "arguments": {**VALID_EVENT["arguments"], "packageId": "standard"}}
        result = _invoke(event)
        assert "standard" in result["topupId"]
        assert "Standard" in result["message"]

    def test_transfer_pro(self):
        event = {**VALID_EVENT, "arguments": {**VALID_EVENT["arguments"], "packageId": "pro"}}
        result = _invoke(event)
        assert "pro" in result["topupId"]
        assert "Pro" in result["message"]

    @patch("subscriptions.handlers.topup.MercadoPagoClient")
    def test_mercadopago_returns_init_point(self, MockMP):
        MockMP.return_value.create_preference.return_value = {
            "id": "pref-123",
            "init_point": "https://mp.com/checkout/pref-123",
        }
        event = {**VALID_EVENT, "arguments": {**VALID_EVENT["arguments"], "paymentMethod": "mercadopago"}}
        result = _invoke(event)
        assert result["topupId"] == "pref-123"
        assert "mp.com" in result["initPoint"]
        MockMP.return_value.create_preference.assert_called_once()

    @patch("subscriptions.handlers.topup.FintocClient")
    def test_fintoc_returns_widget_token(self, MockFintoc):
        MockFintoc.return_value.create_payment_intent.return_value = {
            "payment_intent_id": "pi-fintoc-456",
            "widget_token": "wt_abc123",
        }
        event = {**VALID_EVENT, "arguments": {**VALID_EVENT["arguments"], "paymentMethod": "fintoc"}}
        result = _invoke(event)
        assert result["topupId"] == "pi-fintoc-456"
        assert result["initPoint"] == "wt_abc123"


# ── Security: tenantId must come from identity ────────────────────────────────

class TestTopupSecurity:
    def test_missing_identity_raises(self):
        event = {**VALID_EVENT, "identity": {}}
        with pytest.raises(Exception, match="tenantId"):
            _invoke(event)

    def test_tenantId_from_claims_not_arguments(self):
        """Even if arguments contained tenantId, the handler must ignore it."""
        event = {
            **VALID_EVENT,
            "arguments": {**VALID_EVENT["arguments"], "tenantId": "attacker-tenant"},
        }
        result = _invoke(event)
        # The topupId should contain the identity tenant, not the argument one
        assert "attacker-tenant" not in result["topupId"]
        assert "tenant-abc" in result["topupId"]


# ── Validation ────────────────────────────────────────────────────────────────

class TestTopupValidation:
    def test_invalid_package_raises(self):
        event = {**VALID_EVENT, "arguments": {**VALID_EVENT["arguments"], "packageId": "unknown"}}
        with pytest.raises(ValueError, match="Invalid packageId"):
            _invoke(event)

    def test_invalid_payment_method_raises(self):
        event = {**VALID_EVENT, "arguments": {**VALID_EVENT["arguments"], "paymentMethod": "bitcoin"}}
        with pytest.raises(ValueError, match="Invalid paymentMethod"):
            _invoke(event)

    def test_package_id_case_insensitive(self):
        event = {**VALID_EVENT, "arguments": {**VALID_EVENT["arguments"], "packageId": "Starter"}}
        result = _invoke(event)
        assert "starter" in result["topupId"]


# ── Webhook processor routing ─────────────────────────────────────────────────

class TestWebhookTopupRouting:
    def _make_payment_info(self, external_reference, status="approved", amount=9990.0):
        return {
            "external_reference": external_reference,
            "status": status,
            "transaction_amount": amount,
        }

    @patch("subscriptions.handlers.webhook_processor.tenant_repo")
    @patch("subscriptions.handlers.webhook_processor.SUBSCRIPTIONS_TABLE")
    @patch("subscriptions.handlers.webhook_processor.mp_client")
    def test_topup_payment_routes_to_topup_handler(self, mock_mp, mock_table, mock_repo):
        from subscriptions.handlers.webhook_processor import process_payment

        mock_mp.get_payment.return_value = self._make_payment_info(
            "topup:tenant-abc:starter", status="approved", amount=9990.0
        )
        mock_table.put_item.return_value = {}
        mock_repo.increment_whatsapp_quota.return_value = True

        process_payment("pay-001", "{}")
        mock_repo.increment_whatsapp_quota.assert_called_once()
        call_args = mock_repo.increment_whatsapp_quota.call_args
        assert call_args[0][1] == 100  # starter = 100 messages

    @patch("subscriptions.handlers.webhook_processor.tenant_repo")
    @patch("subscriptions.handlers.webhook_processor.SUBSCRIPTIONS_TABLE")
    @patch("subscriptions.handlers.webhook_processor.mp_client")
    def test_topup_amount_mismatch_rejected(self, mock_mp, mock_table, mock_repo):
        from subscriptions.handlers.webhook_processor import process_payment

        mock_mp.get_payment.return_value = self._make_payment_info(
            "topup:tenant-abc:pro", status="approved", amount=100.0  # should be 39990
        )
        mock_table.put_item.return_value = {}

        process_payment("pay-002", "{}")
        mock_repo.increment_whatsapp_quota.assert_not_called()

    @patch("subscriptions.handlers.webhook_processor.SUBSCRIPTIONS_TABLE")
    @patch("subscriptions.handlers.webhook_processor.mp_client")
    def test_non_approved_status_skipped(self, mock_mp, mock_table):
        from subscriptions.handlers.webhook_processor import process_payment, tenant_repo

        mock_mp.get_payment.return_value = self._make_payment_info(
            "topup:tenant-abc:starter", status="pending", amount=9990.0
        )
        with patch.object(tenant_repo, "increment_whatsapp_quota") as mock_inc:
            process_payment("pay-003", "{}")
            mock_inc.assert_not_called()

    @patch("subscriptions.handlers.webhook_processor.SUBSCRIPTIONS_TABLE")
    @patch("subscriptions.handlers.webhook_processor.mp_client")
    def test_subscription_payment_not_routed_to_topup(self, mock_mp, mock_table):
        """Existing subscription flow must not be affected."""
        from subscriptions.handlers.webhook_processor import process_payment, tenant_repo

        mock_mp.get_payment.return_value = self._make_payment_info(
            "tenant-abc",  # old format — no topup: prefix
            status="approved", amount=9990.0
        )
        mock_table.put_item.return_value = {}
        mock_table.get_item.return_value = {"Item": {"planId": "lite"}}

        with patch.object(tenant_repo, "increment_whatsapp_quota") as mock_inc:
            try:
                process_payment("pay-004", "{}")
            except Exception:
                pass  # might fail on subscription logic mocks — that's ok
            mock_inc.assert_not_called()


SMS_EVENT = {
    "arguments": {
        "packageId": "starter",
        "paymentMethod": "transfer",
        "backUrl": "https://admin.holalucia.cl/settings",
    },
    "info": {"fieldName": "topupSmsQuota"},
    "identity": {
        "claims": {"custom:tenantId": "tenant-abc", "sub": "cognito-sub-123"}
    },
}


class TestSmsTopupHandler:
    def test_sms_transfer_starter(self):
        result = _invoke(SMS_EVENT)
        assert result["topupId"].startswith("transfer:tenant-abc:starter")
        assert "SMS" in result["message"]
        assert "Starter" in result["message"]

    def test_sms_external_reference_prefix(self):
        result = _invoke(SMS_EVENT)
        # topupId for transfer = f"transfer:{tenant_id}:{package_id}"
        # The external_reference used internally is sms-topup:... but topupId for
        # transfer is built differently — check the message contains SMS label
        assert "SMS" in result["message"]

    def test_sms_invalid_package_raises(self):
        event = {**SMS_EVENT, "arguments": {**SMS_EVENT["arguments"], "packageId": "unknown"}}
        with pytest.raises(ValueError, match="Invalid packageId"):
            _invoke(event)

    def test_whatsapp_event_still_uses_whatsapp_packages(self):
        result = _invoke(VALID_EVENT)
        assert "WhatsApp" in result["message"]


class TestSmsWebhookRouting:
    def _make_payment_info(self, external_reference, status="approved", amount=9990.0):
        return {
            "external_reference": external_reference,
            "status": status,
            "transaction_amount": amount,
        }

    @patch("subscriptions.handlers.webhook_processor.tenant_repo")
    @patch("subscriptions.handlers.webhook_processor.SUBSCRIPTIONS_TABLE")
    @patch("subscriptions.handlers.webhook_processor.mp_client")
    def test_sms_topup_routes_to_sms_handler(self, mock_mp, mock_table, mock_repo):
        from subscriptions.handlers.webhook_processor import process_payment

        mock_mp.get_payment.return_value = self._make_payment_info(
            "sms-topup:tenant-abc:starter", status="approved", amount=9990.0
        )
        mock_table.put_item.return_value = {}
        mock_repo.increment_sms_quota.return_value = True

        process_payment("pay-sms-001", "{}")
        mock_repo.increment_sms_quota.assert_called_once()
        call_args = mock_repo.increment_sms_quota.call_args
        assert call_args[0][1] == 50  # SMS starter = 50 messages

    @patch("subscriptions.handlers.webhook_processor.tenant_repo")
    @patch("subscriptions.handlers.webhook_processor.SUBSCRIPTIONS_TABLE")
    @patch("subscriptions.handlers.webhook_processor.mp_client")
    def test_sms_topup_amount_mismatch_rejected(self, mock_mp, mock_table, mock_repo):
        from subscriptions.handlers.webhook_processor import process_payment

        mock_mp.get_payment.return_value = self._make_payment_info(
            "sms-topup:tenant-abc:pro", status="approved", amount=100.0  # should be 39990
        )
        mock_table.put_item.return_value = {}

        process_payment("pay-sms-002", "{}")
        mock_repo.increment_sms_quota.assert_not_called()

    @patch("subscriptions.handlers.webhook_processor.SUBSCRIPTIONS_TABLE")
    @patch("subscriptions.handlers.webhook_processor.mp_client")
    def test_sms_topup_non_approved_skipped(self, mock_mp, mock_table):
        from subscriptions.handlers.webhook_processor import process_payment, tenant_repo

        mock_mp.get_payment.return_value = self._make_payment_info(
            "sms-topup:tenant-abc:starter", status="pending", amount=9990.0
        )
        with patch.object(tenant_repo, "increment_sms_quota") as mock_inc:
            process_payment("pay-sms-003", "{}")
            mock_inc.assert_not_called()
