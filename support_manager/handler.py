import json
import os
import boto3
import requests
from typing import Dict, Any

def get_github_token() -> str:
    """Retrieve GitHub token from SSM Parameter Store."""
    ssm = boto3.client('ssm')
    try:
        # Assuming the token is stored in SSM. 
        # In a real scenario, you'd probably use a secret manager, but SSM is common for this stack.
        # We'll use the existing /chat-booking/github-token if it exists, or similar.
        # IF YOU DON'T HAVE THIS PARAMETER, YOU MUST CREATE IT MANUALLY OR IN CDK.
        # For now, let's assume it's stored as a secure string.
        parameter = ssm.get_parameter(
            Name='/chat-booking/github-token',
            WithDecryption=True
        )
        return parameter['Parameter']['Value']
    except Exception as e:
        print(f"Error fetching GitHub token: {e}")
        # Fallback for local testing if env var is set
        return os.environ.get('GITHUB_TOKEN', '')

def lambda_handler(event: Dict[str, Any], context):
    print(f"Received event: {json.dumps(event)}")
    
    # 1. Extract Input
    arguments = event.get('arguments', {})
    input_data = arguments.get('input', {})
    
    subject = input_data.get('subject')
    description = input_data.get('description')
    tenant_id = input_data.get('tenantId')
    
    # 2. Extract User Info from Identity
    identity = event.get('identity', {})
    claims = identity.get('claims', {})
    user_email = claims.get('email', 'Unknown Email')
    user_sub = claims.get('sub', 'Unknown ID')
    username = identity.get('username', 'Unknown User')

    # 3. Prepare Issue Content
    repo_name = os.environ.get('GITHUB_SUPPORT_REPO')
    if not repo_name:
        raise Exception("GITHUB_SUPPORT_REPO environment variable is not set")
    
    issue_title = f"[Support] {subject}"
    issue_body = (
        f"**Reporter:** {user_email} (User ID: {user_sub})\n"
        f"**Tenant ID:** {tenant_id}\n"
        f"**Description:**\n\n{description}\n\n"
        f"---\n*Ticket created via Admin Panel Support Form*"
    )
    
    # 4. Create Issue via GitHub API
    github_token = get_github_token()
    if not github_token:
        print("CRITICAL: No GitHub token found. Cannot create issue.")
        raise Exception("Configuration Error: Missing GitHub Token")

    url = f"https://api.github.com/repos/{repo_name}/issues"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "title": issue_title,
        "body": issue_body,
        "labels": ["support"]
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        print(f"Issue created successfully: {response.json().get('html_url')}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Failed to create GitHub issue: {e}")
        if e.response is not None:
             print(f"Response: {e.response.text}")
        raise Exception(f"Failed to create support issue: {str(e)}")
