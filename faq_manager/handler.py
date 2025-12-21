import json
import os
import boto3 # type: ignore
import logging
import uuid
import datetime
from botocore.exceptions import ClientError # type: ignore

# Initialize logger
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
faqs_table = dynamodb.Table(os.environ['FAQS_TABLE'])

from shared.utils import extract_appsync_event, success_response, error_response
from shared.domain.entities import TenantId

def lambda_handler(event, context):
    """
    Handler for FAQ CRUD operations via AppSync
    """
    logger.info(f"Event: {json.dumps(event)}")
    
    try:
        field_name, tenant_id_str, arguments = extract_appsync_event(event) # arguments is the input_data
        tenant_id = tenant_id_str

        if field_name == 'listFAQs':
            return list_faqs(tenant_id)
        elif field_name == 'createFAQ':
            # extract_appsync_event returns the input map as the 3rd arg. 
            # Check if arguments needs 'input' key or is the input itself. 
            # In catalog/handler it returns input_data.
            # But the original code looked at arguments.get('input').
            # extract_appsync_event usually returns 'arguments' or 'arguments['input']'.
            # Let's trust extract_appsync_event standardization.
            # If arguments is already the input payload:
            return create_faq(tenant_id, arguments)
        elif field_name == 'updateFAQ':
            return update_faq(tenant_id, arguments)
        elif field_name == 'deleteFAQ':
            # For delete, arguments usually contains { 'faqId': ... }
            return delete_faq(tenant_id, arguments.get('faqId'))
        else:
            raise Exception(f"Unknown field name: {field_name}")
            
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        # Raise e to return error to AppSync, or use error_response if we change return type signature
        raise e

def list_faqs(tenant_id):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    response = faqs_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('tenantId').eq(tenant_id)
    )
    return response.get('Items', [])

def create_faq(tenant_id, input_data):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    faq_id = str(uuid.uuid4())
    
    item = {
        'tenantId': tenant_id,
        'faqId': faq_id,
        'question': input_data['question'],
        'answer': input_data['answer'],
        'category': input_data.get('category', 'General'),
        'active': input_data.get('active', True)
    }
    
    faqs_table.put_item(Item=item)
    return item

def update_faq(tenant_id, input_data):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    faq_id = input_data['faqId']
    
    # Build update expression
    update_parts = []
    expression_values = {}
    expression_names = {}
    
    fields = ['question', 'answer', 'category', 'active']
    for field in fields:
        if field in input_data:
            update_parts.append(f"#{field} = :{field}")
            expression_values[f":{field}"] = input_data[field]
            expression_names[f"#{field}"] = field
            
    if not update_parts:
        return get_faq(tenant_id, faq_id)

    update_expression = "SET " + ", ".join(update_parts)
    
    response = faqs_table.update_item(
        Key={
            'tenantId': tenant_id,
            'faqId': faq_id
        },
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
        ReturnValues="ALL_NEW"
    )
    
    return response.get('Attributes')

def delete_faq(tenant_id, faq_id):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    # Get item first to return it
    item = get_faq(tenant_id, faq_id)
    if not item:
        raise Exception("FAQ not found")
        
    faqs_table.delete_item(
        Key={
            'tenantId': tenant_id,
            'faqId': faq_id
        }
    )
    return item

def get_faq(tenant_id, faq_id):
    if not tenant_id:
        raise Exception("Unauthorized: Missing tenantId")
        
    response = faqs_table.get_item(
        Key={
            'tenantId': tenant_id,
            'faqId': faq_id
        }
    )
    return response.get('Item')
