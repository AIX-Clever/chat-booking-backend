import os
import boto3
import urllib.parse
from datetime import datetime
from shared.utils import Logger
from shared.domain.entities import TenantId
from shared.infrastructure.vector_repository import VectorRepository
from shared.ai_handler import AIHandler
from document_processor import DocumentProcessor

logger = Logger()
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

DOCUMENTS_TABLE_NAME = os.environ.get('DOCUMENTS_TABLE')
documents_table = dynamodb.Table(DOCUMENTS_TABLE_NAME) if DOCUMENTS_TABLE_NAME else None

# Initialize Vector Infrastructure
db_cluster_arn = os.environ.get('DB_ENDPOINT')
db_secret_arn = os.environ.get('DB_SECRET_ARN')

vector_repo = None
ai_handler = None

if db_cluster_arn and db_secret_arn:
    vector_repo = VectorRepository(db_cluster_arn, db_secret_arn)
    # Reuse AIHandler for embedding only
    ai_handler = AIHandler(vector_repo) 

doc_processor = DocumentProcessor()

def lambda_handler(event: dict, context):
    """
    Handle S3 Object Created Event.
    """
    logger.info("Ingestion triggered", event=event)
    
    # Iterate over records (usually 1)
    # Ensure DB Schema exists (Idempotent)
    try:
        vector_repo.ensure_schema()
    except Exception as e:
        logger.error("Schema initialization failed", error=str(e))
        # Decide if we want to stop or continue. 
        # Continuing might fail on insert, but let's try.
    
    for record in event.get('Records', []):
        try:
            process_record(record)
        except Exception as e:
            logger.error("Failed to process record", error=str(e), record=record)
            # In production, send to DLQ
            continue

def process_record(record: dict):
    bucket = record['s3']['bucket']['name']
    key = urllib.parse.unquote_plus(record['s3']['object']['key'])
    
    # Key format: tenantId/documentId.ext
    parts = key.split('/')
    if len(parts) < 2:
        logger.warning("Invalid key format", key=key)
        return

    tenant_id_str = parts[0]
    # documentId could be the filename part excluding extension? 
    # Actually presign handler used UUID. Let's try to infer or query DB by Key GSI?
    # We didn't add GSI for s3Key, so we might need to rely on filename matching if we encoded ID in it.
    # In presign: key = f"{tenant_id}/{document_id}.{ext}"
    filename_part = parts[1]
    document_id = filename_part.rsplit('.', 1)[0] # remove extension
    
    logger.info(f"Processing document {document_id} for tenant {tenant_id_str}")

    # 1. Download File
    response = s3_client.get_object(Bucket=bucket, Key=key)
    file_content = response['Body'].read()
    file_type = response.get('ContentType', 'application/octet-stream')
    
    if file_type == 'application/octet-stream' and key.endswith('.pdf'):
        file_type = 'application/pdf'
        
    # 2. Process
    if not ai_handler or not vector_repo:
         logger.error("AI Infrastructure unavailable")
         update_status(tenant_id_str, document_id, 'FAILED', "Infrastructure error")
         return

    try:
        chunks = doc_processor.process(file_content, file_type)
        logger.info(f"Extracted {len(chunks)} chunks")
        
        # 3. Embed & Insert
        for chunk in chunks:
            embedding = ai_handler.get_embedding(chunk)
            vector_repo.insert(tenant_id_str, chunk, embedding)
            
        # 4. Update Status to INDEXED
        update_status(tenant_id_str, document_id, 'INDEXED', chunks_count=len(chunks))
        
    except Exception as e:
        logger.error("Processing error", error=str(e))
        update_status(tenant_id_str, document_id, 'FAILED', str(e))

def update_status(tenant_id: str, document_id: str, status: str, error_msg: str = None, chunks_count: int = 0):
    if not documents_table:
        return

    update_expr = "SET #status = :status, updatedAt = :updated"
    expr_vals = {
        ':status': status,
        ':updated': datetime.utcnow().isoformat()
    }
    
    if error_msg:
        update_expr += ", errorMessage = :error"
        expr_vals[':error'] = error_msg
        
    if chunks_count > 0:
        update_expr += ", chunksCount = :chunks"
        expr_vals[':chunks'] = chunks_count

    try:
        documents_table.update_item(
            Key={'tenantId': tenant_id, 'documentId': document_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues=expr_vals
        )
    except Exception as e:
        logger.error("Failed to update status", error=str(e))
