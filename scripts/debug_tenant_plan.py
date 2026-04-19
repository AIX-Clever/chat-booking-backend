
import boto3
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_tenants():
    print("Checking tenants across all potential tables...")
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    client = boto3.client("dynamodb", region_name="us-east-1")
    
    # List all tables
    tables = client.list_tables()["TableNames"]
    tenant_tables = [t for t in tables if "Tenants" in t and "ChatBooking" in t]
    
    print(f"Found tenant tables: {tenant_tables}")
    
    for table_name in tenant_tables:
        print(f"\n--- Scanning Table: {table_name} ---")
        table = dynamodb.Table(table_name)
        try:
            response = table.scan()
            items = response.get("Items", [])
            print(f"Found {len(items)} items in {table_name}.")
            
            for item in items:
                tenant_id = item.get("tenantId")
                name = item.get("name")
                plan = item.get("plan", "MISSING")
                email = item.get("billingEmail", "No Email")
                print(f"  Tenant: {name} ({tenant_id}) | Plan: {plan} | Email: {email}")
        except Exception as e:
            print(f"  Error scanning {table_name}: {e}")

if __name__ == "__main__":
    check_tenants()
