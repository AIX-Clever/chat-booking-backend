"""
Fintoc Client wrapper for managing Banking integration (Subscription Intents).
Uses direct REST API calls since the installed SDK version (2.17.0) does not expose
managers like `link_intents` or `subscription_intents`.
"""
import os
import json
import urllib.request
import urllib.error


FINTOC_API_BASE = "https://api.fintoc.com/v1"


class FintocClient:
    """
    Client for interacting with Fintoc API via direct HTTP.
    """
    def __init__(self, api_key=None, environment='test'):
        self.api_key = api_key or os.environ.get('FINTOC_API_KEY')
        self.environment = environment or os.environ.get('FINTOC_ENV', 'test')
        if not self.api_key:
            raise ValueError("Fintoc API Key is missing")

    def _request(self, method, path, data=None):
        """Makes a direct HTTP request to the Fintoc REST API."""
        url = f"{FINTOC_API_BASE}/{path}"
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            print(f"[INTERNAL_LOG] Fintoc HTTP Error {e.code}: {error_body}")
            raise RuntimeError(f"Fintoc API returned {e.code}: {error_body}") from e

    def create_link_intent(self, product='subscriptions', holder_type='individual', country='cl'):
        """
        Creates a Subscription Intent via POST /v1/subscription_intents.
        Returns a dict with widget_token and link_intent_id.
        """
        print(f"[INTERNAL_LOG] FintocClient.create_link_intent called. product={product}, key={self.api_key[:14]}...")

        # Fintoc Subscription Intents don't require a body per the docs.
        result = self._request("POST", "subscription_intents")

        print(f"[INTERNAL_LOG] Fintoc raw result: {result}")

        widget_token = result.get("widget_token")
        intent_id = result.get("id")

        if not widget_token or not intent_id:
            raise RuntimeError(f"Fintoc API returned unexpected result (missing widget_token or id): {result}")

        print(f"[INTERNAL_LOG] widget_token: {widget_token[:14]}...")
        print(f"[INTERNAL_LOG] subscription_intent id: {intent_id}")

        return {
            "widget_token": widget_token,
            "link_intent_id": intent_id,
        }

    def create_payment_intent(self, amount: int, currency: str, external_reference: str) -> dict:
        """
        Creates a one-time payment intent via POST /v1/payment_intents.
        Returns widget_token and payment_intent_id.
        """
        data = {
            "amount": amount,
            "currency": currency,
            "external_reference": external_reference,
        }
        result = self._request("POST", "payment_intents", data)
        widget_token = result.get("widget_token")
        intent_id = result.get("id")
        if not widget_token or not intent_id:
            raise RuntimeError(f"Fintoc payment_intent unexpected response: {result}")
        return {"widget_token": widget_token, "payment_intent_id": intent_id}

    def get_movement(self, movement_id, link_token):
        """Retrieves a movement (payment) details."""
        pass

    def get_account_info(self, link_token, account_id):
        """Retrieves account information."""
        pass
