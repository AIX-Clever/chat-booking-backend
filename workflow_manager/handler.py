import json
import os
import boto3 # type: ignore
import logging
import uuid
import datetime
from botocore.exceptions import ClientError # type: ignore

# Initialize logger
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
workflows_table = dynamodb.Table(os.environ['WORKFLOWS_TABLE'])
tenants_table = dynamodb.Table(os.environ['TENANTS_TABLE'])

from shared.utils import extract_appsync_event, error_response
from shared.domain.entities import TenantId

def lambda_handler(event, context):
    """
    Handler for Workflow CRUD operations via AppSync
    """
    try:
        # Use shared utility to consistent extraction
        field_name, tenant_id_str, arguments = extract_appsync_event(event)
        tenant_id = tenant_id_str # extract_appsync_event returns string or TenantId? value. let's check. 
        # extract_appsync_event returns (field, tenant_id_str, input_data)
        
        logger.info(f"Operation: {field_name}, Tenant: {tenant_id}")
        
        if field_name == 'listWorkflows':
            return list_workflows(tenant_id)
        elif field_name == 'getWorkflow':
            return get_workflow(tenant_id, arguments.get('workflowId'))
        elif field_name == 'createWorkflow':
            return create_workflow(tenant_id, arguments)
        elif field_name == 'updateWorkflow':
            return update_workflow(tenant_id, arguments)
        elif field_name == 'deleteWorkflow':
            return delete_workflow(tenant_id, arguments.get('workflowId'))
        else:
            raise Exception(f"Unknown field name: {field_name}")

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise e

def list_workflows(tenant_id):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    response = workflows_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('tenantId').eq(tenant_id)
    )
    return response.get('Items', [])

def get_workflow(tenant_id, workflow_id):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    response = workflows_table.get_item(
        Key={
            'tenantId': tenant_id,
            'workflowId': workflow_id
        }
    )
    return response.get('Item')

def create_workflow(tenant_id, input_data):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    workflow_id = str(uuid.uuid4())
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    item = {
        'tenantId': tenant_id,
        'workflowId': workflow_id,
        'name': input_data['name'],
        'description': input_data.get('description'),
        'definition': input_data['definition'], # JSON
        'status': input_data.get('status', 'DRAFT'),
        'createdAt': timestamp,
        'updatedAt': timestamp
    }
    
    workflows_table.put_item(Item=item)
    return item

def update_workflow(tenant_id, input_data):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    workflow_id = input_data['workflowId']
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Build update expression
    update_parts = []
    expression_values = {}
    expression_names = {}
    
    fields = ['name', 'description', 'definition', 'status']
    for field in fields:
        if field in input_data:
            update_parts.append(f"#{field} = :{field}")
            expression_values[f":{field}"] = input_data[field]
            expression_names[f"#{field}"] = field
            
    update_parts.append("#updatedAt = :updatedAt")
    expression_values[":updatedAt"] = timestamp
    expression_names["#updatedAt"] = "updatedAt"
    
    update_expression = "SET " + ", ".join(update_parts)
    
    response = workflows_table.update_item(
        Key={
            'tenantId': tenant_id,
            'workflowId': workflow_id
        },
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
        ReturnValues="ALL_NEW"
    )
    
    return response.get('Attributes')

def delete_workflow(tenant_id, workflow_id):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    # Get item first to return it
    item = get_workflow(tenant_id, workflow_id)
    if not item:
        raise Exception("Workflow not found")
        
    workflows_table.delete_item(
        Key={
            'tenantId': tenant_id,
            'workflowId': workflow_id
        }
    )
    return item
