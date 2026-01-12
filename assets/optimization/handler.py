
import os
import boto3
import io
import logging
from PIL import Image

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

BUCKET_NAME = os.environ.get('BUCKET_NAME')
DEST_PREFIX = os.environ.get('DEST_PREFIX', 'optimized/')

def lambda_handler(event, context):
    """
    S3 Event Handler for Image Optimization
    """
    for record in event['Records']:
        try:
            # Get object key from event
            source_bucket = record['s3']['bucket']['name']
            source_key = record['s3']['object']['key']
            
            # Check if it's already in optimized folder (prevent loops)
            if source_key.startswith(DEST_PREFIX):
                logger.info(f"Skipping already optimized object: {source_key}")
                continue
                
            # Check validation (only accept raw/)
            if not source_key.startswith('raw/'):
                logger.info(f"Skipping object not in raw/: {source_key}")
                continue

            logger.info(f"Processing: {source_bucket}/{source_key}")

            # Download file
            response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
            content_type = response['ContentType']
            image_content = response['Body'].read()

            # Process Image
            with Image.open(io.BytesIO(image_content)) as img:
                # Convert to RGB (in case of RGBA/P) before WebP if needed
                if img.mode in ("RGBA", "P"):
                   img = img.convert("RGBA")
                else:
                   img = img.convert("RGB")

                # Define sizes
                sizes = {
                    'thumbnail': (150, 150),
                    'small': (400, 400),
                    'medium': (800, 800)
                }
                
                base_filename = os.path.basename(source_key)
                name_without_ext = os.path.splitext(base_filename)[0]

                # Generate and upload each size
                for size_name, dimensions in sizes.items():
                    # Resize (copy img)
                    current_img = img.copy()
                    current_img.thumbnail(dimensions)
                    
                    # Save to WebP in memory
                    buffer = io.BytesIO()
                    current_img.save(buffer, format="WEBP", quality=85)
                    buffer.seek(0)
                    
                    # Upload
                    dest_key = f"{DEST_PREFIX}{size_name}/{name_without_ext}.webp"
                    
                    s3_client.put_object(
                        Bucket=BUCKET_NAME,
                        Key=dest_key,
                        Body=buffer,
                        ContentType='image/webp',
                        CacheControl='max-age=31536000' # Cache for 1 year
                    )
                    
                    logger.info(f"Generated {size_name}: {dest_key}")

        except Exception as e:
            logger.error(f"Error processing record: {e}")
            raise e

    return {
        'statusCode': 200,
        'body': 'Optimization complete'
    }
