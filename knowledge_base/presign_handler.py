import os
import boto3
import uuid
import json
from datetime import datetime
from botocore.exceptions import ClientError
from shared.utils import Logger, success_response, error_response, extract_appsync_event
from shared.domain.entities import TenantId

logger = Logger()
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

DOCUMENTS_BUCKET = os.environ.get('DOCUMENTS_BUCKET')
DOCUMENTS_TABLE_NAME = os.environ.get('DOCUMENTS_TABLE')
documents_table = dynamodb.Table(DOCUMENTS_TABLE_NAME) if DOCUMENTS_TABLE_NAME else None

# Limits (Hardcoded for now, ideal: from Tenant Plan)
MAX_FILES_PER_TENANT = 50
MAX_FILE_SIZE_MB = 10

def lambda_handler(event: dict, context) -> dict:
    """
    Handle getUploadUrl request.
    Input: { "fileName": "foo.pdf", "fileType": "application/pdf" }
    Output: { "uploadUrl": "...", "key": "...", "documentId": "..." }
    """
    try:
        field, tenant_id_str, input_data = extract_appsync_event(event)
        tenant_id = TenantId(tenant_id_str)
        
        if field == 'getUploadUrl':
             return handle_get_upload_url(tenant_id, input_data)
        else:
            return error_response(f"Unknown operation: {field}", 400)
            
    except Exception as e:
        logger.error("Presign failed", error=str(e))
        return error_response(str(e), 500)

def handle_get_upload_url(tenant_id: TenantId, input_data: dict) -> dict:
    if not DOCUMENTS_BUCKET or not documents_table:
        return error_response("Storage not configured", 503)

    file_name = input_data.get('fileName')
    file_type = input_data.get('contentType')
    
    if not file_name or not file_type:
        return error_response("Missing fileName or fileType", 400)

    # 1. Check Limits (Count PENDING or INDEXED docs)
    # Simple limit check: Query Count
    # Optimally: Retrieve Tenant Settings or keep usage counter.
    # For now: We assume limit OK or check DB count.
    # checking db count is expensive (Scan/Query). 
    # Let's skip heavy count for "Cheapest" MVP or do it efficiently later.
    
    # 2. Generate Key
    document_id = str(uuid.uuid4())
    # Key format: tenantId/documentId.pdf
    ext = file_name.split('.')[-1] if '.' in file_name else 'dat'
    key = f"{tenant_id}/{document_id}.{ext}"

    # 3. Generate Presigned URL
    try:
        url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': DOCUMENTS_BUCKET,
                'Key': key,
                'ContentType': file_type
                # 'ContentLength': ... # Client-side enforcement mostly
            },
            ExpiresIn=300 # 5 minutes
        )
    except ClientError as e:
         return error_response(f"S3 Error: {str(e)}", 500)

    # 4. Save metadata to DynamoDB (PENDING)
    item = {
        'tenantId': str(tenant_id),
        'documentId': document_id,
        'fileName': file_name,
        's3Key': key,
        'status': 'PENDING',
        'fileType': file_type,
        'createdAt': datetime.utcnow().isoformat(),
        'updatedAt': datetime.utcnow().isoformat()
    }
    
    documents_table.put_item(Item=item)
    
    return success_response({
        'uploadUrl': url,
        'key': key,
        'documentId': document_id
    })
