
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
        
        # 3.1 Fetch Providers
        providers = []
        try:
            providers_table_name = os.environ.get('PROVIDERS_TABLE', 'ChatBooking-Providers')
            providers_table = dynamodb.Table(providers_table_name)
            
            # Use Scan with filter for now (low volume)
            providers_response = providers_table.scan(
                FilterExpression='tenantId = :tid AND active = :active',
                ExpressionAttributeValues={
                    ':tid': tenant_id,
                    ':active': True
                }
            )
            
            raw_providers = providers_response.get('Items', [])
            
            for prov in raw_providers:
                providers.append({
                    'providerId': prov.get('providerId'),
                    'name': prov.get('name'),
                    'bio': prov.get('bio'),
                    'photoUrl': prov.get('photoUrl'),
                    'timezone': prov.get('timezone', 'America/Santiago'),
                    'serviceIds': prov.get('services', []) # Correct field name in DB is services
                    # Exclude metadata for public
                })
        except Exception as e:
            logger.error("Failed to fetch providers", error=str(e))
            providers = []
        
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
            settings = {} 

        profile_settings = settings.get('profile', {})

        # Address Logic
        address_data = tenant_data.get('address', {})
        # If address is stored in settings, merge/override
        if not address_data and profile_settings.get('address'):
             address_data = profile_settings.get('address')
        
        full_address = ""
        if isinstance(address_data, dict):
            parts = [
                address_data.get('street', ''),
                address_data.get('city', ''),
                address_data.get('state', '')
            ]
            full_address = ", ".join([str(p) for p in parts if p])

        public_profile = {
            'tenantId': tenant_data.get('tenantId'),
            'name': tenant_data.get('name'),
            'slug': tenant_data.get('slug'),
            'bio': tenant_data.get('bio') or profile_settings.get('bio', ''), 
            'photoUrl': tenant_data.get('photoUrl') or profile_settings.get('logoUrl', ''),
            'themeColor': tenant_data.get('themeColor') or settings.get('widgetConfig', {}).get('primaryColor', '#1976d2'),
            'primaryServiceId': tenant_data.get('primaryServiceId') or settings.get('primaryServiceId'), # This usually stays at root or needs check
            'services': services,
            'profession': profile_settings.get('profession', ''),
            'specializations': profile_settings.get('specializations', []),
            'operatingHours': profile_settings.get('operatingHours', ''),
            'fullAddress': full_address or profile_settings.get('fullAddress', ''),
            'providers': providers
        }
        
        logger.info(f"Found public profile for {slug} with {len(services)} services", profile=public_profile)
        return public_profile

    except Exception as e:
        logger.error("Get public profile failed", error=str(e))
        raise Exception(f"Internal error: {str(e)}")
