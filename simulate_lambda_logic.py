
import boto3
import os
import sys
from datetime import datetime

# Add shared to path
sys.path.append(os.getcwd())

os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["TENANTS_TABLE"] = "ChatBooking-Tenants"
os.environ["TENANT_USAGE_TABLE"] = "ChatBooking-TenantUsage"

from shared.domain.entities import TenantId, TenantPlan
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository
from shared.metrics import MetricsService
from shared.limit_service import TenantLimitService

def debug_tenant_limit(tenant_id_str):
    print(f"--- Debugging Tenant: {tenant_id_str} ---")
    
    tenant_id = TenantId(tenant_id_str)
    tenant_repo = DynamoDBTenantRepository()
    metrics_service = MetricsService()
    limit_service = TenantLimitService(tenant_repo, metrics_service)
    
    # 1. Test Repo 직접 호출
    print(f"Attempting to fetch tenant {tenant_id_str} from table...")
    tenant = tenant_repo.get_by_id(tenant_id)
    if tenant:
        print(f"SUCCESS: Tenant found!")
        print(f"  Name: {tenant.name}")
        print(f"  Plan: {tenant.plan}")
        print(f"  Status: {tenant.status}")
        print(f"  Limits: {tenant.get_plan_limits()}")
    else:
        print(f"FAILURE: Tenant NOT found in table.")
        
    # 2. Test MetricsService
    print(f"\nAttempting to fetch metrics...")
    usage = metrics_service.get_usage_for_plan_limits(tenant_id_str)
    print(f"  Usage: {usage}")
    
    # 3. Test LimitService
    print(f"\nTesting LimitService.check_can_create_provider...")
    can_create = limit_service.check_can_create_provider(tenant_id)
    print(f"  Can Create: {can_create}")

if __name__ == '__main__':
    debug_tenant_limit('4c2b1847')
