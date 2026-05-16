import json
import os
import re
import boto3
import logging
import time
import html as _html
from boto3.dynamodb.conditions import Key, Attr

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
cloudfront = boto3.client('cloudfront')
dynamodb = boto3.resource('dynamodb')


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"[profile_baker] Variable de entorno requerida '{name}' no está definida.")
    return value


def escape_html(value: str) -> str:
    return _html.escape(str(value), quote=True)


# Environment variables — fail hard si faltan (regla de oro)
LINK_BUCKET = _require_env('LINK_BUCKET')
DISTRIBUTION_ID = _require_env('DISTRIBUTION_ID')
TENANTS_TABLE = _require_env('TENANTS_TABLE')
SERVICES_TABLE_NAME = _require_env('SERVICES_TABLE')
PROVIDERS_TABLE_NAME = _require_env('PROVIDERS_TABLE')
PUBLIC_LINK_BASE_URL = _require_env('PUBLIC_LINK_BASE_URL')

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
    tenant_plan = new_image.get('plan', {}).get('S', 'FREE')

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
            "providers": providers,
            "tenantPlan": tenant_plan,
        }
        
        bake_profile(slug, profile_data, context)
        
        # [FIX] Also trigger a bake for all Providers under this Tenant
        # This ensures that when tenant branding or address/hours are changed, all provider pages reflect it
        for provider in providers:
            # provider dict from fetch_providers only has subset of fields.
            # We need to fetch the full provider items, or at least enough to bake.
            # Let's fetch the full provider items from the table.
            provider_resp = providers_table.get_item(Key={'providerId': provider['providerId'], 'tenantId': tenant_id})
            provider_item = provider_resp.get('Item')
            if provider_item:
                logger.info(f"Triggering provider rebake for {provider['providerId']}")
                process_provider_record_from_item(provider_item, new_image, services_table, context)
                
    except Exception as e:
        logger.error(f"Error baking tenant profile for {slug}: {str(e)}")

def process_provider_record_from_item(provider_item, tenant_item, services_table, context):
    tenant_id = provider_item.get('tenantId')
    provider_id = provider_item.get('providerId')
    slug = provider_item.get('slug')
    
    if not slug: return

    # Parse tenant settings
    settings_raw = tenant_item.get('settings', '{}')
    # Since tenant_item came from new_image (Stream), it's in DynamoDB JSON format?
    # Wait, new_image is stream format.
    settings = parse_settings(tenant_item)
    settings_profile = settings.get('profile', {})
    
    # Provider specific data (from standard dict, since provider_item is from get_item)
    name = provider_item.get('name', 'Profesional')
    bio = provider_item.get('bio', '')
    photo_url = provider_item.get('photoUrl', '')
    
    # Tenant branding & info
    theme_color = settings.get('widgetConfig', {}).get('primaryColor') or '#3b82f6'
    
    # Address & Hours inherited from Tenant
    # tenant_item from stream has {"S": "..."} format
    full_address = tenant_item.get('fullAddress', {}).get('S', '') if isinstance(tenant_item.get('fullAddress'), dict) else tenant_item.get('fullAddress', '')
    if settings_profile.get('address'):
        addr_parts = [
            settings_profile['address'].get('street'),
            settings_profile['address'].get('city'),
            settings_profile['address'].get('state'),
            settings_profile['address'].get('country')
        ]
        full_address = ", ".join([p for p in addr_parts if p])
        
    operating_hours = settings_profile.get('operatingHours', '')
    
    specializations = provider_item.get('specializations', [])
    profession = provider_item.get('profession', 'Especialista')

    try:
        services = fetch_services(services_table, tenant_id)
        this_provider = {
            "providerId": provider_id,
            "name": name,
            "photoUrl": photo_url,
            "bio": bio,
            "services": provider_item.get('services', []),
            "profession": provider_item.get('profession'),
        }
        
        tenant_plan = tenant_item.get('plan', {}).get('S', 'FREE') if isinstance(tenant_item.get('plan'), dict) else tenant_item.get('plan', 'FREE')

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
            "providers": [this_provider],
            "preselectedProviderId": provider_id,
            "tenantPlan": tenant_plan,
        }

        bake_profile(slug, profile_data, context)
    except Exception as e:
        logger.error(f"Error during manual provider bake for {slug}: {str(e)}")

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
        settings_profile = settings.get('profile', {})
        
        # Provider specific data
        name = new_image.get('name', {}).get('S', 'Profesional')
        bio = new_image.get('bio', {}).get('S', '')
        photo_url = new_image.get('photoUrl', {}).get('S', '')
        
        # Tenant branding & info
        theme_color = settings.get('widgetConfig', {}).get('primaryColor') or '#3b82f6'
        tenant_plan = tenant_item.get('plan', 'FREE')

        # Address & Hours inherited from Tenant
        full_address = tenant_item.get('fullAddress', '')
        if settings_profile.get('address'):
            addr_parts = [
                settings_profile['address'].get('street'),
                settings_profile['address'].get('city'),
                settings_profile['address'].get('state'),
                settings_profile['address'].get('country')
            ]
            full_address = ", ".join([p for p in addr_parts if p])

        operating_hours = settings_profile.get('operatingHours', '')

        # Metadata / Profession from provider if available, else generic
        specializations = []
        try:
            metadata_str = new_image.get('metadata', {}).get('S', '{}')
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
            ai_drivers = metadata.get('aiDrivers', {})
            specializations = ai_drivers.get('specialties', [])
            profession = new_image.get('profession', {}).get('S', 'Especialista')
        except Exception as e:
            logger.warning(f"Failed to parse provider metadata: {e}")
            profession = "Especialista"

        services = fetch_services(services_table, tenant_id)
        this_provider = {
            "providerId": provider_id,
            "name": name,
            "photoUrl": photo_url,
            "bio": bio,
            "services": [s['S'] for s in new_image.get('services', {}).get('L', [])],
            "profession": new_image.get('profession', {}).get('S'),
        }

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
            "providers": [this_provider],
            "preselectedProviderId": provider_id,
            "tenantPlan": tenant_plan,
        }
        
        bake_profile(slug, profile_data, context)
        
        # [FIX] Also trigger a bake for the Tenant (Company page)
        # This ensures that when a provider is added/modified, the company page is updated
        tenant_slug = tenant_item.get('slug')
        if tenant_slug:
            logger.info(f"Triggering company rebake for tenant {tenant_id} (slug: {tenant_slug})")
            # We already have tenant_item, construct tenant_image for process_tenant_record wrapper
            # Simplest is to just call a modified process_tenant_record that takes the item
            # instead of image from stream.
            process_tenant_record_from_item(tenant_item, services_table, providers_table, context)

    except Exception as e:
        logger.error(f"Error baking provider profile for {slug}: {str(e)}")

def process_tenant_record_from_item(item, services_table, providers_table, context):
    tenant_id = item.get('tenantId')
    slug = item.get('slug')
    
    if not slug: return

    settings_raw = item.get('settings', '{}')
    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
    profile = settings.get('profile', {})
    
    name = profile.get('centerName') or item.get('name', 'Profesional')
    bio = profile.get('bio') or item.get('bio', '')
    photo_url = profile.get('logoUrl') or item.get('photoUrl', '')
    theme_color = settings.get('widgetConfig', {}).get('primaryColor') or item.get('themeColor', '#3b82f6')
    profession = profile.get('profession', 'Especialista')
    tenant_plan = item.get('plan', 'FREE')

    full_address = item.get('fullAddress', '')
    operating_hours = profile.get('operatingHours', '')
    specializations = item.get('specializations', [])

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
            "providers": providers,
            "tenantPlan": tenant_plan,
        }
        
        bake_profile(slug, profile_data, context)
    except Exception as e:
        logger.error(f"Error during manual tenant bake for {slug}: {str(e)}")

from boto3.dynamodb.types import TypeDeserializer

deserializer = TypeDeserializer()

def parse_settings(new_image):
    settings_data = new_image.get('settings', {})
    
    # Verify if it's a Stream Record format (S or M)
    if 'S' in settings_data:
        try:
            return json.loads(settings_data['S'])
        except Exception as e:
            logger.warning(f"Failed to parse settings JSON string: {e}")
            return {}
            
    if 'M' in settings_data:
        try:
            # TypeDeserializer expects the value inside 'M' IF we pass the whole item
            # But here settings_data IS the wrapper {"M": {...}} or {"S": ...}
            # deserializer.deserialize(settings_data) should work if valid low-level
            return deserializer.deserialize(settings_data)
        except Exception as e:
            logger.warning(f"Failed to deserialize settings Map: {e}")
            return {}
            
    # Fallback/Empty
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
    try:
        items = []
        kwargs = {"FilterExpression": Attr('tenantId').eq(tenant_id) & Attr('active').eq(True)}
        while True:
            response = table.scan(**kwargs)
            items.extend(response.get('Items', []))
            last = response.get('LastEvaluatedKey')
            if not last:
                break
            kwargs['ExclusiveStartKey'] = last
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
        items = []
        kwargs = {"FilterExpression": Attr('tenantId').eq(tenant_id) & Attr('active').eq(True)}
        while True:
            response = table.scan(**kwargs)
            items.extend(response.get('Items', []))
            last = response.get('LastEvaluatedKey')
            if not last:
                break
            kwargs['ExclusiveStartKey'] = last
        return [
            {
                "providerId": i['providerId'],
                "name": i['name'],
                "photoUrl": i.get('photoUrl', ''),
                "bio": i.get('bio', ''),
                "services": i.get('services', []),
                "profession": i.get('profession'),
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
    name = escape_html(profile_data['name'])
    bio = escape_html(profile_data.get('bio', ''))
    photo_url = escape_html(profile_data.get('photoUrl', ''))
    profession = escape_html(profile_data.get('profession', ''))

    if profession:
        title = f"{name} — {profession} | Lucia"
    else:
        title = f"Reserva con {name} | Lucia"
    raw_bio = profile_data.get('bio', '')
    description = escape_html(raw_bio[:160] if raw_bio else f"Agenda tu cita con {profile_data['name']}{' — ' + profile_data.get('profession', '') if profile_data.get('profession') else ''} de forma fácil y rápida.")

    slug = profile_data['slug']
    canonical_url = f"{PUBLIC_LINK_BASE_URL}/{slug}"

    meta_tags = f"""
    <!-- SEO Injected by Baker -->
    <title>{title}</title>
    <meta name="description" content="{description}">
    <link rel="canonical" href="{canonical_url}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    <meta property="og:image" content="{photo_url}">
    <meta property="og:image:width" content="400">
    <meta property="og:image:height" content="400">
    <meta property="og:image:type" content="image/jpeg">
    <meta property="og:url" content="{canonical_url}">
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="Hola Lucia">
    <meta property="og:locale" content="es_CL">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{title}">
    <meta name="twitter:description" content="{description}">
    <meta name="twitter:image" content="{photo_url}">
    """

    # 2.1 SEO Body Text (para indexabilidad sin JS)
    specialties_text = escape_html(", ".join(profile_data.get('specializations', [])))
    services_text = escape_html(", ".join([s['name'] for s in profile_data.get('services', [])]))
    full_address = escape_html(profile_data.get('fullAddress', ''))
    operating_hours = escape_html(profile_data.get('operatingHours', ''))

    address_html = f"<h2>Ubicación</h2><p>{full_address}</p>" if full_address else ""
    hours_html = f"<h2>Horarios</h2><p>{operating_hours}</p>" if operating_hours else ""

    seo_body = f"""
    <div style="display:none;" id="seo-content" aria-hidden="true">
        <h1>{name}</h1>
        <p>{bio}</p>
        {address_html}
        {hours_html}
        <h2>Especialidades</h2>
        <p>{specialties_text}</p>
        <h2>Servicios</h2>
        <p>{services_text}</p>
    </div>
    """

    # 3. Data Injection — escapar </script> para evitar script injection
    json_data = json.dumps(profile_data).replace("</", "<\\/")
    script_injection = f"""
    <script>
        window.__INITIAL_DATA__ = {json_data};
    </script>
    """

    # 4. Modify HTML
    if "<title>" in template_html and "</title>" in template_html:
        template_html = re.sub(r'<title>.*?</title>', '', template_html)
    
    if "<head>" in template_html:
        template_html = template_html.replace("<head>", f"<head>{meta_tags}{script_injection}")
    
    # Inject SEO body BEFORE </body> to avoid disturbing React's hydration root
    if "</body>" in template_html:
        template_html = template_html.replace("</body>", f"{seo_body}</body>")
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
