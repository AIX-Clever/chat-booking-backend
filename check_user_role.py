import boto3
import os
import json

def check_user_role(email):
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.Table('ChatBooking-UserRoles')
    
    print(f"Checking table: {table.table_name}")
    
    # 1. Scan for the email (since we suspect PK might be userId=email)
    print(f"\nScanning for email: {email}...")
    try:
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('email').eq(email)
        )
        items = response.get('Items', [])
        print(f"Found {len(items)} items via Scan:")
        for item in items:
            print(json.dumps(item, indent=2))
            
    except Exception as e:
        print(f"Scan failed: {e}")

if __name__ == "__main__":
    check_user_role('lucylisperguer@gmail.com')
