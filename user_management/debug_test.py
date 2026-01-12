"""
Quick debug script to test UserRoleRepository directly
Run this in AWS Lambda console to debug
"""

import json
from shared.infrastructure.user_role_repository import DynamoDBUserRoleRepository
from shared.domain.entities import TenantId

def lambda_handler(event, context):
    repo = DynamoDBUserRoleRepository()
    
    # Test 1: List users for tenant
    tenant_id = TenantId("e9624300")
    
    try:
        users = repo.list_by_tenant(tenant_id)
        print(f"Found {len(users)} users")
        
        result = []
        for user in users:
            print(f"User: {user.email}, Role: {user.role.value}")
            result.append(user.to_dict())
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'count': len(users),
                'users': result
            })
        }
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
