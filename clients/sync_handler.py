import os
import boto3
import uuid
import logging
from datetime import datetime

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
CLIENTS_TABLE_NAME = os.environ.get('CLIENTS_TABLE')
AUDIT_LOGS_TABLE_NAME = os.environ.get('CLIENT_AUDIT_LOGS_TABLE')

clients_table = dynamodb.Table(CLIENTS_TABLE_NAME)
audit_table = dynamodb.Table(AUDIT_LOGS_TABLE_NAME)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def to_iso_string(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def lambda_handler(event, context):
    """
    Triggered by DynamoDB Stream on Bookings table (INSERT only)
    """
    logger.info(f"Processing {len(event['Records'])} stream records")

    for record in event['Records']:
        if record['eventName'] != 'INSERT':
            continue

        try:
            # Extract new booking image
            new_image = record['dynamodb']['NewImage']

            # Unmarshal DynamoDB JSON to plain dict
            booking = _unmarshal(new_image)
            tenant_id = booking.get('tenantId')
            
            # Extract names with fallback for legacy clientName
            client_name = booking.get('clientName') or booking.get('customerName') or ''
            first_name = booking.get('clientFirstName') or booking.get('customerFirstName')
            last_name = booking.get('clientLastName') or booking.get('customerLastName')

            if not first_name and client_name:
                name_parts = client_name.split(' ', 1)
                first_name = name_parts[0]
                last_name = name_parts[1] if len(name_parts) > 1 else ''

            # Map flattened fields to customer_info structure
            customer_info = {
                'email': booking.get('clientEmail') or booking.get('customerEmail'),
                'firstName': first_name or '',
                'lastName': last_name or '',
                'phone': booking.get('clientPhone') or booking.get('customerPhone')
            }

            email = customer_info.get('email')
            booking_id = booking.get('bookingId')

            if not email:
                logger.warning(
                    f"Booking {booking_id} has no email. Skipping sync."
                )
                continue

            _sync_client(tenant_id, booking_id, customer_info)

        except Exception as e:
            logger.error(f"Error processing record: {str(e)}", exc_info=True)


def _sync_client(tenant_id, booking_id, customer_info):
    email = customer_info.get('email')
    given_name = customer_info.get('firstName', '').strip()
    family_name = customer_info.get('lastName', '').strip()
    phone = customer_info.get('phone')

    # 1. Lookup client by email GSI
    response = clients_table.query(
        IndexName='email-index',
        KeyConditionExpression=boto3.dynamodb.conditions.Key('tenantId').eq(tenant_id) &
        boto3.dynamodb.conditions.Key('email').eq(email)
    )

    timestamp = to_iso_string(datetime.utcnow())

    if response.get('Count', 0) > 0:
        # Existing client: we pass full_name here to be evaluated in _update_if_changed 
        _update_if_changed(tenant_id, response['Items'][0], customer_info, booking_id, timestamp)
    else:
        # New client
        client_id = str(uuid.uuid4())
        logger.info(f"Creating new client {client_id} for email {email}")

        new_client = {
            'tenantId': tenant_id,
            'id': client_id,
            'email': email,
            'names': {
                'given': given_name,
                'family': family_name
            },
            'contactInfo': [
                {'system': 'email', 'value': email},
                {'system': 'phone', 'value': phone} if phone else None
            ],
            'createdAt': timestamp,
            'updatedAt': timestamp,
            'source': 'BOOKING',
            'identifierValue': 'PENDING',  # Placeholder for RUT/CPF
            'identifiers': []  # Required by GraphQL schema
        }
        # Clean None from lists
        new_client['contactInfo'] = [c for c in new_client['contactInfo'] if c]

        clients_table.put_item(Item=new_client)

        # Audit log for creation
        _record_audit(
            tenant_id, client_id, 'ALL', None, 'CREATED',
            'BOOKING_SYNC', booking_id, timestamp
        )


def _update_if_changed(tenant_id, client, customer_info, booking_id, timestamp):
    client_id = client['id']
    updates = {}
    changes = []

    # 1. Check Name
    new_given = customer_info.get('firstName', '').strip()
    new_family = customer_info.get('lastName', '').strip()
        
    if new_given or new_family:
        old_given = client.get('names', {}).get('given', '')
        old_family = client.get('names', {}).get('family', '')
        
        name_updated = False
        names_obj = client.get('names', {})
        
        if new_given and new_given != old_given:
            names_obj['given'] = new_given
            changes.append(('names.given', old_given, new_given))
            name_updated = True
            
        if new_family and new_family != old_family:
            names_obj['family'] = new_family
            changes.append(('names.family', old_family, new_family))
            name_updated = True
            
        if name_updated:
            updates['names'] = names_obj

    # 2. Check Phone
    new_phone = customer_info.get('phone')
    old_phone = next(
        (c['value'] for c in client.get('contactInfo', []) if c['system'] == 'phone'),
        None
    )
    if new_phone and new_phone != old_phone:
        # Update contactInfo list
        new_contact_info = [
            c for c in client.get('contactInfo', []) if c['system'] != 'phone'
        ]
        new_contact_info.append({'system': 'phone', 'value': new_phone})
        updates['contactInfo'] = new_contact_info
        changes.append(('phone', old_phone, new_phone))

    if updates:
        logger.info(f"Updating client {client_id} with {len(changes)} changes")

        # Build update expression
        update_expr = "SET updatedAt = :ts"
        attr_values = {":ts": timestamp}

        for i, (field, old, new) in enumerate(changes):
            # clean_field = field.replace('.', '_') # Unused
            update_expr += f", {field} = :val{i}"
            # Handles nested given name
            attr_values[f":val{i}"] = updates.get(field.split('.')[0], new)

        # Simplest way: put_item with merged data since we already have the full item
        merged_item = {**client, **updates, 'updatedAt': timestamp}
        clients_table.put_item(Item=merged_item)

        # Record audits
        for field, old, new in changes:
            _record_audit(
                tenant_id, client_id, field, old, new,
                'BOOKING_SYNC', booking_id, timestamp
            )


def _record_audit(tenant_id, client_id, field, old, new, source, source_id, timestamp):
    audit_item = {
        'tenantId': tenant_id,
        'clientIdAndTimestamp': f"{client_id}#{timestamp}#{str(uuid.uuid4())[:8]}",
        'clientId': client_id,
        'field': field,
        'oldValue': old if old is not None else "",
        'newValue': new,
        'source': source,
        'sourceId': source_id,
        'changedBy': 'system',
        'timestamp': timestamp
    }
    audit_table.put_item(Item=audit_item)


def _unmarshal(image):
    """Deeply unmarshal DynamoDB Image to plain dict/list"""
    from boto3.dynamodb.types import TypeDeserializer
    deserializer = TypeDeserializer()
    return {k: deserializer.deserialize(v) for k, v in image.items()}
