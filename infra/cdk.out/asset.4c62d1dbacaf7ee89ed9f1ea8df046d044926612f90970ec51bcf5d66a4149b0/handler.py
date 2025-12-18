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

def lambda_handler(event, context):
    """
    Handler for Workflow CRUD operations via AppSync
    """
    logger.info(f"Event: {json.dumps(event)}")
    
    # Get operation details
    info = event.get('info', {})
    field_name = info.get('fieldName')
    arguments = event.get('arguments', {})
    identity = event.get('identity', {})
    
    # Determine tenantId
    # For API Key auth (public/test), we might pass tenantId in valid inputs or it might be in the identity for Cognito
    # In this system, Cognito identity usually has claims
    tenant_id = None
    
    # Try to get tenant_id from Cognito custom attributes
    if 'claims' in identity:
        tenant_id = identity['claims'].get('custom:tenantId')
        
    # If not in claims (e.g. Admin or API Key), check arguments or fallback
    # For admin operations, we usually expect to be authenticated as a user belonging to a tenant
    if not tenant_id:
         # For development/admin access, we might need a way to specify tenantId if not in token
         # But the schema says Workflows are @aws_cognito_user_pools, so we should have a user
         logger.warning("No tenantId found in identity claims")
         # Fallback for testing if allowed, or error
         # In arguments?
         pass
         
    # For now, let's assume we extract it or error if strictly required.
    # However, createWorkflow might rely on the user's tenant.
    
    try:
        if field_name == 'listWorkflows':
            return list_workflows(tenant_id)
        elif field_name == 'getWorkflow':
            return get_workflow(tenant_id, arguments.get('workflowId'))
        elif field_name == 'createWorkflow':
            return create_workflow(tenant_id, arguments.get('input'))
        elif field_name == 'updateWorkflow':
            return update_workflow(tenant_id, arguments.get('input'))
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
