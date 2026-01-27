import boto3
import logging
from typing import List, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger()


class EmailService:
    """
    Generic Infrastructure Adapter for sending emails via Amazon SES.
    """

    def __init__(self, region_name: str = "us-east-1"):
        self.client = boto3.client("ses", region_name=region_name)

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
            response = self.client.send_email(
                Source=source,
                Destination={"ToAddresses": to_addresses},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                        "Text": {"Data": body_text, "Charset": "UTF-8"},
                    },
                },
            )
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
