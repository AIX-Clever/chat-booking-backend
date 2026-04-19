"""
twilio_connect/handler.py

OAuth callback handler for Twilio Embedded Signup.

Flow:
1. User clicks "Connect WhatsApp Business" in the dashboard.
2. Dashboard redirects to Twilio's OAuth URL with state=tenantId.
3. Twilio calls this Lambda with ?code=XXX&state=tenantId after the user completes the OAuth.
4. This handler exchanges the code for the sub-account SID, auth token and phone number.
5. Persists these credentials in the Tenant's settings in DynamoDB.
6. Redirects the user back to the dashboard settings page.
"""

import json
import os
import urllib.request
import urllib.parse
import base64
import boto3
from urllib.parse import parse_qs

from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.domain.entities import TenantId
from shared.utils import Logger

logger = Logger()

# --- Configuration ---
SECRETS_NAME = os.environ.get("TWILIO_MASTER_SECRET_NAME", "prod/twilio/master")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://admin.holalucia.cl/settings?tab=whatsapp&connected=true")
DASHBOARD_ERROR_URL = os.environ.get("DASHBOARD_URL", "https://admin.holalucia.cl/settings?tab=whatsapp&error=true")

_secrets_cache: dict | None = None

def _get_master_credentials() -> dict:
    """Fetches and caches Twilio master credentials from AWS Secrets Manager."""
    global _secrets_cache
    if _secrets_cache:
        return _secrets_cache
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=SECRETS_NAME)
    _secrets_cache = json.loads(response["SecretString"])
    return _secrets_cache


def _exchange_code_for_token(code: str) -> dict:
    """
    Exchanges an OAuth authorization code for Twilio sub-account credentials.
    Returns a dict with: account_sid, auth_token, phone_number.
    """
    creds = _get_master_credentials()
    connected_app_sid = creds.get("connected_app_sid", os.environ.get("TWILIO_CONNECTED_APP_SID"))
    connected_app_secret = creds.get("connected_app_secret", os.environ.get("TWILIO_CONNECTED_APP_SECRET"))

    if not connected_app_sid or not connected_app_secret:
        raise ValueError("Missing Twilio Connected App credentials")

    # Step 1: Exchange code for access token
    token_url = "https://oauth.twilio.com/v1/token"
    data = urllib.parse.urlencode({
        "code": code,
        "grant_type": "authorization_code",
        "client_id": connected_app_sid,
    }).encode("utf-8")

    auth_str = f"{connected_app_sid}:{connected_app_secret}"
    auth_header = "Basic " + base64.b64encode(auth_str.encode()).decode()

    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read().decode())

    # token_data should have: access_token, sub_account_sid, etc.
    sub_account_sid = token_data.get("account_sid") or token_data.get("sub_account_sid")
    access_token = token_data.get("access_token")

    if not sub_account_sid or not access_token:
        raise ValueError(f"Unexpected token response: {token_data}")

    # Step 2: Use master credentials to get sub-account auth token
    master_creds = _get_master_credentials()
    master_sid = master_creds["account_sid"]
    master_auth = master_creds["auth_token"]

    subaccount_url = f"https://api.twilio.com/2010-04-01/Accounts/{sub_account_sid}.json"
    auth_str_master = f"{master_sid}:{master_auth}"
    auth_header_master = "Basic " + base64.b64encode(auth_str_master.encode()).decode()

    req2 = urllib.request.Request(subaccount_url, method="GET")
    req2.add_header("Authorization", auth_header_master)
    with urllib.request.urlopen(req2) as resp2:
        account_data = json.loads(resp2.read().decode())

    # Step 3: Fetch the incoming WhatsApp phone number for the sub-account
    phone_number = _fetch_whatsapp_number(sub_account_sid, account_data.get("auth_token", ""))

    return {
        "twilio_account_sid": sub_account_sid,
        "twilio_auth_token": account_data.get("auth_token", ""),
        "twilio_whatsapp_number": phone_number,
    }


def _fetch_whatsapp_number(account_sid: str, auth_token: str) -> str:
    """
    Fetches the WhatsApp-capable sender number from the sub-account.
    Returns it formatted as 'whatsapp:+1234567890'.
    """
    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json?PageSize=1"
        auth_str = f"{account_sid}:{auth_token}"
        auth_header = "Basic " + base64.b64encode(auth_str.encode()).decode()
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", auth_header)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        phones = data.get("incoming_phone_numbers", [])
        if phones:
            number = phones[0].get("phone_number", "")
            return f"whatsapp:{number}" if not number.startswith("whatsapp:") else number
    except Exception as e:
        logger.warning("Could not fetch WhatsApp number from sub-account", error=str(e))
    return ""


def _save_credentials_to_tenant(tenant_id_str: str, credentials: dict):
    """Merges Twilio credentials into the tenant's settings and persists."""
    repo = DynamoDBTenantRepository()
    tenant_id = TenantId(tenant_id_str)
    tenant = repo.get_by_id(tenant_id)
    if not tenant:
        raise ValueError(f"Tenant not found: {tenant_id_str}")

    settings = tenant.settings or {}
    settings.update(credentials)
    tenant.settings = settings
    repo.save(tenant)
    logger.info("Twilio credentials saved to tenant", tenant_id=tenant_id_str,
                phone=credentials.get("twilio_whatsapp_number"))


def lambda_handler(event, context):
    """
    Handles the OAuth redirect from Twilio Embedded Signup.
    Expects HTTP GET with ?code=XXX&state=TENANT_ID
    """
    try:
        query = event.get("queryStringParameters") or {}
        code = query.get("code")
        tenant_id_str = query.get("state")

        if not code or not tenant_id_str:
            logger.error("Missing code or state in callback", params=query)
            return {
                "statusCode": 302,
                "headers": {"Location": DASHBOARD_ERROR_URL},
                "body": ""
            }

        logger.info("Received Twilio OAuth callback", tenant_id=tenant_id_str)
        credentials = _exchange_code_for_token(code)
        _save_credentials_to_tenant(tenant_id_str, credentials)

        return {
            "statusCode": 302,
            "headers": {"Location": DASHBOARD_URL},
            "body": ""
        }

    except Exception as e:
        logger.error("Error processing Twilio OAuth callback", error=str(e))
        return {
            "statusCode": 302,
            "headers": {"Location": DASHBOARD_ERROR_URL},
            "body": ""
        }
