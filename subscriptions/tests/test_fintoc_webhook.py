import json
import os
import unittest
from importlib import import_module
from unittest.mock import patch

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


def _module():
    return import_module("subscriptions.handlers.fintoc_webhook")


class TestFintocWebhook(unittest.TestCase):
    @patch(
        "subscriptions.handlers.fintoc_webhook._sync_tenant_plan_and_status"
    )
    @patch("subscriptions.handlers.fintoc_webhook.SUBSCRIPTIONS_TABLE")
    def test_movement_created_matches_by_intent_id(
        self, mock_table, mock_sync_tenant
    ):
        mock_table.query.return_value = {
            "Items": [
                {
                    "tenantId": "tenant-123",
                    "subscriptionId": "li_123",
                    "status": "PENDING",
                    "planId": "pro",
                    "mpPreapprovalId": "li_123",
                },
                {
                    "tenantId": "tenant-123",
                    "subscriptionId": "CURRENT",
                    "status": "PENDING",
                    "planId": "pro",
                    "mpPreapprovalId": "li_123",
                },
            ]
        }

        event = {
            "headers": {},
            "body": json.dumps(
                {
                    "type": "movement.created",
                    "data": {
                        "id": "mov_123",
                        "account_id": "acc_001",
                        "amount": 9990,
                        "subscription_intent_id": "li_123",
                    },
                }
            ),
        }

        response = _module().lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "OK")
        self.assertEqual(mock_table.update_item.call_count, 2)
        mock_sync_tenant.assert_called_once_with("tenant-123", "pro")

    @patch(
        "subscriptions.handlers.fintoc_webhook._sync_tenant_plan_and_status"
    )
    @patch("subscriptions.handlers.fintoc_webhook.SUBSCRIPTIONS_TABLE")
    def test_movement_created_uses_tenant_fallback_from_description(
        self, mock_table, mock_sync_tenant
    ):
        mock_table.query.return_value = {"Items": []}
        mock_table.get_item.return_value = {
            "Item": {
                "tenantId": "tenant-xyz",
                "subscriptionId": "CURRENT",
                "status": "PENDING",
                "planId": "lite",
                "mpPreapprovalId": "li_xyz",
            }
        }

        event = {
            "headers": {},
            "body": json.dumps(
                {
                    "type": "movement.created",
                    "data": {
                        "id": "mov_456",
                        "account_id": "acc_002",
                        "amount": 9990,
                        "description": "tenant_id:tenant-xyz monthly payment",
                    },
                }
            ),
        }

        response = _module().lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "OK")
        self.assertEqual(mock_table.update_item.call_count, 1)
        mock_sync_tenant.assert_called_once_with("tenant-xyz", "lite")

    @patch("subscriptions.handlers.fintoc_webhook.SUBSCRIPTIONS_TABLE")
    def test_movement_created_records_unmatched_movement(self, mock_table):
        mock_table.query.return_value = {"Items": []}
        mock_table.get_item.return_value = {}

        event = {
            "headers": {},
            "body": json.dumps(
                {
                    "type": "movement.created",
                    "data": {
                        "id": "mov_unmatched_1",
                        "account_id": "acc_404",
                        "amount": 12000,
                        "description": "payment without usable refs",
                    },
                }
            ),
        }

        response = _module().lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "UNMATCHED_RECORDED")
        self.assertEqual(mock_table.put_item.call_count, 1)

        put_item_args = mock_table.put_item.call_args.kwargs["Item"]
        self.assertEqual(put_item_args["tenantId"], "UNMATCHED")
        self.assertEqual(put_item_args["status"], "UNMATCHED")
        self.assertTrue(
            put_item_args["subscriptionId"].startswith("MOVEMENT#")
        )


if __name__ == "__main__":
    unittest.main()
