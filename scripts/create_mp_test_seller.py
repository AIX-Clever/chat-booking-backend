import boto3
import json
import secrets
import mercadopago
import sys

def get_secret():
    secret_name = "ChatBooking/MercadoPago"
    region_name = "us-east-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except Exception as e:
        print(f"Error retrieving secret: {e}")
        return None

    if 'SecretString' in get_secret_value_response:
        return json.loads(get_secret_value_response['SecretString'])
    return None

def create_test_user(access_token):
    sdk = mercadopago.SDK(access_token)
    
    # Generate a random identifier to ensure uniqueness if needed
    suffix = secrets.token_hex(4)
    description = f"Test Seller ChatBooking {suffix}"
    
    data = {
        "site_id": "MLC", # Chile
        "description": description
    }
    
    try:
        # According to documentation, POST /users/test_user
        # The SDK method might be sdk.user().create_test_user or similar
        # Checking SDK source or docs... standard mp sdk usually exposes it.
        # If not, we use requests. But let's try raw request via SDK if possible, or just requests.
        # Actually, let's use requests to be sure about the endpoint.
        import requests
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        response = requests.post("https://api.mercadopago.com/users/test_user", json=data, headers=headers)
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            print(f"Error creating test user: {response.status_code} {response.text}")
            return None
            
    except Exception as e:
        print(f"Exception creating test user: {e}")
        return None

def main():
    print("--- MercadoPago Test Seller Generator ---")
    access_token = None
    
    # Check arguments
    if len(sys.argv) > 1 and sys.argv[1] == '--stdin':
        print("Reading Access Token from STDIN...")
        try:
            # Expecting JSON { "MP_ACCESS_TOKEN": "..." } or just the string
            input_str = sys.stdin.read().strip()
            # Try parsing as JSON first (as aws cli output)
            try:
                data = json.loads(input_str)
                # Handle AWS Lambda config structure
                if 'check_args' in data: # Generic check
                    pass
                # Look for Environment.Variables
                env_vars = data.get('Environment', {}).get('Variables', {})
                access_token = env_vars.get('MP_ACCESS_TOKEN')
                
                if not access_token:
                    # Maybe it's just the token or simple json
                    access_token = data.get('MP_ACCESS_TOKEN')
            except json.JSONDecodeError:
                access_token = input_str
                
        except Exception as e:
            print(f"Error reading from stdin: {e}")
            return
            
    if not access_token:
        print("Fetching Production Access Token from Secrets Manager...")
        secrets_data = get_secret()
        if secrets_data:
            access_token = secrets_data.get('ACCESS_TOKEN')
    
    if not access_token:
        print("ACCESS_TOKEN not found.")
        return

    print(f"Using Access Token: {access_token[:10]}...")
    
    if not access_token:
        print("ACCESS_TOKEN not found in secret.")
        return

    print("Creating Test User (Seller)...")
    user_data = create_test_user(access_token)
    
    if user_data:
        print("\n✅ Test User Created Successfully!")
        print(json.dumps(user_data, indent=2))
        print("\nIMPORTANT:")
        print("1. Save the 'id', 'nickname', and 'password'.")
        print("2. Since the 'access_token' might not be in the response above (security), you might need to:")
        print("   - Log in to developers.mercadopago.com with your Main Account.")
        print("   - Or use the 'password' to log in as this test user? (Test users can't typically log in to dashboard).")
        print("   - Wait, usually for Test Users, you just 'get' credentials?")
        print("   - If API didn't return 'access_token', try generating one.")
    else:
        print("Failed to create test user.")

if __name__ == "__main__":
    main()
