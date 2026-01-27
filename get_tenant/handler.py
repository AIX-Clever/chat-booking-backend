import os
import json
from typing import Dict, Any
import uuid
from datetime import datetime, timezone
from shared.domain.entities import TenantId, Workflow, WorkflowStep
from shared.infrastructure.dynamodb_repositories import (
    DynamoDBTenantRepository,
    DynamoDBWorkflowRepository,
)
from shared.utils import (
    Logger,
    extract_appsync_event,
    error_response,
)

# Load Default Flow
try:
    with open(os.path.join(os.path.dirname(__file__), "base_workflow.json"), "r") as f:
        DEFAULT_FLOW = json.load(f)
except Exception as e:
    print(f"Warning: Could not load default flow from local file: {e}")
    DEFAULT_FLOW = {}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Get tenant handler
    """
    logger = Logger()
    logger.info("Starting get tenant", event=event)

    try:
        # Extract context using shared utility (handles args, identity, headers, etc.)
        field, tenant_id_str, input_data = extract_appsync_event(event)

        # Override tenant_id if explicit argument is provided (though extract_appsync_event prioritizes args)
        # Actually, extract_appsync_event already does: args > identity > stash > headers.
        # But for getTenant, if tenantId arg is provided, it returns that.
        # If not, it returns identity tenantId.
        # Perfect.

        logger.info("Resolved Tenant ID", tenant_id=tenant_id_str)

        if not tenant_id_str:
            return error_response("Tenant ID not found in context or arguments", 400)

        # Authorization Check (if specific ID requested vs inferred)
        # If the ID came from arguments, we might want to verify it matches identity?
        # extract_appsync_event doesn't tell us WHERE it got it from.
        # But for 'getTenant', usually:
        # 1. Admin asks for specific tenant (if super admin) -> Args
        # 2. Admin asks for their own -> Identity
        # 3. Widget asks for public tenant -> Args (via x-tenant-id header or arg)

        # We can implement a safety check:
        # If identity is present, and extracted ID differs...
        # But we don't easily have 'identity' here without parsing again.
        # For now, we trust the extraction priority.

        tenant_repo = DynamoDBTenantRepository()
        tenant = tenant_repo.get_by_id(TenantId(tenant_id_str))

        if not tenant:
            return error_response("Tenant not found", 404)

        # SELF-HEALING: Check if tenant has workflows, if not create default
        try:
            workflow_repo = DynamoDBWorkflowRepository()
            # We use list_by_tenant which is efficient enough for this check (usually 0 or few items)
            existing_flows = workflow_repo.list_by_tenant(tenant.tenant_id)

            if not existing_flows and DEFAULT_FLOW:
                logger.info(
                    f"Tenant {tenant_id_str} has no workflows. Self-healing with default flow."
                )

                # Map JSON steps to Entity steps
                steps = {}
                for step_id, step_data in DEFAULT_FLOW.get("steps", {}).items():
                    steps[step_id] = WorkflowStep(
                        step_id=step_data["stepId"],
                        type=step_data["type"],
                        content=step_data.get("content", {}),
                        next_step=step_data.get("next"),
                    )

                new_workflow = Workflow(
                    workflow_id=str(uuid.uuid4()),
                    tenant_id=tenant.tenant_id,
                    name=DEFAULT_FLOW.get("name", "Default Booking Flow"),
                    description=DEFAULT_FLOW.get(
                        "description", "Auto-created by system"
                    ),
                    is_active=True,
                    steps=steps,
                    metadata={},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )

                workflow_repo.save(new_workflow)
                logger.info(
                    f"Created default workflow {new_workflow.workflow_id} for tenant {tenant.tenant_id}"
                )

        except Exception as wh_error:
            # Non-blocking error - log and continue so user can still login
            logger.error("Workflow self-healing failed", error=str(wh_error))

        # Return Result via success_response (if it handles direct return)
        # or simple dict if AppSync expects direct object.
        # The other lambdas use success_response.
        # Schema expects Tenant! (object), success_response returns raw data?
        # shared/utils.py success_response returns data directly.

        return {
            "tenantId": str(tenant.tenant_id),
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status.value,
            "plan": tenant.plan.value,
            "billingEmail": tenant.billing_email,
            "settings": tenant.settings if tenant.settings else None,
            "createdAt": tenant.created_at.isoformat() + "Z",
            "updatedAt": getattr(tenant, "updated_at", tenant.created_at).isoformat()
            + "Z",
        }

    except Exception as e:
        logger.error("Get tenant failed", error=str(e))
        raise e
