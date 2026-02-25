import json
import logging
import os
import boto3
import base64
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')

# Environment variables
DTE_FOLIOS_TABLE_NAME = os.environ.get('DTE_FOLIOS_TABLE')
dte_folios_table = dynamodb.Table(DTE_FOLIOS_TABLE_NAME) if DTE_FOLIOS_TABLE_NAME else None

def lambda_handler(event, context):
    """
    AppSync resolver handler for CAF Folio Management.
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Get tenant information from Auth
        identity = event.get('identity', {})
        if not identity:
            logger.error("No identity found in event")
            return create_error_response("Unauthorized", "UNAUTHORIZED")
            
        tenant_id = _extract_tenant_id(identity)
        if not tenant_id:
            logger.error("No tenantId found in identity")
            return create_error_response("Unauthorized: Missing tenant ID", "UNAUTHORIZED")
            
        field_name = event.get('info', {}).get('fieldName')
        
        # Route the request
        if field_name == 'uploadCaf':
            return handle_upload_caf(event['arguments'], tenant_id)
            
        logger.error(f"Unknown operation: {field_name}")
        return create_error_response(f"Unknown operation: {field_name}", "UNKNOWN_OPERATION")
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return create_error_response("Internal server error", "INTERNAL_SERVER_ERROR")

def handle_upload_caf(args, tenant_id):
    """
    Handles uploading and parsing a CAF XML file.
    Expects base64 encoded XML content.
    """
    if not dte_folios_table:
        logger.error("DTE_FOLIOS_TABLE environment variable not set")
        return create_error_response("Server configuration error", "SERVER_ERROR")

    try:
        base64_xml = args.get('base64Xml')
        tipo_dte = args.get('tipoDte')
        
        if not base64_xml or not tipo_dte:
            return create_error_response("Missing required arguments", "BAD_REQUEST")
            
        # 1. Decode Base64 string
        try:
            xml_content = base64.b64decode(base64_xml).decode('utf-8')
        except Exception as e:
            logger.error(f"Base64 decode failed: {e}")
            return {'success': False, 'message': 'El archivo no está codificado correctamente en Base64'}

        # 2. Parse XML to find ranges
        folio_inicial = None
        folio_final = None
        
        try:
            # We want to find <D> <RE> ... </RE> <RNG><D>...<H>...</H></D></RNG> </D>
            # The structure might vary, but generally D -> RNG -> D (Desde) and H (Hasta)
            root = ET.fromstring(xml_content)
            
            # Simple recursive search for tags, namespace agnostic
            def find_tag(element, tag_name):
                if element.tag.endswith(tag_name):
                    return element
                for child in element:
                    result = find_tag(child, tag_name)
                    if result is not None:
                        return result
                return None
                
            rng_element = find_tag(root, 'RNG')
            if rng_element is not None:
                desde_element = find_tag(rng_element, 'D')
                hasta_element = find_tag(rng_element, 'H')
                
                if desde_element is not None and hasta_element is not None:
                    folio_inicial = int(desde_element.text)
                    folio_final = int(hasta_element.text)
            
            if folio_inicial is None or folio_final is None:
                logger.error("Could not find RNG range in XML")
                return {'success': False, 'message': 'No se encontró el rango de folios en el archivo CAF.'}
                
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return {'success': False, 'message': 'El archivo subido no es un XML válido.'}
            
        # 3. Store in DynamoDB
        partition_key = f"{tenant_id}#{tipo_dte}"
        
        # We start emitting from folio_inicial
        dte_folios_table.put_item(
            Item={
                'tenantId_tipoDte': partition_key,
                'folio_actual': folio_inicial,
                'folio_inicial': folio_inicial,
                'folio_final': folio_final,
                'caf_xml': base64_xml, # Store the base64 string directly
            }
        )
        
        logger.info(f"Successfully uploaded CAF for {partition_key}. Rango: {folio_inicial} - {folio_final}")
        
        return {
            'success': True,
            'message': f'Folios cargados correctamente. Rango: {folio_inicial} al {folio_final}',
            'folioInicial': folio_inicial,
            'folioFinal': folio_final
        }

    except ClientError as e:
        logger.error(f"DynamoDB error: {e}")
        return create_error_response("Database error", "DATABASE_ERROR")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return create_error_response(f"Internal error", "INTERNAL_ERROR")

def create_error_response(message, code="BAD_REQUEST"):
    """Format standardized error responses matching AppSync expectations"""
    # Graphql error format handled implicitly or explicitly depending on schema
    raise Exception(f"{code}: {message}")

def _extract_tenant_id(identity):
    """
    Extracts tenant ID from AppSync identity object
    """
    if 'resolverContext' in identity and 'tenantId' in identity['resolverContext']:
        # IAM / Application logic custom context
        return identity['resolverContext']['tenantId']
    elif 'claims' in identity:
        # Cognito JWT
        claims = identity['claims']
        return claims.get('custom:tenantId')
    return None
