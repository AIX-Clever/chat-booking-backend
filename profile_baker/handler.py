import json
import os
import boto3
import logging
import time
from boto3.dynamodb.conditions import Key, Attr

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
cloudfront = boto3.client('cloudfront')
dynamodb = boto3.resource('dynamodb')

# Environment variables
LINK_BUCKET = os.environ.get('LINK_BUCKET')
DISTRIBUTION_ID = os.environ.get('DISTRIBUTION_ID')
TENANTS_TABLE = os.environ.get('TENANTS_TABLE')
SERVICES_TABLE_NAME = os.environ.get('SERVICES_TABLE') # Passed via standard env vars in commonProps?
PROVIDERS_TABLE_NAME = os.environ.get('PROVIDERS_TABLE')

# We need the table names. lambda-stack.ts commonProps passes them as SERVICES_TABLE, PROVIDERS_TABLE.
# Let's verify if they are available in os.environ. Only TENANTS_TABLE was explicit in `profileBakerFunction` env, 
# but `commonProps` usually adds them.
# Checking lambda-stack: `const commonProps = { ... environment: { SERVICES_TABLE: ... } }`
# Yes, they should be there.

def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")
    
    # Initialize tables globally or here
    services_table = dynamodb.Table(os.environ.get('SERVICES_TABLE'))
    providers_table = dynamodb.Table(os.environ.get('PROVIDERS_TABLE'))
    
    for record in event.get('Records', []):
        if record['eventName'] in ['INSERT', 'MODIFY']:
            new_image = record['dynamodb'].get('NewImage', {})
            
            # Extract data from DynamoDB Stream record (Low-level DynamoDB JSON format)
            # We need to unmarshall or carefuly extract.
            # tenantId: {'S': '...'}
            tenant_id = new_image.get('tenantId', {}).get('S')
            slug = new_image.get('slug', {}).get('S')
            if not slug:
                continue

            # Basic fields
            name = new_image.get('name', {}).get('S', 'Profesional')
            bio = new_image.get('bio', {}).get('S', '')
            photo_url = new_image.get('photoUrl', {}).get('S', '')
            theme_color = new_image.get('themeColor', {}).get('S', '#3b82f6')
            profession = new_image.get('profession', {}).get('S', 'Especialista')
            full_address = new_image.get('fullAddress', {}).get('S', '')
            operating_hours = new_image.get('operatingHours', {}).get('S', '')
            
            # Specializations is a List of Strings (L) or SS?
            # Usually stored as Attribute 'L' or 'SS' in DynamoDB Stream
            print(f"DEBUG Specializations raw: {new_image.get('specializations')}")
            specializations = []
            if 'specializations' in new_image:
                 # If it's a list (L) [ {'S': '...'}, ... ]
                if 'L' in new_image['specializations']:
                    specializations = [item['S'] for item in new_image['specializations']['L']]
                # If it's a String Set (SS)
                elif 'SS' in new_image['specializations']:
                     specializations = new_image['specializations']['SS']

            logger.info(f"Processing bake for tenant {tenant_id} with slug {slug}")
            
            try:
                # Fetch Services
                services = fetch_services(services_table, tenant_id)
                # Fetch Providers
                providers = fetch_providers(providers_table, tenant_id)
                
                profile_data = {
                    "tenantId": tenant_id,
                    "slug": slug,
                    "name": name,
                    "bio": bio,
                    "photoUrl": photo_url,
                    "themeColor": theme_color,
                    "profession": profession,
                    "specializations": specializations,
                    "fullAddress": full_address,
                    "operatingHours": operating_hours,
                    "services": services,
                    "providers": providers
                }
                
                bake_profile(slug, profile_data, context)
            except Exception as e:
                logger.error(f"Error baking profile for {slug}: {str(e)}")
                import traceback
                traceback.print_exc()
                
    return {"status": "success"}

def fetch_services(table, tenant_id):
    # Query GSI by tenantId if possible, or Scan with filter (Services table usually has tenantId as PK or GSI)
    # Check infrastructure definitions. Usually `Services` has PK=serviceId, but we need by tenant.
    # We should have a GSI `byTenant`. If not, we scan (inefficient but OK for bake).
    # Assuming GSI `byTenant` exists or we use Scan for now.
    # Let's try Query if index name known, else Scan.
    # Based on previous context, we might scan. 
    try:
        response = table.scan(
            FilterExpression=Attr('tenantId').eq(tenant_id) & Attr('active').eq(True)
        )
        items = response.get('Items', [])
        # Transform to frontend expected format
        return [
            {
                "serviceId": i['serviceId'],
                "name": i['name'],
                "description": i.get('description', ''),
                "durationMinutes": int(i['durationMinutes']),
                "price": float(i['price'])
            }
            for i in items
        ]
    except Exception as e:
        logger.error(f"Error fetching services: {e}")
        return []

def fetch_providers(table, tenant_id):
    try:
        response = table.scan(
            FilterExpression=Attr('tenantId').eq(tenant_id) & Attr('active').eq(True)
        )
        items = response.get('Items', [])
        return [
            {
                "providerId": i['providerId'],
                "name": i['name'],
                "photoUrl": i.get('photoUrl', '')
            }
            for i in items
        ]
    except Exception as e:
        logger.error(f"Error fetching providers: {e}")
        return []

def bake_profile(slug, profile_data, context=None):
    # 1. Read template
    try:
        response = s3.get_object(Bucket=LINK_BUCKET, Key='index.html')
        template_html = response['Body'].read().decode('utf-8')
    except Exception as e:
        logger.error(f"Could not read index.html template from {LINK_BUCKET}: {str(e)}")
        raise e

    # 2. SEO Tags
    name = profile_data['name']
    bio = profile_data['bio']
    photo_url = profile_data['photoUrl']
    
    title = f"Reserva con {name} | Lucia"
    description = bio[:160] if bio else f"Agenda tu cita con {name} de forma fácil y rápida."
    
    meta_tags = f"""
    <!-- SEO Injected by Baker -->
    <title>{title}</title>
    <meta name="description" content="{description}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    <meta property="og:image" content="{photo_url}">
    <meta property="og:type" content="website">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{title}">
    <meta name="twitter:description" content="{description}">
    <meta name="twitter:image" content="{photo_url}">
    """
    
    # 3. Data Injection (The Full Bake)
    # Serialize profile_data to JSON and inject as window.__INITIAL_DATA__
    json_data = json.dumps(profile_data)
    script_injection = f"""
    <script>
        window.__INITIAL_DATA__ = {json_data};
    </script>
    """
    
    # 4. Modify HTML
    # Replace/Inject SEO
    if "<title>" in template_html and "</title>" in template_html:
        import re
        template_html = re.sub(r'<title>.*?</title>', '', template_html)
    
    if "<head>" in template_html:
        template_html = template_html.replace("<head>", f"<head>{meta_tags}{script_injection}")
    
    # 5. Upload
    target_key = slug 
    logger.info(f"Uploading baked HTML to {target_key}")
    
    s3.put_object(
        Bucket=LINK_BUCKET,
        Key=target_key,
        Body=template_html.encode('utf-8'),
        ContentType='text/html',
        CacheControl='max-age=0, no-cache, no-store, must-revalidate'
    )
    
    # 6. Invalidate CloudFront
    if DISTRIBUTION_ID:
        logger.info(f"Invalidating CloudFront path: /{slug}*")
        try:
            cloudfront.create_invalidation(
                DistributionId=DISTRIBUTION_ID,
                InvalidationBatch={
                    'Paths': {
                        'Quantity': 1,
                        'Items': [f"/{slug}*"]
                    },
                    'CallerReference': f"bake-{slug}-{context.aws_request_id}" if context else f"bake-{slug}-{time.time()}"
                }
            )
        except Exception as e:
            logger.warning(f"Could not invalidate CloudFront: {str(e)}")
