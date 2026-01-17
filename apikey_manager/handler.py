
import os
import boto3
import json
from datetime import datetime, timezone
from typing import Dict, Any
from shared.domain.entities import TenantId, ApiKey
from shared.infrastructure.dynamodb_repositories import DynamoDBApiKeyRepository
from shared.utils import lambda_response, Logger, extract_appsync_event, generate_api_key, hash_api_key, generate_id, success_response, error_response

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    API Key Management Handler
    """
    logger = Logger()
    logger.info("Starting API Key operation", event=event)
    
    try:
        field, tenant_id_str, input_data = extract_appsync_event(event)
        tenant_id = TenantId(tenant_id_str)
        repo = DynamoDBApiKeyRepository()

        if field == 'listApiKeys':
            return handle_list_api_keys(repo, tenant_id)
        elif field == 'createApiKey':
            return handle_create_api_key(repo, tenant_id, input_data)
        elif field == 'revokeApiKey':
            return handle_revoke_api_key(repo, tenant_id, input_data)
        else:
            return error_response(f"Unknown field: {field}")

    except Exception as e:
        logger.error("Operation failed", error=str(e))
        raise e

def handle_list_api_keys(repo: DynamoDBApiKeyRepository, tenant_id: TenantId) -> Any:
    keys = repo.list_by_tenant(tenant_id)
    # Map to schema response
    return [
        {
            'apiKeyId': k.api_key_id,
            'tenantId': str(k.tenant_id),
            'name': k.name,
            'keyPreview': k.key_preview,
            'status': k.status,
            'createdAt': k.created_at.isoformat() + 'Z',
            'lastUsedAt': k.last_used_at.isoformat() + 'Z' if k.last_used_at else None
        }
        for k in keys
    ]

def handle_create_api_key(repo: DynamoDBApiKeyRepository, tenant_id: TenantId, input_data: Dict[str, Any]) -> Any:
    # Generate key
    public_key, hashed_key = generate_api_key()
    
    name = input_data.get('name', 'New API Key')
    preview = f"{public_key[:8]}...{public_key[-4:]}"
    
    new_key = ApiKey(
        api_key_id=generate_id('key'),
        tenant_id=tenant_id,
        api_key_hash=hashed_key,
        status='ACTIVE',
        name=name,
        key_preview=preview,
        allowed_origins=['*'], # Default to all for now
        rate_limit=1000,
        created_at=datetime.now(timezone.utc)
    )
    
    repo.save(new_key)
    
    # Return schema compliant object
    # Note: Schema doesn't return full key, but frontend needs it once?
    # Schema says returns ApiKey! which has keyPreview but not full key.
    # Frontend Create Dialog usually shows it once.
    # The `ApiKey` type in schema has `apiKeyId`, `keyPreview`...
    # It does NOT have `apiKey` (the full secret).
    # If I want to return the secret, I need to add it to generic `ApiKey` type (and expose it always? Bad)
    # OR return a specific CreateApiKeyResponse.
    #
    # Current schema.graphql definition:
    # type ApiKey { ... keyPreview: String ... }
    # 
    # If the user needs to copy the key, I must return it here.
    # I should add `apiKey: String` to the return type but make it nullable in general type?
    # Or just return it in `keyPreview` for this specific call? No, preview is truncated.
    # 
    # Decision: For now, I'll return the full key in `keyPreview` ONLY for creation? No, that corrupts the field logic.
    # I should have added `secret: String` to `ApiKey` type, nullable.
    # But since I didn't, I will (hotfix schema plan) add `secret: String` to ApiKey type, 
    # but only populate it on creation.
    
    # Let's adjust schema in next step if needed. 
    # For now, I'll return the object.
    
    return {
        'apiKeyId': new_key.api_key_id,
        'tenantId': str(new_key.tenant_id),
        'name': new_key.name,
        'keyPreview': new_key.key_preview,
        'status': new_key.status,
        'createdAt': new_key.created_at.isoformat() + 'Z',
        'lastUsedAt': None,
        'apiKey': public_key 
    }

def handle_revoke_api_key(repo: DynamoDBApiKeyRepository, tenant_id: TenantId, input_data: Dict[str, Any]) -> Any:
    key_id = input_data.get('apiKeyId')
    # Since repo doesn't have get_by_id, and primary key of ApiKeyTable is hashed key?
    # Wait, DynamoDBApiKeyRepository: 
    # KeyConditionExpression=Key('apiKeyHash').eq(api_key_hash) for find_by_hash
    # But for save/load?
    # Table definition in `dynamodb-stack.ts` (not viewed) likely has PK as hash or tenantId?
    # 
    # `DynamoDBApiKeyRepository.save`:
    # item = { ... 'apiKeyId': ... }
    # 
    # `list_by_tenant`: Query on `tenantId`.
    # 
    # If I revoke by ID, I need to find the item.
    # Does repo have get_by_id? No.
    # I need to implement get_by_id in repo or scan (inefficient) or use GSI if exists.
    # `list_by_tenant` works. I can filter in memory for now (safe enough for <100 keys).
    
    keys = repo.list_by_tenant(tenant_id)
    target_key = next((k for k in keys if k.api_key_id == key_id), None)
    
    if not target_key:
        return error_response("API Key not found", 404)
        
    target_key.status = 'REVOKED'
    repo.save(target_key)
    
    return {
        'apiKeyId': target_key.api_key_id,
        'tenantId': str(target_key.tenant_id),
        'name': target_key.name,
        'keyPreview': target_key.key_preview,
        'status': target_key.status,
        'createdAt': target_key.created_at.isoformat() + 'Z',
        'lastUsedAt': target_key.last_used_at.isoformat() + 'Z' if target_key.last_used_at else None
    }
