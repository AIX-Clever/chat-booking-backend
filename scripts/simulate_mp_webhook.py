import sys
import json
import hmac
import hashlib
import requests
import boto3
import time
import os

def get_secret():
    secret_name = "ChatBooking/MercadoPago"
    region_name = "us-east-1"
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except Exception as e:
        print(f"Error retrieving secret: {e}")
        return None
    if 'SecretString' in get_secret_value_response:
        return json.loads(get_secret_value_response['SecretString'])
    return None

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 simulate_mp_webhook.py <preapproval_id> <webhook_url> [--stdin]")
        return

    preapproval_id = sys.argv[1]
    webhook_url = sys.argv[2]
    secret = None
    
    if len(sys.argv) > 3 and sys.argv[3] == '--stdin':
        try:
            input_str = sys.stdin.read().strip()
            try:
                data = json.loads(input_str)
                env_vars = data.get('Environment', {}).get('Variables', {})
                secret = env_vars.get('MP_WEBHOOK_SECRET') or data.get('MP_WEBHOOK_SECRET')
            except json.JSONDecodeError:
                secret = input_str
        except Exception:
            pass
            
    if not secret:
        print("Fetching Webhook Secret from Secrets Manager...")
        secrets_data = get_secret()
        if secrets_data:
            secret = secrets_data.get('WEBHOOK_SECRET')
            
    if not secret:
        print("WEBHOOK_SECRET not found.")
        return

    # Construct Payload
    # MP Webhook structure for preapproval
    # Query params usually have data.id and type
    # Body is often empty or minimal?
    # Actually, MP documentation says:
    # POST /webhook?data.id=...&type=...
    # Body: {}
    # Let's try sending data in query params as MP does.
    
    ts = str(int(time.time() * 1000))
    request_id = f"simulated-{ts}"
    data_id = preapproval_id
    
    # Manifest: id:[data.id];request-id:[x-request-id];ts:[ts];
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    
    calculated_hmac = hmac.new(
        secret.encode(),
        manifest.encode(),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "x-signature": f"ts={ts},v1={calculated_hmac}",
        "x-request-id": request_id,
        "Content-Type": "application/json"
    }
    
    # URL with query params
    target_url = f"{webhook_url}?topic=subscription_preapproval&id={data_id}&data.id={data_id}"
    
    print(f"Sending webhook to {target_url}")
    print(f"Manifest: {manifest}")
    print(f"Signature: {calculated_hmac}")
    
    response = requests.post(target_url, headers=headers, json={})
    
    print(f"Response: {response.status_code} {response.text}")

if __name__ == "__main__":
    main()
