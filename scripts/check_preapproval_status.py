import sys
import json
import mercadopago
import boto3

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
    if len(sys.argv) < 2:
        print("Usage: python3 check_preapproval_status.py <preapproval_id> [--stdin]")
        return

    preapproval_id = sys.argv[1]
    access_token = None
    
    # Check arguments
    if len(sys.argv) > 2 and sys.argv[2] == '--stdin':
        try:
            input_str = sys.stdin.read().strip()
            try:
                data = json.loads(input_str)
                env_vars = data.get('Environment', {}).get('Variables', {})
                access_token = env_vars.get('MP_ACCESS_TOKEN') or data.get('MP_ACCESS_TOKEN')
            except json.JSONDecodeError:
                access_token = input_str
        except Exception:
            pass

    if not access_token:
        secrets_data = get_secret()
        if secrets_data:
            access_token = secrets_data.get('ACCESS_TOKEN')
            
    if not access_token:
        print("ACCESS_TOKEN not found.")
        return

    sdk = mercadopago.SDK(access_token)
    result = sdk.preapproval().get(preapproval_id)
    
    if result["status"] == 200:
        response = result["response"]
        print(f"Status: {response.get('status')}")
        print(f"Payer Email: {response.get('payer_email')}")
        print(f"External Reference: {response.get('external_reference')}")
        print(f"Reason: {response.get('reason')}")
        print(json.dumps(response, indent=2))
    else:
        print(f"Error checking status: {result}")

if __name__ == "__main__":
    main()
