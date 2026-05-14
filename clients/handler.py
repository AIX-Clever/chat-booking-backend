

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
    extract_user_id,
    error_response,
    to_iso_string,
    enforce_not_readonly
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
        user_id = extract_user_id(event) or 'unknown'

        # Enforce RBAC for mutations
        if field in ['createClient', 'updateClient']:
            enforce_not_readonly(event)

        # Route based on field name
        if field == 'getClient':
            return get_client(tenant_id, input_data.get('clientId'))
        elif field in ('listClients', 'listClientsPaginated'):
            return list_clients(
                tenant_id,
                limit=int(input_data.get('limit', 50)),
                next_token=input_data.get('nextToken')
            )
        elif field == 'createClient':
            return create_client(tenant_id, input_data, user_id)
        elif field == 'updateClient':
            return update_client(tenant_id, input_data, user_id)
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


def list_clients(tenant_id: str, limit: int = 50, next_token: str = None) -> Dict[str, Any]:
    """List clients for a tenant with pagination"""
    import json, base64

    query_kwargs = {
        'KeyConditionExpression': Key('tenantId').eq(tenant_id),
        'Limit': limit
    }

    if next_token:
        try:
            query_kwargs['ExclusiveStartKey'] = json.loads(
                base64.b64decode(next_token).decode('utf-8')
            )
        except Exception:
            raise ValueError("nextToken inválido")

    response = clients_table.query(**query_kwargs)

    items = [_format_client(item) for item in response.get('Items', [])]

    new_token = None
    if 'LastEvaluatedKey' in response:
        new_token = base64.b64encode(
            json.dumps(response['LastEvaluatedKey']).encode('utf-8')
        ).decode('utf-8')

    return {'items': items, 'nextToken': new_token}


def create_client(
    tenant_id: str, input_data: Dict[str, Any], user_id: str = 'unknown'
) -> Dict[str, Any]:
    """Create a new client"""

    # Security: Ensure input tenantId matches auth context if present
    if 'tenantId' in input_data and input_data['tenantId'] != tenant_id:
        raise ValueError(
            "Unauthorized: Cannot create client for another tenant"
        )

    # 1. Validate Identifiers
    identifiers = input_data.get('identifiers', [])

    UNIQUE_ID_TYPES = {'TAX_ID', 'RUT', 'CPF', 'DNI'}

    for ident in identifiers:
        id_type = ident['type']
        id_value = ident['value']

        # Validate format
        if not validate_id(id_type, id_value):
            raise ValueError(f"Identificador inválido ({id_type}): {id_value}")

        # Dedup via GSI for uniquely-constrained types
        if id_type in UNIQUE_ID_TYPES:
            existing = clients_table.query(
                IndexName='tax-id-index',
                KeyConditionExpression=Key('tenantId').eq(tenant_id) &
                Key('identifierValue').eq(id_value)
            )
            if existing.get('Count', 0) > 0:
                raise ValueError(
                    f"Ya existe un cliente con el identificador {id_value}"
                )

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
    _record_audit(tenant_id, client_id, 'ALL', None, 'CREATED', 'ADMIN_PANEL', 'ui', timestamp, user_id)

    return _format_client(item)


def update_client(
    tenant_id: str, input_data: Dict[str, Any], user_id: str = 'unknown'
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
        _record_audit(tenant_id, client_id, field, old, new, 'ADMIN_PANEL', 'ui', timestamp, user_id)

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


def _record_audit(tenant_id, client_id, field, old, new, source, source_id, timestamp, changed_by='unknown'):
    audit_item = {
        'tenantId': tenant_id,
        'clientIdAndTimestamp': f"{client_id}#{timestamp}#{str(uuid.uuid4())[:8]}",
        'clientId': client_id,
        'field': field,
        'oldValue': old if old is not None else "",
        'newValue': new,
        'source': source,
        'sourceId': source_id,
        'changedBy': changed_by,
        'timestamp': timestamp
    }
    audit_table.put_item(Item=audit_item)


def _format_client(item: Dict[str, Any]) -> Dict[str, Any]:
    """Format DynamoDB item for GraphQL"""
    # Convert Decimals to float/int if necessary, handling optional fields
    # Boto3 DynamoDB Table resource handles basic types well.
    return item
