import boto3
import logging
import os
from typing import List, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger()


class EmailService:
    """
    Generic Infrastructure Adapter for sending emails via Amazon SES.
    """

    def __init__(self, region_name: Optional[str] = None):
        region = region_name or os.environ.get("SES_REGION") or os.environ.get("AWS_REGION") or "us-east-2"
        self.client = boto3.client("ses", region_name=region)
        # Inyectado automáticamente en cada envío para rastrear bounces/complaints
        self.configuration_set = os.environ.get("SES_CONFIGURATION_SET")

    def send_email(
        self,
        source: str,
        to_addresses: List[str],
        subject: str,
        body_html: str,
        body_text: str,
    ) -> bool:
        """
        Sends an email using Amazon SES.

        Args:
            source: The email address that is sending the email.
            to_addresses: A list of email addresses to send the email to.
            subject: The subject of the email.
            body_html: The HTML body of the email.
            body_text: The text body of the email.

        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        try:
            kwargs = {
                "Source": source,
                "Destination": {"ToAddresses": to_addresses},
                "Message": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                        "Text": {"Data": body_text, "Charset": "UTF-8"},
                    },
                },
            }
            # Adjuntar ConfigurationSet si está configurado (requerido para tracking de bounces/complaints)
            if self.configuration_set:
                kwargs["ConfigurationSetName"] = self.configuration_set

            response = self.client.send_email(**kwargs)
            logger.info(
                f"Email sent successfully to {to_addresses}. MessageId: {response.get('MessageId')}"
            )
            return True
        except ClientError as e:
            logger.error(
                f"Failed to send email to {to_addresses}. Error: {e.response['Error']['Message']}"
            )
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email to {to_addresses}: {str(e)}")
            return False


class SnsService:
    """
    Generic Infrastructure Adapter for publishing messages via Amazon SNS.
    """

    def __init__(self, region_name: Optional[str] = None):
        region = region_name or os.environ.get("AWS_REGION") or "us-east-2"
        self.client = boto3.client("sns", region_name=region)

    def publish_message(self, topic_arn: str, message: str, message_attributes: Optional[dict] = None) -> bool:
        """
        Publishes a message to an SNS Topic.

        Args:
            topic_arn: The ARN of the SNS Topic.
            message: The JSON or text message to send.
            message_attributes: Optional attributes for message filtering.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            kwargs = {
                "TopicArn": topic_arn,
                "Message": message
            }
            if message_attributes:
                kwargs["MessageAttributes"] = message_attributes

            response = self.client.publish(**kwargs)
            logger.info(f"Message published to SNS {topic_arn}. MessageId: {response.get('MessageId')}")
            return True
        except ClientError as e:
            logger.error(f"Failed to publish to SNS {topic_arn}. Error: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error publishing to SNS {topic_arn}: {str(e)}")
            return False
