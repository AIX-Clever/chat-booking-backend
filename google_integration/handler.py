import json
import os
import base64
from typing import Dict, Any

from shared.infrastructure.google_auth_service import GoogleAuthService
from shared.infrastructure.dynamodb_repositories import DynamoDBProviderIntegrationRepository
from shared.domain.entities import TenantId

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handles Google OAuth flow via Function URL.
    Routes:
    - GET /authorize: Redirects to Google consent screen
    - GET /callback: Handles code exchange
    """
    path = event.get('rawPath', '')
    query_params = event.get('queryStringParameters', {}) or {}
    
    # Initialize services
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    
    # Function URL domain (supplied by Lambda env or computed)
    # We might need to pass the Function URL explicitly or deduce it headers
    # For now, let's assume we pass it as env var or it is configured in Google Console
    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI')
    
    # Fallback to deduce from Host header if not in env
    if not redirect_uri:
        headers = event.get('headers', {})
        host = headers.get('host') or headers.get('Host')
        if host:
            redirect_uri = f"https://{host}/callback"
    
    if not client_id or not client_secret or not redirect_uri:
        debug_info = {
            "client_id_set": bool(client_id),
            "client_secret_set": bool(client_secret),
            "redirect_uri_set": bool(redirect_uri),
            "redirect_uri_val": redirect_uri
        }
        print(f"Missing config: {json.dumps(debug_info)}")
        return _response(500, "Missing configuration")

    auth_service = GoogleAuthService(client_id, client_secret, redirect_uri)
    repo = DynamoDBProviderIntegrationRepository()

    if path.endswith('/authorize'):
        return handle_authorize(query_params, auth_service)
    elif path.endswith('/callback'):
        return handle_callback(query_params, auth_service, repo)
    else:
        return _response(404, "Not Found")

def handle_authorize(params: dict, auth_service: GoogleAuthService) -> Dict[str, Any]:
    tenant_id = params.get('tenantId')
    provider_id = params.get('providerId')
    
    if not tenant_id or not provider_id:
        return _response(400, "Missing tenantId or providerId")

    # Encode state
    state = base64.urlsafe_b64encode(f"{tenant_id}:{provider_id}".encode()).decode()
    
    url = auth_service.get_authorization_url(state)
    
    # Redirect
    return {
        "statusCode": 302,
        "headers": {
            "Location": url
        }
    }

def handle_callback(params: dict, auth_service: GoogleAuthService, repo: DynamoDBProviderIntegrationRepository) -> Dict[str, Any]:
    code = params.get('code')
    state = params.get('state')
    error = params.get('error')
    
    if error:
        return _response(400, f"Google Auth Error: {error}")
        
    if not code or not state:
        return _response(400, "Missing code or state")

    try:
        # Decode state
        decoded_state = base64.urlsafe_b64decode(state).decode()
        tenant_id_str, provider_id = decoded_state.split(':')
        tenant_id = TenantId(tenant_id_str)
        
        # Exchange code
        tokens = auth_service.exchange_code_for_token(code)
        
        # Save tokens
        repo.save_google_creds(tenant_id, provider_id, tokens)
        
        return _response(200, "Successfully connected Google Calendar! You can close this window.")
        
    except Exception as e:
        print(f"Callback Error: {e}")
        return _response(500, "Internal Server Error during callback")

def _response(status: int, message: str) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "body": message,
        "headers": {
            "Content-Type": "text/plain"
        }
    }
