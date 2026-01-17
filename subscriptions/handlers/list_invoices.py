import json
import os
import boto3
from boto3.dynamodb.conditions import Key
from shared.utils import lambda_response, error_response, success_response  
from shared.decorators import require_tenant_context
from shared.subscriptions.config import SubscriptionConfig

dynamodb = boto3.resource('dynamodb')
SUBSCRIPTIONS_TABLE = dynamodb.Table(SubscriptionConfig.SUBSCRIPTIONS_TABLE)

@require_tenant_context
def lambda_handler(event, context):
    """
    List invoices (past payments) for a tenant.
    Query pattern: PK=tenant_id, SK begins_with "PAYMENT#"
    """
    try:
        tenant_id = event['tenant_id']
        
        response = SUBSCRIPTIONS_TABLE.query(
            KeyConditionExpression=Key('tenantId').eq(tenant_id) & Key('subscriptionId').begins_with('PAYMENT#')
        )
        
        items = response.get('Items', [])
        invoices = []
        
        for item in items:
            # item structure matches Payment Audit entity
            # SK: PAYMENT#{id}
            # amount, status, date, etc.
            
            payment_id = item['subscriptionId'].split('#')[1]
            
            # Map to GraphQL Invoice type
            invoice = {
                'invoiceId': payment_id,
                'tenantId': tenant_id,
                'amount': float(item.get('amount', 0)),
                'currency': item.get('currency', 'CLP'),
                'status': item.get('status', 'PENDING').upper(),
                'date': item.get('processedAt') or item.get('createdAt'), # ISO String
                'pdfUrl': item.get('pdfUrl'),
                'metadata': json.dumps(item.get('metadata', {})) if item.get('metadata') else None
            }
            invoices.append(invoice)
            
        # Sort by date desc (if not already sorted by SK roughly)
        invoices.sort(key=lambda x: x['date'], reverse=True)
            
        return invoices # GraphQL Resolver expects direct list or simple object if using response template
        
    except Exception as e:
        print(f"Error listing invoices: {str(e)}")
        raise e
