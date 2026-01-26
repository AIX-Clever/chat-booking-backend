import os
import requests
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

# You might need to install these:
# pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

class GoogleAuthService:
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str) -> str:
        """
        Generates the Google OAuth 2.0 authorization URL.
        Using direct URL construction to avoid local server dependency of installed flows.
        """
        base_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline", # Crucial for getting a refresh token
            "state": state,
            "prompt": "consent" # Forces consent screen to ensure refresh token is returned
        }
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{base_url}?{query_string}"

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchanges the authorization code for access and refresh tokens.
        """
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri
        }
        
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refreshes the access token using the refresh token.
        """
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        return response.json()

    def get_calendar_service(self, access_token: str, refresh_token: str):
        """
        Returns a build google calendar service object.
        """
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=self.SCOPES
        )
        return build('calendar', 'v3', credentials=creds)

    def list_busy_slots(self, service, time_min: str, time_max: str, calendar_id: str = 'primary') -> list:
        """
        Queries the freebusy endpoint to find busy slots.
        time_min/max should be ISO strings.
        """
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "timeZone": 'UTC',
            "items": [{"id": calendar_id}]
        }
        
        events_result = service.freebusy().query(body=body).execute()
        calendars = events_result.get('calendars', {})
        busy_slots = calendars.get(calendar_id, {}).get('busy', [])
        return busy_slots

    def create_event(self, service, summary: str, description: str, start_time: str, end_time: str, calendar_id: str = 'primary') -> Dict[str, Any]:
        """
        Creates a new event in the calendar.
        start_time/end_time should be ISO strings.
        """
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
            },
        }

        created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
        return created_event
