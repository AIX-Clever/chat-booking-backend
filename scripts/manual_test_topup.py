"""
Manual integration test for topupWhatsappQuota Lambda.
Requires: live AWS credentials + deployed Lambda (dev environment).

Usage:
    python scripts/manual_test_topup.py [dev|qa|prod] [packageId] [paymentMethod]

    python scripts/manual_test_topup.py dev starter transfer
    python scripts/manual_test_topup.py dev standard mercadopago
"""

import json
import sys
import os
import boto3

ENV = sys.argv[1] if len(sys.argv) > 1 else "dev"
PACKAGE_ID = sys.argv[2] if len(sys.argv) > 2 else "starter"
PAYMENT_METHOD = sys.argv[3] if len(sys.argv) > 3 else "transfer"
REGION = "us-east-1"

# Use a real tenantId from the environment (never trusting frontend)
TEST_TENANT_ID = os.environ.get("TEST_TENANT_ID", "test-tenant-123")
TEST_BACK_URL = "https://admin.holalucia.cl/settings?tab=whatsapp"


def find_lambda(name_fragment: str) -> str | None:
    client = boto3.client("lambda", region_name=REGION)
    paginator = client.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            if name_fragment in fn["FunctionName"] and ENV in fn["FunctionName"]:
                return fn["FunctionName"]
    return None


def invoke_topup(function_name: str, package_id: str, payment_method: str) -> dict:
    """Simulate the AppSync event that the Lambda receives."""
    event = {
        "arguments": {
            "packageId": package_id,
            "paymentMethod": payment_method,
            "backUrl": TEST_BACK_URL,
        },
        "info": {
            "fieldName": "topupWhatsappQuota",
        },
        # tenantId comes from Cognito identity — never from arguments
        "identity": {
            "claims": {
                "custom:tenantId": TEST_TENANT_ID,
                "sub": "mock-cognito-sub-123",
            }
        },
    }

    client = boto3.client("lambda", region_name=REGION)
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )
    payload = json.loads(response["Payload"].read().decode("utf-8"))
    return payload


def test_invalid_package(function_name: str):
    """Should return a ValueError for unknown package."""
    print("\n[TEST] Invalid packageId → should fail gracefully")
    event = {
        "arguments": {"packageId": "nonexistent", "paymentMethod": "transfer", "backUrl": TEST_BACK_URL},
        "info": {"fieldName": "topupWhatsappQuota"},
        "identity": {"claims": {"custom:tenantId": TEST_TENANT_ID}},
    }
    client = boto3.client("lambda", region_name=REGION)
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )
    payload = json.loads(response["Payload"].read().decode("utf-8"))
    if "errorMessage" in payload or "errorType" in payload:
        print(f"  ✅ Correctly rejected: {payload.get('errorMessage', payload)}")
    else:
        print(f"  ❌ Should have rejected invalid package. Got: {payload}")


def test_missing_tenant(function_name: str):
    """Should fail when tenantId is missing from identity (security check)."""
    print("\n[TEST] Missing tenantId in identity → should fail")
    event = {
        "arguments": {"packageId": "starter", "paymentMethod": "transfer", "backUrl": TEST_BACK_URL},
        "info": {"fieldName": "topupWhatsappQuota"},
        "identity": {},  # no claims
    }
    client = boto3.client("lambda", region_name=REGION)
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )
    payload = json.loads(response["Payload"].read().decode("utf-8"))
    if "errorMessage" in payload or "errorType" in payload:
        print(f"  ✅ Correctly rejected: {payload.get('errorMessage', payload)}")
    else:
        print(f"  ❌ Should have rejected missing tenant. Got: {payload}")


def main():
    print(f"=== manual_test_topup — env={ENV} package={PACKAGE_ID} method={PAYMENT_METHOD} ===")
    print(f"    tenant (from env): {TEST_TENANT_ID}")

    print("\nFinding TopupWhatsappQuotaFunction...")
    function_name = find_lambda("TopupWhatsappQuota")
    if not function_name:
        print(f"❌ Could not find TopupWhatsappQuotaFunction in {ENV}. Is it deployed?")
        sys.exit(1)
    print(f"  Found: {function_name}")

    # --- Happy path ---
    print(f"\n[TEST] Happy path — package={PACKAGE_ID}, method={PAYMENT_METHOD}")
    payload = invoke_topup(function_name, PACKAGE_ID, PAYMENT_METHOD)
    print(f"  Response: {json.dumps(payload, indent=2)}")

    if "errorMessage" in payload or "errorType" in payload:
        print(f"  ❌ Unexpected error: {payload.get('errorMessage')}")
    elif payload.get("topupId") and payload.get("message"):
        print(f"  ✅ topupId: {payload['topupId']}")
        print(f"  ✅ message: {payload['message']}")
        if PAYMENT_METHOD == "transfer":
            print("  ℹ️  initPoint empty (transfer) — correct")
        else:
            print(f"  ✅ initPoint: {payload.get('initPoint', '')[:60]}...")
    else:
        print(f"  ❌ Unexpected response shape: {payload}")

    # --- Security / validation tests ---
    test_invalid_package(function_name)
    test_missing_tenant(function_name)

    print("\n=== Done ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n🚨 Error: {e}")
        if "ExpiredToken" in str(e):
            print("   AWS token expired — run `aws sso login` and retry.")
        sys.exit(1)
