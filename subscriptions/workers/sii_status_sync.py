import boto3
from datetime import datetime
from shared.subscriptions.config import SubscriptionConfig
from boto3.dynamodb.conditions import Attr

# INITIALIZATION
dynamodb = boto3.resource("dynamodb")
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)


def lambda_handler(event, context):
    """
    Cron-based worker to sync DTE status from SII
    """
    print("Starting SII Status Sync Worker...")

    # 1. Query for items in 'EN_PROCESO'
    # For now, we use a Scan with filter for simplicity,
    # but a GSI on dteSiiStatus is recommended for production.
    try:
        response = SUBSCRIPTIONS_TABLE.scan(
            FilterExpression=Attr("dteSiiStatus").eq("EN_PROCESO")
        )
        items = response.get("Items", [])
        print(f"Found {len(items)} documents pending synchronization.")

        for item in items:
            sync_document_status(item)

    except Exception as e:
        print(f"Error querying pending documents: {str(e)}")
        raise e


def sync_document_status(item):
    tenant_id = item["tenantId"]
    sub_id = item["subscriptionId"]
    track_id = item.get("dteTrackId")

    if not track_id:
        print(f"Skipping {sub_id}: No TrackID found.")
        return

    print(f"Syncing TrackID {track_id} for Tenant {tenant_id}...")

    # TODO: Implement real SOAP Query using Certificate/Token
    # This is a placeholder for the logic we are prototyping in test_sii_token.py

    # mock_status_query(track_id) -> returns 'ACEPTADO', 'RECHAZADO', or 'EN_PROCESO'
    new_status = "ACEPTADO"  # Placeholder logic: Assume success for now

    print(f"New status for {track_id}: {new_status}")

    # 2. Update DynamoDB
    if new_status != "EN_PROCESO":
        SUBSCRIPTIONS_TABLE.update_item(
            Key={"tenantId": tenant_id, "subscriptionId": sub_id},
            UpdateExpression="set dteSiiStatus = :s, dteLastSync = :now",
            ExpressionAttributeValues={
                ":s": new_status,
                ":now": datetime.utcnow().isoformat() + "Z",
            },
        )
        print(f"Updated {sub_id} to status {new_status}")
    else:
        print(f"Document {sub_id} is still being processed by SII.")
