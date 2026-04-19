import boto3
from botocore.exceptions import ClientError
from shared.domain.repositories import FileStorageRepository
from shared.utils import Logger

logger = Logger()


class S3FileStorageRepository(FileStorageRepository):
    """S3 implementation of FileStorageRepository"""

    def __init__(self, bucket_name: str, region_name: str = "us-east-1"):
        self.s3_client = boto3.client("s3", region_name=region_name)
        self.bucket_name = bucket_name

    def generate_presigned_url(
        self,
        file_name: str,
        content_type: str,
        operation: str = "put_object",
        expiration: int = 3600,
    ) -> str:
        """
        Generate a presigned URL to share an S3 object (or upload to it)
        """
        try:
            # Add prefix if not present (enforce raw/ for uploads)
            if operation == "put_object" and not file_name.startswith("raw/"):
                key = f"raw/{file_name}"
            else:
                key = file_name

            params = {
                "Bucket": self.bucket_name,
                "Key": key,
                "ContentType": content_type,
            }

            response = self.s3_client.generate_presigned_url(
                ClientMethod=operation, Params=params, ExpiresIn=expiration
            )
            return response

        except ClientError as e:
            logger.error("Error generating presigned URL", error=str(e))
            raise e
