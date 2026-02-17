

import os
import boto3
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List
from boto3.dynamodb.conditions import Key
from validation import validate_id
from shared.utils import (
    extract_appsync_event,
    error_response,
    to_iso_string
)

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
CLIENTS_TABLE_NAME = os.environ.get('CLIENTS_TABLE')
AUDIT_LOGS_TABLE_NAME = os.environ.get('CLIENT_AUDIT_LOGS_TABLE')

clients_table = dynamodb.Table(CLIENTS_TABLE_NAME)
audit_table = dynamodb.Table(AUDIT_LOGS_TABLE_NAME)

# Logger setup
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    AppSync Handler for Client File operations
    """
    logger.info("Received event", extra={"event": event})

    try:
        field, tenant_id, input_data = extract_appsync_event(event)

        # Route based on field name
        if field == 'getClient':
            return get_client(tenant_id, input_data.get('clientId'))
        elif field == 'listClients':
            return list_clients(tenant_id)
        elif field == 'createClient':
            return create_client(tenant_id, input_data)
        elif field == 'updateClient':
            return update_client(tenant_id, input_data)
        elif field == 'listClientAuditLogs':
            return list_client_audit_logs(tenant_id, input_data.get('clientId'))
        else:
            return error_response(f"Unknown operation: {field}")

    except ValueError as e:
        logger.error(f"Validation Error: {str(e)}")
        return error_response(str(e))
    except Exception as e:
        logger.error(f"Internal Error: {str(e)}")
        # In production, hide internal details
        return error_response(f"Internal Server Error: {str(e)}")


def get_client(tenant_id: str, client_id: str) -> Dict[str, Any]:
    """Get a single client by ID"""
    if not client_id:
        raise ValueError("clientId is required")

    response = clients_table.get_item(
        Key={
            'tenantId': tenant_id,
            'id': client_id
        }
    )

    item = response.get('Item')
    if not item:
        # AppSync expects null if not found, usually? Or we can raise error.
        # Returning None results in null in GraphQL.
        return None

    return _format_client(item)


def list_clients(tenant_id: str) -> List[Dict[str, Any]]:
    """List all clients for a tenant"""
    # Note: In production this should be paginated
    response = clients_table.query(
        KeyConditionExpression=Key('tenantId').eq(tenant_id)
    )

    items = response.get('Items', [])
    logger.info(f"Found {len(items)} clients")
    if len(items) > 0:
        logger.info(f"First client raw: {items[0]}")
    
    result = [_format_client(item) for item in items]
    if len(result) > 0:
        logger.info(f"First client result: {result[0]}")
        
    return result


def create_client(
    tenant_id: str, input_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a new client"""

    # Security: Ensure input tenantId matches auth context if present
    if 'tenantId' in input_data and input_data['tenantId'] != tenant_id:
        raise ValueError(
            "Unauthorized: Cannot create client for another tenant"
        )

    # 1. Validate Identifiers (Tax ID Check)
    identifiers = input_data.get('identifiers', [])
    
    # Optional: we allow creation without identifiers for now? 
    # But schema says it is a list.
    for ident in identifiers:
        if ident['type'] == 'TAX_ID':
            # Check duplicates via GSI
            existing = clients_table.query(
                IndexName='tax-id-index',
                KeyConditionExpression=Key('tenantId').eq(tenant_id) &
                Key('identifierValue').eq(ident['value'])
            )
            if existing.get('Count', 0) > 0:
                raise ValueError(
                    f"Client with ID {ident['value']} already exists"
                )

            # Basic validation
            if not validate_id(ident['type'], ident['value'], 'CL'):
                raise ValueError(f"Invalid identifier: {ident['value']}")

    client_id = str(uuid.uuid4())
    timestamp = to_iso_string(datetime.utcnow())

    item = {
        'tenantId': tenant_id,
        'id': client_id,
        'createdAt': timestamp,
        'updatedAt': timestamp,
        **input_data,  # Spread the rest: names, contactInfo, etc.
        'email': input_data.get('email') or (
            input_data.get('contactInfo', [{}])[0].get('value') 
            if input_data.get('contactInfo') else None
        ),
        'identifierValue': (
            identifiers[0]['value'] if identifiers else 'UNKNOWN'
        ),  # For GSI
    }

    clients_table.put_item(Item=item)
    
    # Audit log (Manuel creation)
    _record_audit(tenant_id, client_id, 'ALL', None, 'CREATED', 'ADMIN_PANEL', 'ui', timestamp)

    return _format_client(item)


def update_client(
    tenant_id: str, input_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Update existing client"""
    client_id = input_data.get('id')
    if not client_id:
        raise ValueError("Client ID is required for update")

    # Check existence
    existing = clients_table.get_item(
        Key={'tenantId': tenant_id, 'id': client_id}
    )
    if 'Item' not in existing:
        raise ValueError("Client not found")

    # Update fields
    timestamp = to_iso_string(datetime.utcnow())
    old_item = existing['Item']
    new_item = old_item.copy()

    # Detect changes for auditing
    changes = []
    for k, v in input_data.items():
        if k != 'id' and old_item.get(k) != v:
            changes.append((k, old_item.get(k), v))
            new_item[k] = v

    new_item['updatedAt'] = timestamp

    # Update GSI attribute if identifiers changed
    if 'identifiers' in input_data and input_data['identifiers']:
        new_item['identifierValue'] = input_data['identifiers'][0]['value']
        
    # Ensure top-level email is synced
    if 'email' in input_data:
        new_item['email'] = input_data['email']

    clients_table.put_item(Item=new_item)
    
    # Record audits
    for field, old, new in changes:
        _record_audit(tenant_id, client_id, field, old, new, 'ADMIN_PANEL', 'ui', timestamp)

    return _format_client(new_item)


def list_client_audit_logs(tenant_id: str, client_id: str) -> List[Dict[str, Any]]:
    """Fetch history of changes for a client"""
    if not client_id:
        raise ValueError("clientId is required")
        
    response = audit_table.query(
        KeyConditionExpression=Key('tenantId').eq(tenant_id) & 
                                 Key('clientIdAndTimestamp').begins_with(f"{client_id}#"),
        ScanIndexForward=False # Newest first
    )
    
    return response.get('Items', [])


def _record_audit(tenant_id, client_id, field, old, new, source, source_id, timestamp):
    audit_item = {
        'tenantId': tenant_id,
        'clientIdAndTimestamp': f"{client_id}#{timestamp}#{str(uuid.uuid4())[:8]}",
        'clientId': client_id,
        'field': field,
        'oldValue': old if old is not None else "",
        'newValue': new,
        'source': source,
        'sourceId': source_id,
        'changedBy': 'system', # Could be user ID from auth context later
        'timestamp': timestamp
    }
    audit_table.put_item(Item=audit_item)


def _format_client(item: Dict[str, Any]) -> Dict[str, Any]:
    """Format DynamoDB item for GraphQL"""
    # Convert Decimals to float/int if necessary, handling optional fields
    # Boto3 DynamoDB Table resource handles basic types well.
    return item
