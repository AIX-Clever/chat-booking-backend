import json
import os
import re
from datetime import datetime, UTC

import boto3
from boto3.dynamodb.conditions import Key

from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.entities import SubscriptionStatus

dynamodb = boto3.resource("dynamodb")
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)

TENANT_REGEX = re.compile(
    r"(?:tenant_id|tenantId|tenant)\s*[:=#]\s*([A-Za-z0-9_-]+)"
)
INTENT_REGEX = re.compile(
    r"(?:subscription_intent_id|subscriptionIntentId|link_intent_id|"
    r"linkIntentId|intent|subscription)\s*[:=#]\s*([A-Za-z0-9_-]+)"
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _extract_refs_from_description(description: str) -> dict:
    refs = {"tenant_id": None, "intent_id": None}
    if not description:
        return refs

    tenant_match = TENANT_REGEX.search(description)
    if tenant_match:
        refs["tenant_id"] = tenant_match.group(1)

    intent_match = INTENT_REGEX.search(description)
    if intent_match:
        refs["intent_id"] = intent_match.group(1)

    return refs


def _extract_intent_candidates(
    data: dict, description_intent: str = None
) -> list:
    candidates = []
    direct_refs = [
        data.get("subscription_intent_id"),
        data.get("subscriptionIntentId"),
        data.get("link_intent_id"),
        data.get("linkIntentId"),
        data.get("intent_id"),
        data.get("intentId"),
        data.get("reference"),
    ]

    subscription_intent = data.get("subscription_intent", {})
    if isinstance(subscription_intent, dict):
        direct_refs.append(subscription_intent.get("id"))

    if description_intent:
        direct_refs.append(description_intent)

    for ref in direct_refs:
        if not ref or not isinstance(ref, str):
            continue
        cleaned = ref.strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    return candidates


def _query_subscription_by_preapproval(preapproval_id: str) -> list:
    response = SUBSCRIPTIONS_TABLE.query(
        IndexName="mpPreapprovalId-index",
        KeyConditionExpression=Key("mpPreapprovalId").eq(preapproval_id),
    )
    return response.get("Items", [])


def _find_subscription_for_movement(data: dict):
    description = data.get("description") or ""
    description_refs = _extract_refs_from_description(description)
    intent_candidates = _extract_intent_candidates(
        data, description_refs.get("intent_id")
    )

    for candidate in intent_candidates:
        items = _query_subscription_by_preapproval(candidate)
        if items:
            non_current = [
                item
                for item in items
                if item.get("subscriptionId") != "CURRENT"
            ]
            chosen = non_current[0] if non_current else items[0]
            return chosen, f"intent:{candidate}"

    tenant_from_description = description_refs.get("tenant_id")
    if tenant_from_description:
        current = SUBSCRIPTIONS_TABLE.get_item(
            Key={
                "tenantId": tenant_from_description,
                "subscriptionId": "CURRENT",
            }
        ).get("Item")
        if current:
            return current, f"tenant:{tenant_from_description}"

    return None, None


def _activate_subscription(tenant_id: str, subscription_id: str):
    SUBSCRIPTIONS_TABLE.update_item(
        Key={"tenantId": tenant_id, "subscriptionId": subscription_id},
        UpdateExpression="SET #s = :s, updatedAt = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": SubscriptionStatus.AUTHORIZED.value,
            ":u": _iso_now(),
        },
    )

    if subscription_id != "CURRENT":
        SUBSCRIPTIONS_TABLE.update_item(
            Key={"tenantId": tenant_id, "subscriptionId": "CURRENT"},
            UpdateExpression="SET #s = :s, updatedAt = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": SubscriptionStatus.AUTHORIZED.value,
                ":u": _iso_now(),
            },
        )


def _sync_tenant_plan_and_status(tenant_id: str, plan_id: str):
    try:
        from shared.infrastructure.dynamodb_repositories import (
            DynamoDBTenantRepository,
        )
        from shared.domain.entities import TenantPlan, TenantStatus

        repo = DynamoDBTenantRepository()
        tenant = repo.get_by_id(tenant_id)
        if not tenant:
            print(f"Tenant {tenant_id} not found for Fintoc activation sync.")
            return

        if plan_id and plan_id.upper() in TenantPlan._member_names_:
            tenant.plan = TenantPlan[plan_id.upper()]
        tenant.status = TenantStatus.ACTIVE
        repo.save(tenant)
        print(f"Tenant {tenant_id} activated from Fintoc webhook.")
    except Exception as err:
        print(f"Failed to sync tenant status/plan for {tenant_id}: {err}")


def _record_unmatched_movement(data: dict, reason: str):
    movement_id = data.get("id")
    if not movement_id:
        movement_id = (
            f"{data.get('account_id', 'unknown')}"
            f"#{data.get('amount', '0')}"
            f"#{abs(hash(data.get('description', '')))}"
        )

    SUBSCRIPTIONS_TABLE.put_item(
        Item={
            "tenantId": "UNMATCHED",
            "subscriptionId": f"MOVEMENT#{movement_id}",
            "status": "UNMATCHED",
            "provider": "FINTOC",
            "reason": reason,
            "rawData": json.dumps(data),
            "createdAt": _iso_now(),
            "updatedAt": _iso_now(),
        }
    )


def lambda_handler(event, context):
    try:
        fintoc_webhook_secret = os.environ.get("FINTOC_WEBHOOK_SECRET")
        signature_header = event.get("headers", {}).get(
            "Fintoc-Signature"
        ) or event.get("headers", {}).get("fintoc-signature")
        raw_body = event.get("body", "")

        print(f"Full Event: {json.dumps(event)}")

        if not signature_header or not fintoc_webhook_secret:
            print(
                "Missing signature header or webhook secret. "
                "Skipping verification for now (WARNING)."
            )
        else:
            try:
                from fintoc import WebhookSignature

                WebhookSignature.verify_header(
                    raw_body, signature_header, fintoc_webhook_secret
                )
                print("Webhook signature verified successfully.")
            except Exception as sig_err:
                print(f"Webhook signature verification failed: {sig_err}")
                return {"statusCode": 403, "body": "Invalid signature"}

        body = json.loads(raw_body)
        event_type = body.get("type")
        data = body.get("data", {})

        print(f"Received Fintoc Webhook: {event_type}")

        if event_type == "movement.created":
            account_id = data.get("account_id")
            amount = data.get("amount")
            description = data.get("description")
            print(
                f"Payment detected: {amount} CLP from account {account_id}, "
                f"description={description}"
            )

            matched_subscription, match_source = (
                _find_subscription_for_movement(data)
            )
            if not matched_subscription:
                print(
                    "No subscription match for movement.created. "
                    f"Recording as unmatched movement (account={account_id})."
                )
                _record_unmatched_movement(data, "No subscription match found")
                return {"statusCode": 200, "body": "UNMATCHED_RECORDED"}

            tenant_id = matched_subscription["tenantId"]
            sub_id = matched_subscription["subscriptionId"]
            current_status = matched_subscription.get("status")
            plan_id = matched_subscription.get("planId")

            if current_status == SubscriptionStatus.AUTHORIZED.value:
                print(
                    f"Subscription {sub_id} for tenant {tenant_id} "
                    f"already AUTHORIZED. source={match_source}"
                )
            else:
                print(
                    f"Matched movement to tenant={tenant_id}, "
                    f"subscription={sub_id}, source={match_source}"
                )
                _activate_subscription(tenant_id, sub_id)
                _sync_tenant_plan_and_status(tenant_id, plan_id)

        elif event_type == "subscription_intent.succeeded":
            intent_id = data.get("id")
            print(f"Subscription Intent Succeeded: {intent_id}")

            items = _query_subscription_by_preapproval(intent_id)
            if not items:
                print(
                    f"No subscription found for intent ID (GSI): {intent_id}"
                )
            else:
                for item in items:
                    tenant_id = item["tenantId"]
                    sub_id = item["subscriptionId"]
                    current_status = item.get("status")
                    plan_id = item.get("planId")

                    if current_status == SubscriptionStatus.AUTHORIZED.value:
                        print(
                            f"Subscription {sub_id} for tenant {tenant_id} "
                            "is already AUTHORIZED. Skipping."
                        )
                        continue

                    print(
                        f"Activating subscription {sub_id} "
                        f"for tenant {tenant_id}"
                    )
                    _activate_subscription(tenant_id, sub_id)
                    _sync_tenant_plan_and_status(tenant_id, plan_id)
                    print(f"Successfully activated tenant {tenant_id}")

        elif event_type == "link.created":
            link_token = data.get("link_token")
            holder_id = data.get("holder_id")
            username = data.get("username")

            print(
                f"New Bank Account Connected: {username} ({holder_id}) "
                f"link_token={link_token}"
            )

        return {"statusCode": 200, "body": "OK"}

    except Exception as err:
        print(f"Error processing Fintoc webhook: {err}")
        return {"statusCode": 500, "body": str(err)}
