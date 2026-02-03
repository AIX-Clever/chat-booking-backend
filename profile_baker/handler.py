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
    
    # Initialize tables
    tenants_table = dynamodb.Table(os.environ.get('TENANTS_TABLE'))
    services_table = dynamodb.Table(os.environ.get('SERVICES_TABLE'))
    providers_table = dynamodb.Table(os.environ.get('PROVIDERS_TABLE'))
    
    for record in event.get('Records', []):
        if record['eventName'] not in ['INSERT', 'MODIFY']:
            continue
            
        new_image = record['dynamodb'].get('NewImage', {})
        
        # Determine if this is a Tenant or a Provider record
        if 'providerId' in new_image:
            process_provider_record(new_image, tenants_table, services_table, providers_table, context)
        elif 'tenantId' in new_image:
            process_tenant_record(new_image, services_table, providers_table, context)
                
    return {"status": "success"}

def process_tenant_record(new_image, services_table, providers_table, context):
    tenant_id = new_image.get('tenantId', {}).get('S')
    slug = new_image.get('slug', {}).get('S')
    
    if not slug:
        logger.info(f"Skipping tenant {tenant_id}: No slug defined")
        return

    # Extract and parse settings JSON
    settings = parse_settings(new_image)
    profile = settings.get('profile', {})
    
    # Priority: settings.profile > Top level attributes > Defaults
    name = profile.get('centerName') or new_image.get('name', {}).get('S', 'Profesional')
    bio = profile.get('bio') or new_image.get('bio', {}).get('S', '')
    photo_url = profile.get('logoUrl') or new_image.get('photoUrl', {}).get('S', '')
    theme_color = settings.get('widgetConfig', {}).get('primaryColor') or new_image.get('themeColor', {}).get('S', '#3b82f6')
    profession = profile.get('profession') or new_image.get('profession', {}).get('S', 'Especialista')
    
    full_address = construct_address(profile, new_image)
    operating_hours = profile.get('operatingHours') or new_image.get('operatingHours', {}).get('S', '')
    specializations = extract_specializations(profile, new_image)

    logger.info(f"Processing bake for tenant {tenant_id} with slug {slug}")
    
    try:
        services = fetch_services(services_table, tenant_id)
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
        logger.error(f"Error baking tenant profile for {slug}: {str(e)}")

def process_provider_record(new_image, tenants_table, services_table, providers_table, context):
    tenant_id = new_image.get('tenantId', {}).get('S')
    provider_id = new_image.get('providerId', {}).get('S')
    slug = new_image.get('slug', {}).get('S')
    
    if not slug:
        logger.info(f"Skipping provider {provider_id}: No slug defined")
        return

    logger.info(f"Processing personal bake for provider {provider_id} with slug {slug}")
    
    try:
        # Fetch Tenant for branding
        tenant_resp = tenants_table.get_item(Key={'tenantId': tenant_id})
        tenant_item = tenant_resp.get('Item')
        if not tenant_item:
            logger.error(f"Tenant {tenant_id} not found for provider {provider_id}")
            return
            
        settings_raw = tenant_item.get('settings', '{}')
        settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
        
        # Provider specific data
        name = new_image.get('name', {}).get('S', 'Profesional')
        bio = new_image.get('bio', {}).get('S', '')
        photo_url = new_image.get('photoUrl', {}).get('S', '')
        
        # Tenant branding
        theme_color = settings.get('widgetConfig', {}).get('primaryColor') or '#3b82f6'
        
        # Metadata / Profession from provider if available, else generic
        specializations = []
        try:
            metadata_str = new_image.get('metadata', {}).get('S', '{}')
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
            ai_drivers = metadata.get('aiDrivers', {})
            specializations = ai_drivers.get('specialties', [])
            # profession logic: try to get from new_image.profession, else generic.
            # 'profile' was undefined here. We should look at new_image or tenant settings defaults.
            # Let's try to get it from new_image directly first.
            profession = new_image.get('profession', {}).get('S', 'Especialista')
        except Exception as e:
            logger.warning(f"Failed to parse provider metadata: {e}")
            profession = "Especialista"

        services = fetch_services(services_table, tenant_id)
        # For professional landing, we only include this provider or highlight it
        all_providers = fetch_providers(providers_table, tenant_id)
        
        profile_data = {
            "tenantId": tenant_id,
            "slug": slug,
            "name": name,
            "bio": bio,
            "photoUrl": photo_url,
            "themeColor": theme_color,
            "profession": profession,
            "specializations": specializations,
            "services": services,
            "providers": all_providers,
            "preselectedProviderId": provider_id # Signal for frontend to open this one
        }
        
        bake_profile(slug, profile_data, context)
    except Exception as e:
        logger.error(f"Error baking provider profile for {slug}: {str(e)}")

def parse_settings(new_image):
    settings_raw = new_image.get('settings', {}).get('S', '{}')
    try:
        return json.loads(settings_raw)
    except Exception as e:
        logger.warning(f"Failed to parse settings JSON: {e}")
        return {}

def construct_address(profile, new_image):
    address = profile.get('address', {})
    if address:
        addr_parts = [
            address.get('street'),
            address.get('city'),
            address.get('state'),
            address.get('country')
        ]
        return ", ".join([p for p in addr_parts if p])
    return new_image.get('fullAddress', {}).get('S', '')

def extract_specializations(profile, new_image):
    spec_raw = profile.get('specializations')
    if spec_raw and isinstance(spec_raw, list):
        return spec_raw
    
    if 'specializations' in new_image:
        spec_attr = new_image['specializations']
        if 'L' in spec_attr:
            return [item['S'] for item in spec_attr['L']]
        elif 'SS' in spec_attr:
            return spec_attr['SS']
    return []

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

    # 2.1 SEO Body Text (For indexability without JS)
    specialties_text = ", ".join(profile_data.get('specializations', []))
    services_text = ", ".join([s['name'] for s in profile_data.get('services', [])])
    
    seo_body = f"""
    <div style="display:none;" id="seo-content" aria-hidden="true">
        <h1>{name}</h1>
        <p>{bio}</p>
        <h2>Especialidades</h2>
        <p>{specialties_text}</p>
        <h2>Servicios</h2>
        <p>{services_text}</p>
    </div>
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
    
    if "<body>" in template_html:
        template_html = template_html.replace("<body>", f"<body>{seo_body}")
    elif "<body " in template_html: # Handle body with attributes
        import re
        template_html = re.sub(r'(<body[^>]*>)', rf'\1{seo_body}', template_html)
    # 5. Upload
    target_key = f"{slug}/index.html"
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
