
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
            logger.info(f"No tenant found for slug: {slug}. Checking providers...")
            
            # Fallback: Check if it's a Provider Slug
            # Since we don't have a global slug index on Providers yet, we must Scan
            # This is not performant for high volume but acceptable for current scale/fix.
            
            providers_table_name = os.environ.get('PROVIDERS_TABLE', 'ChatBooking-Providers')
            providers_table = dynamodb.Table(providers_table_name)
            
            try:
                # Scan for slug
                # Use limit? No, slug should be unique-ish.
                scan_response = providers_table.scan(
                    FilterExpression='slug = :slug',
                    ExpressionAttributeValues={':slug': slug}
                )
                
                provider_items = scan_response.get('Items', [])
                
                if not provider_items:
                    logger.warning(f"No provider found for slug: {slug}")
                    return None
                    
                # Found a provider!
                provider_data = provider_items[0]
                tenant_id = provider_data.get('tenantId')
                provider_id = provider_data.get('providerId')
                
                logger.info(f"Found provider {provider_id} for slug {slug} in tenant {tenant_id}")
                
                # Fetch Tenant details for branding
                tenant_response = table.get_item(Key={'tenantId': tenant_id})
                tenant_data = tenant_response.get('Item')
                
                if not tenant_data:
                    logger.error(f"Tenant {tenant_id} not found for provider {slug}")
                    return None
                    
                # Continue with this tenant_data context, but mark as provider profile
                # We need to adapt the flow below to prioritize this provider
                
                # Assign tenant_data so subsequent logic works
                # But we want to inject 'preselectedProviderId' or modify specific fields
                
                # Set specific flag to modify return structure at the end
                is_provider_profile = True
                target_provider_id = provider_id
                
            except Exception as e:
                logger.error(f"Error scanning providers for slug {slug}: {str(e)}")
                return None
        else:
            # Tenant found
            tenant_data = items[0]
            tenant_id = tenant_data.get('tenantId')
            is_provider_profile = False
            target_provider_id = None
        
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
                # Parse metadata safely to extract specializations
                specializations = []
                try:
                    metadata_str = prov.get('metadata', '{}')
                    if isinstance(metadata_str, str):
                        metadata = json.loads(metadata_str)
                    else:
                        metadata = metadata_str or {}
                    
                    ai_drivers = metadata.get('aiDrivers', {})
                    specializations = ai_drivers.get('specialties', [])
                except Exception as e:
                    logger.warning(f"Failed to parse provider metadata for {prov.get('providerId')}", error=str(e))

                providers.append({
                    'providerId': prov.get('providerId'),
                    'name': prov.get('name'),
                    'bio': prov.get('bio'),
                    'photoUrl': prov.get('photoUrl'),
                    'timezone': prov.get('timezone', 'America/Santiago'),
                    'serviceIds': prov.get('services', []), # Correct field name in DB is services
                    'specializations': specializations,
                    'available': prov.get('active', True) # distinct from specific availability logic, just means "active provider"
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
            except Exception:
                settings = {}
                
        # Double check settings is not None (json.loads can return None) and is a dict
        if not isinstance(settings, dict):
            settings = {} 

        profile_settings = settings.get('profile') or {}

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
            'themeColor': tenant_data.get('themeColor') or (settings.get('widgetConfig') or {}).get('primaryColor', '#1976d2'),
            'primaryServiceId': tenant_data.get('primaryServiceId') or settings.get('primaryServiceId'), # This usually stays at root or needs check
            'services': services,
            'profession': profile_settings.get('profession', ''),
            'specializations': profile_settings.get('specializations', []),
            'operatingHours': profile_settings.get('operatingHours', ''),
            'fullAddress': full_address or profile_settings.get('fullAddress', ''),
            'providers': providers,
            'tenantPlan': tenant_data.get('plan', 'LITE'),
            'preselectedProviderId': target_provider_id if is_provider_profile else None
        }
        
        # Override name/bio/photo if it is a specific provider profile
        if is_provider_profile:
            # Find the specific provider data in the fetched 'providers' list
            # The 'providers' list contains all active providers for the tenant (fetched in step 3.1)
            target_provider = next((p for p in providers if p['providerId'] == target_provider_id), None)
            
            if target_provider:
                public_profile['name'] = target_provider['name']
                public_profile['bio'] = target_provider.get('bio') or public_profile['bio']
                public_profile['photoUrl'] = target_provider.get('photoUrl') or public_profile['photoUrl']
                public_profile['specializations'] = target_provider.get('specializations') or public_profile['specializations']
                public_profile['profession'] = "Especialista" # Or from provider metadata if available
        
        
        logger.info(f"Found public profile for {slug} with {len(services)} services", profile=public_profile)
        return public_profile

    except Exception as e:
        logger.error("Get public profile failed", error=str(e))
        raise Exception(f"Internal error: {str(e)}")
