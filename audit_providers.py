import boto3
import os
from boto3.dynamodb.conditions import Key
from datetime import datetime

def audit_tenant_providers(tenant_id):
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    
    # 1. Count actual providers
    providers_table = dynamodb.Table('ChatBooking-Providers')
    response = providers_table.query(
        KeyConditionExpression=Key('tenantId').eq(tenant_id)
    )
    actual_count = response.get('Count', 0)
    provider_ids = [item['providerId'] for item in response.get('Items', [])]
    
    # 2. Get metrics counter
    usage_table = dynamodb.Table('ChatBooking-TenantUsage')
    month_key = f"MONTH#{datetime.now().strftime('%Y-%m')}"
    usage_response = usage_table.get_item(
        Key={'PK': f"TENANT#{tenant_id}", 'SK': month_key}
    )
    usage_item = usage_response.get('Item', {})
    usage_count = int(usage_item.get('providers', 0))
    
    # 3. Get total counter
    total_response = usage_table.get_item(
        Key={'PK': f"TENANT#{tenant_id}", 'SK': "TOTAL#ALL"}
    )
    total_item = total_response.get('Item', {})
    total_count = int(total_item.get('providers', 0))
    
    print(f"--- Audit Report for Tenant: {tenant_id} ---")
    print(f"Actual providers in Table: {actual_count}")
    print(f"Provider IDs: {provider_ids}")
    print(f"Usage Item ({month_key}): {usage_item}")
    print(f"Metrics 'providers' count (MONTH): {usage_count}")
    print(f"Metrics 'providers' count (TOTAL): {total_count}")
    
    # 4. Check Tenant Plan
    tenants_table = dynamodb.Table('ChatBooking-Tenants')
    tenant_response = tenants_table.get_item(Key={'tenantId': tenant_id})
    tenant_item = tenant_response.get('Item', {})
    
    print(f"Tenant Plan: {tenant_item.get('plan')}")
    print(f"Tenant Status: {tenant_item.get('status')}")
    print(f"Tenant Data: {tenant_item}")

    if actual_count != usage_count:
        print("\n[!] MISMATCH DETECTED!")
        return True
    return False

if __name__ == "__main__":
    audit_tenant_providers('4c2b1847')
