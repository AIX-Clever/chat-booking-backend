
import os
import boto3
import json
from typing import Dict, Any
from shared.utils import Logger, success_response, error_response
from shared.domain.entities import Tenant, TenantId
from shared.infrastructure.dynamodb_repositories import DynamoDBTenantRepository

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Get tenant public profile by slug
    Args:
        event: AppSync event with arguments.slug
    """
    logger = Logger()
    logger.info("Starting get public profile", event=event)
    
    try:
        # 1. Parse Input
        # For public queries, arguments are usually direct or in 'arguments'
        slug = event.get('slug') or event.get('arguments', {}).get('slug')
        
        if not slug:
            return error_response("Slug is required", 400)
            
        logger.info(f"Looking up tenant by slug: {slug}")
        
        # 2. Lookup Tenant by Slug (using GSI from DynamoDB)
        # We need to access the table directly or add find_by_slug to repository
        # For now, accessing via boto3 directly to keep it simple or extending repo
        
        dynamodb = boto3.resource('dynamodb')
        table_name = os.environ.get('TENANTS_TABLE', 'ChatBooking-Tenants')
        table = dynamodb.Table(table_name)
        
        response = table.query(
            IndexName='slug-index',
            KeyConditionExpression='slug = :slug',
            ExpressionAttributeValues={
                ':slug': slug
            }
        )
        
        logger.info(f"DynamoDB query response", response_count=response.get('Count', 0), items_count=len(response.get('Items', [])))
        
        items = response.get('Items', [])
        
        if not items:
            logger.warning(f"No tenant found for slug: {slug}")
            logger.info(f"Query details - Table: {table_name}, Index: slug-index, Slug: {slug}")
            return None # AppSync handles null return as valid for nullable type, or error if !
            
        tenant_data = items[0]
        tenant_id = tenant_data.get('tenantId')
        
        # 3. Fetch Services
        services = []
        try:
            services_table_name = os.environ.get('SERVICES_TABLE', 'ChatBooking-Services')
            services_table = dynamodb.Table(services_table_name)
            
            # Query services by tenantId
            # Assuming partition key is serviceId, we might need an index for tenantId
            # Or scan with filter if index missing (not ideal but works for now as services count is low)
            # Checking schema... Services partition key is 'serviceId' (hash)
            # Lambda permissions granted for ReadData.
            # Best practice: Query using GSI if available. 
            # ChatBooking-Services does not have a tenantId GSI defined in stack usually?
            # Let's check schema.graphql: type Service @aws_api_key @aws_cognito_user_pools
            # DynamoDBServiceRepository uses a GSI 'tenant-index' usually? 
            # Or scan. For now, we'll scan filtering by tenantId 
            # (assuming small number of services per table relative to partition or scan cost acceptable for this tier)
            
            # Let's try to query by index first if it exists, fallback to scan
            # Actually, looking at shared/infrastructure/dynamodb_repositories.py, it likely scans or query index
            # Let's simply scan with filter for now to be safe and quick
            
            services_response = services_table.scan(
                FilterExpression='tenantId = :tid AND active = :active',
                ExpressionAttributeValues={
                    ':tid': tenant_id,
                    ':active': True
                }
            )
            
            raw_services = services_response.get('Items', [])
            
            # Transform to simple public format
            for svc in raw_services:
                services.append({
                    'serviceId': svc.get('serviceId'),
                    'name': svc.get('name'),
                    'description': svc.get('description'),
                    'durationMinutes': int(svc.get('durationMinutes', 0)),
                    'price': float(svc.get('price', 0)) if svc.get('price') else 0,
                    'currency': 'CLP' # Default
                    # Add other fields if needed for SEO
                })
                
        except Exception as e:
            logger.error("Failed to fetch services", error=str(e))
            # Don't fail the whole profile load if services fail
            services = []
        
        # 4. Construct Public Profile
        # ONLY return safe, public data
        
        # Parse settings safely
        settings = tenant_data.get('settings', {})
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except:
                settings = {}
        elif not isinstance(settings, dict):
            settings = {} # handle Decimal or other types if necessary
            
        public_profile = {
            'tenantId': tenant_data.get('tenantId'),
            'name': tenant_data.get('name'),
            'slug': tenant_data.get('slug'),
            'bio': settings.get('bio', ''), # Assuming bio is in settings
            'photoUrl': settings.get('avatarUrl', ''), # Assuming avatarUrl is in settings
            'themeColor': settings.get('themeColor', '#1976d2'),
            'primaryServiceId': settings.get('primaryServiceId'),
            'services': services # Include services
        }
        
        logger.info(f"Found public profile for {slug} with {len(services)} services", profile=public_profile)
        return public_profile

    except Exception as e:
        logger.error("Get public profile failed", error=str(e))
        raise Exception(f"Internal error: {str(e)}")
