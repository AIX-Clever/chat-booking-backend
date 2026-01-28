import json
import os
import boto3
import logging
import time

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

def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")
    
    for record in event.get('Records', []):
        if record['eventName'] in ['INSERT', 'MODIFY']:
            new_image = record['dynamodb'].get('NewImage', {})
            
            # Extract data from DynamoDB Stream record
            tenant_id = new_image.get('tenantId', {}).get('S')
            slug = new_image.get('slug', {}).get('S')
            name = new_image.get('name', {}).get('S', 'Profesional')
            bio = new_image.get('bio', {}).get('S', '')
            photo_url = new_image.get('photoUrl', {}).get('S', '')
            
            if not slug:
                logger.info(f"Tenant {tenant_id} has no slug, skipping.")
                continue

            logger.info(f"Processing bake for tenant {tenant_id} with slug {slug}")
            
            try:
                bake_profile(slug, name, bio, photo_url, context)
            except Exception as e:
                logger.error(f"Error baking profile for {slug}: {str(e)}")
                
    return {"status": "success"}

def bake_profile(slug, name, bio, photo_url, context=None):
    # 1. Read the template index.html from the root of the bucket
    try:
        response = s3.get_object(Bucket=LINK_BUCKET, Key='index.html')
        template_html = response['Body'].read().decode('utf-8')
    except Exception as e:
        logger.error(f"Could not read index.html template from {LINK_BUCKET}: {str(e)}")
        raise e

    # 2. Prepare SEO Tags
    title = f"Reserva con {name} | Lucia"
    description = bio[:160] if bio else f"Agenda tu cita con {name} de forma fácil y rápida."
    
    # Simple replacement logic
    # We expect the template to have some markers or we replace standard tags
    # Let's replace the default ones or add them if not present
    
    # We'll use a simple approach: find <head> and inject/replace meta tags
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
    
    # Basic injection: replace <title>...</title> if exists, then inject after <head>
    if "<title>" in template_html and "</title>" in template_html:
        import re
        template_html = re.sub(r'<title>.*?</title>', '', template_html)
    
    if "<head>" in template_html:
        template_html = template_html.replace("<head>", f"<head>{meta_tags}")
    
    # 3. Upload the new HTML to slug/index.html
    # 3. Upload the new HTML to slug (clean URL)
    target_key = slug # No extension for clean URL behavior on CloudFront/S3
    logger.info(f"Uploading baked HTML to {target_key}")
    
    s3.put_object(
        Bucket=LINK_BUCKET,
        Key=target_key,
        Body=template_html.encode('utf-8'),
        ContentType='text/html',
        CacheControl='max-age=0, no-cache, no-store, must-revalidate'
    )
    
    # 4. Invalidate CloudFront path
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
