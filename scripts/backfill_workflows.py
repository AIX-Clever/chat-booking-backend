import boto3
import json
import os
import uuid
from datetime import datetime, timezone
import sys

# Configuration
REGION = os.environ.get('AWS_REGION', 'us-east-1')
TENANTS_TABLE_NAME = os.environ.get('TENANTS_TABLE', 'ChatBooking-Tenants')
WORKFLOWS_TABLE_NAME = os.environ.get('WORKFLOWS_TABLE', 'ChatBooking-Workflows')

# Path to base workflow template
BASE_WORKFLOW_PATH = os.path.join(os.path.dirname(__file__), '../workflow_manager/base_workflow.json')

def load_base_workflow():
    try:
        with open(BASE_WORKFLOW_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading base_workflow.json from {BASE_WORKFLOW_PATH}: {e}")
        sys.exit(1)

def scan_tenants(dynamodb):
    table = dynamodb.Table(TENANTS_TABLE_NAME)
    try:
        response = table.scan()
        tenants = response.get('Items', [])
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            tenants.extend(response.get('Items', []))
        return tenants
    except Exception as e:
        print(f"Error scanning tenants table {TENANTS_TABLE_NAME}: {e}")
        sys.exit(1)

def has_workflows(dynamodb, tenant_id):
    table = dynamodb.Table(WORKFLOWS_TABLE_NAME)
    try:
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('tenantId').eq(tenant_id),
            Limit=1
        )
        return response['Count'] > 0
    except Exception as e:
        print(f"Error checking workflows for tenant {tenant_id}: {e}")
        return False

def create_default_workflow(dynamodb, tenant_id, base_workflow):
    table = dynamodb.Table(WORKFLOWS_TABLE_NAME)
    workflow_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc).isoformat()
    
    workflow_item = {
        'tenantId': tenant_id,
        'workflowId': workflow_id,
        'name': base_workflow.get('name', 'Default Booking Flow'),
        'description': base_workflow.get('description', 'Created via backfill script'),
        'steps': base_workflow.get('steps', {}),
        'isActive': True,
        'createdAt': current_time,
        'updatedAt': current_time,
        'metadata': {}
    }
    
    try:
        table.put_item(Item=workflow_item)
        print(f"✅ Created default workflow for tenant {tenant_id} (ID: {workflow_id})")
        return True
    except Exception as e:
        print(f"❌ Failed to create workflow for tenant {tenant_id}: {e}")
        return False

def main():
    print(f"Starting Default Workflow Backfill...")
    print(f"Region: {REGION}")
    print(f"Tenants Table: {TENANTS_TABLE_NAME}")
    print(f"Workflows Table: {WORKFLOWS_TABLE_NAME}")
    
    session = boto3.Session(region_name=REGION)
    dynamodb = session.resource('dynamodb')
    
    base_workflow = load_base_workflow()
    print(f"Loaded base workflow template: {base_workflow.get('name')}")
    
    tenants = scan_tenants(dynamodb)
    print(f"Found {len(tenants)} tenants.")
    
    stats = {'scanned': 0, 'skipped': 0, 'created': 0, 'errors': 0}
    
    for tenant in tenants:
        tenant_id = tenant.get('tenantId')
        tenant_name = tenant.get('name', 'Unknown')
        stats['scanned'] += 1
        
        print(f"[{stats['scanned']}/{len(tenants)}] Checking tenant: {tenant_name} ({tenant_id})...", end=' ')
        
        if has_workflows(dynamodb, tenant_id):
            print("Has workflows. Skipped.")
            stats['skipped'] += 1
        else:
            print("MISSING WORKFLOWS. Creating default...", end=' ')
            if create_default_workflow(dynamodb, tenant_id, base_workflow):
                stats['created'] += 1
            else:
                stats['errors'] += 1
                
    print("\n--- Backfill Complete ---")
    print(f"Total Tenants Scanned: {stats['scanned']}")
    print(f"Skipped (Already OK):  {stats['skipped']}")
    print(f"Fixed (Backfilled):    {stats['created']}")
    print(f"Errors:                {stats['errors']}")

if __name__ == "__main__":
    main()
