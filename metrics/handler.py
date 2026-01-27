"""
Metrics Lambda Handler

Handles GraphQL resolvers for dashboard metrics:
- getDashboardMetrics: Returns pre-aggregated metrics for the dashboard
- getPlanUsage: Returns current usage for plan limit display
"""

import json
from shared.utils import extract_tenant_id
from shared.metrics import MetricsService


def lambda_handler(event, context):
    """Main Lambda handler for metrics operations"""
    print(f"Metrics handler invoked with event: {json.dumps(event)}")

    # Extract field name
    field_name = None
    if "info" in event and "fieldName" in event["info"]:
        field_name = event["info"]["fieldName"]
    elif "field" in event:
        field_name = event["field"]

    if not field_name:
        raise ValueError("Could not determine operation field name")

    # Extract tenant ID
    tenant_id = extract_tenant_id(event)
    if not tenant_id:
        raise ValueError("Missing tenantId in request context")

    print(f"Processing field: {field_name} for tenant: {tenant_id}")

    # Initialize metrics service
    metrics_service = MetricsService()

    # Route to appropriate handler
    handlers = {
        "getDashboardMetrics": lambda: get_dashboard_metrics(
            metrics_service, tenant_id
        ),
        "getPlanUsage": lambda: get_plan_usage(metrics_service, tenant_id),
    }

    handler = handlers.get(field_name)
    if not handler:
        raise ValueError(f"Unknown field: {field_name}")

    result = handler()
    print(f"Returning result: {json.dumps(result, default=str)}")
    return result


def get_dashboard_metrics(metrics_service: MetricsService, tenant_id: str) -> dict:
    """Get all dashboard metrics for the tenant"""
    return metrics_service.get_dashboard_metrics(tenant_id)


def get_plan_usage(metrics_service: MetricsService, tenant_id: str) -> dict:
    """Get current usage for plan limits"""
    return metrics_service.get_usage_for_plan_limits(tenant_id)
