import os
import requests
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class MicrosoftAuthService:
    """
    Service for Microsoft Graph API Authentication and Calendar operations.
    Follows the pattern of GoogleAuthService.
    """

    # Scopes needed for calendar access and refresh tokens
    SCOPES = [
        "https://graph.microsoft.com/Calendars.ReadWrite",
        "offline_access",
        "User.Read",
    ]

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.authority = "https://login.microsoftonline.com/common"
        self.graph_url = "https://graph.microsoft.com/v1.0"

    def get_authorization_url(self, state: str) -> str:
        """
        Generates the Microsoft OAuth 2.0 authorization URL.
        """
        base_url = f"{self.authority}/oauth2/v2.0/authorize"
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": " ".join(self.SCOPES),
            "state": state,
        }
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{base_url}?{query_string}"

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchanges the authorization code for access and refresh tokens.
        """
        token_url = f"{self.authority}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "scope": " ".join(self.SCOPES),
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "client_secret": self.client_secret,
        }

        response = requests.post(token_url, data=data)
        response.raise_for_status()
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refreshes the access token using the refresh token.
        """
        token_url = f"{self.authority}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "scope": " ".join(self.SCOPES),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "client_secret": self.client_secret,
        }

        response = requests.post(token_url, data=data)
        response.raise_for_status()
        return response.json()

    def list_busy_slots(
        self, access_token: str, time_min: str, time_max: str, timezone: str = "UTC"
    ) -> list:
        """
        Queries the getSchedule endpoint to find busy slots.
        time_min/max should be ISO strings.
        """
        url = f"{self.graph_url}/me/calendar/getSchedule"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": f'outlook.timezone="{timezone}"',
        }

        # Microsoft expects a list of schedules to check
        body = {
            "Schedules": ["me"],
            "StartTime": {"dateTime": time_min, "timeZone": timezone},
            "EndTime": {"dateTime": time_max, "timeZone": timezone},
            "availabilityViewInterval": 15,  # Minutes
        }

        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()

        data = response.json()
        schedules = data.get("value", [])
        if not schedules:
            return []

        # Extract busy slots from the first schedule (me)
        schedule_items = schedules[0].get("scheduleItems", [])
        busy_slots = []
        for item in schedule_items:
            # Status: 0=Free, 1=Tentative, 2=Busy, 3=Oof, 4=WorkingElsewhere
            if item.get("status") != "free":
                busy_slots.append(
                    {
                        "start": item.get("start", {}).get("dateTime"),
                        "end": item.get("end", {}).get("dateTime"),
                    }
                )

        return busy_slots

    def create_event(
        self,
        access_token: str,
        summary: str,
        description: str,
        start_time: str,
        end_time: str,
        timezone: str = "UTC",
    ) -> Dict[str, Any]:
        """
        Creates a new event in the Outlook calendar.
        start_time/end_time should be ISO strings.
        """
        url = f"{self.graph_url}/me/events"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        event = {
            "subject": summary,
            "body": {"contentType": "HTML", "content": description},
            "start": {"dateTime": start_time, "timeZone": timezone},
            "end": {"dateTime": end_time, "timeZone": timezone},
        }

        response = requests.post(url, headers=headers, json=event)
        response.raise_for_status()
        return response.json()
