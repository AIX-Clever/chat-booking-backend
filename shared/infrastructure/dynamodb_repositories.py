"""
DynamoDB Repository Implementation (Infrastructure Adapter)

Implements repository interfaces using AWS DynamoDB
"""

import boto3
import os
import hashlib
from typing import List, Optional
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from ..domain.entities import (
    Tenant, TenantId, Service, Provider, ProviderAvailability,
    Booking, Conversation, ApiKey, TimeSlot, CustomerInfo,
    BookingStatus, PaymentStatus, ConversationState, TenantStatus, TenantPlan,
    TimeRange, FAQ, Workflow, WorkflowStep, Room
)
from ..domain.repositories import (
    ITenantRepository, IApiKeyRepository, IServiceRepository,
    IProviderRepository, IAvailabilityRepository, IBookingRepository,
    IConversationRepository, IFAQRepository, IRoomRepository
)
from ..domain.exceptions import (
    EntityNotFoundError, ConflictError
)


class DynamoDBTenantRepository(ITenantRepository):
    """DynamoDB implementation of Tenant repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('TENANTS_TABLE', 'ChatBooking-Tenants')
        )

    def get_by_id(self, tenant_id: TenantId) -> Optional[Tenant]:
        try:
            response = self.table.get_item(Key={'tenantId': str(tenant_id)})
            item = response.get('Item')
            
            if not item:
                return None

            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting tenant: {e}")
            return None

    def save(self, tenant: Tenant) -> None:
        item = {
            'tenantId': str(tenant.tenant_id),
            'name': tenant.name,
            'slug': tenant.slug,
            'status': tenant.status.value,
            'plan': tenant.plan.value,
            'ownerUserId': tenant.owner_user_id,
            'billingEmail': tenant.billing_email,
            'settings': tenant.settings,
            'createdAt': tenant.created_at.isoformat()
        }
        
        self.table.put_item(Item=item)

    def _item_to_entity(self, item: dict) -> Tenant:
        return Tenant(
            tenant_id=TenantId(item['tenantId']),
            name=item['name'],
            slug=item.get('slug', ''),
            status=TenantStatus(item['status']),
            plan=TenantPlan(item['plan']),
            owner_user_id=item['ownerUserId'],
            billing_email=item.get('billingEmail'),
            settings=item.get('settings', {}),
            created_at=datetime.fromisoformat(item['createdAt'])
        )


class DynamoDBApiKeyRepository(IApiKeyRepository):
    """DynamoDB implementation of API Key repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('API_KEYS_TABLE', 'ChatBooking-ApiKeys')
        )

    def find_by_hash(self, api_key_hash: str) -> Optional[ApiKey]:
        try:
            response = self.table.query(
                IndexName='GSI1',
                KeyConditionExpression=Key('apiKeyHash').eq(api_key_hash)
            )
            
            items = response.get('Items', [])
            if not items:
                return None

            return self._item_to_entity(items[0])
        except ClientError as e:
            print(f"Error finding API key: {e}")
            return None

    def save(self, api_key: ApiKey) -> None:
        item = {
            'tenantId': str(api_key.tenant_id),
            'apiKeyId': api_key.api_key_id,
            'apiKeyHash': api_key.api_key_hash,
            'status': api_key.status,
            'allowedOrigins': api_key.allowed_origins,
            'rateLimit': api_key.rate_limit,
            'createdAt': api_key.created_at.isoformat()
        }
        
        if api_key.name:
            item['name'] = api_key.name
        if api_key.key_preview:
            item['keyPreview'] = api_key.key_preview
        if api_key.last_used_at:
            item['lastUsedAt'] = api_key.last_used_at.isoformat()

        self.table.put_item(Item=item)

    def list_by_tenant(self, tenant_id: TenantId) -> List[ApiKey]:
        try:
            response = self.table.query(
                KeyConditionExpression=Key('tenantId').eq(str(tenant_id))
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing API keys: {e}")
            return []

    def _item_to_entity(self, item: dict) -> ApiKey:
        return ApiKey(
            api_key_id=item['apiKeyId'],
            tenant_id=TenantId(item['tenantId']),
            api_key_hash=item['apiKeyHash'],
            status=item['status'],
            name=item.get('name'),
            key_preview=item.get('keyPreview'),
            allowed_origins=item.get('allowedOrigins', []),
            rate_limit=item.get('rateLimit', 100),
            created_at=datetime.fromisoformat(item['createdAt']),
            last_used_at=datetime.fromisoformat(item['lastUsedAt']) if item.get('lastUsedAt') else None
        )


class DynamoDBServiceRepository(IServiceRepository):
    """DynamoDB implementation of Service repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('SERVICES_TABLE', 'ChatBooking-Services')
        )

    def get_by_id(self, tenant_id: TenantId, service_id: str) -> Optional[Service]:
        try:
            response = self.table.get_item(
                Key={'tenantId': str(tenant_id), 'serviceId': service_id}
            )
            item = response.get('Item')
            
            if not item:
                return None

            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting service: {e}")
            return None

    def list_by_tenant(self, tenant_id: TenantId) -> List[Service]:
        try:
            response = self.table.query(
                KeyConditionExpression=Key('tenantId').eq(str(tenant_id))
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing services: {e}")
            return []

    def search(self, tenant_id: TenantId, query: Optional[str] = None) -> List[Service]:
        services = self.list_by_tenant(tenant_id)
        
        if not query:
            return [s for s in services if s.active]
        
        query_lower = query.lower()
        return [
            s for s in services
            if s.active and (
                query_lower in s.name.lower() or
                (s.description and query_lower in s.description.lower()) or
                query_lower in s.category.lower()
            )
        ]

    def save(self, service: Service) -> None:
        item = {
            'tenantId': str(service.tenant_id),
            'serviceId': service.service_id,
            'name': service.name,
            'category': service.category,
            'durationMinutes': service.duration_minutes,
            'active': service.active
        }
        
        if service.required_room_ids:
             item['requiredRoomIds'] = service.required_room_ids
        
        if service.location_type:
             item['locationType'] = service.location_type
        
        if service.description:
            item['description'] = service.description
        if service.price is not None:
            item['price'] = str(service.price)  # Store as string to preserve precision

        self.table.put_item(Item=item)

    def delete(self, tenant_id: TenantId, service_id: str) -> None:
        self.table.delete_item(
            Key={'tenantId': str(tenant_id), 'serviceId': service_id}
        )

    def _item_to_entity(self, item: dict) -> Service:
        return Service(
            service_id=item['serviceId'],
            tenant_id=TenantId(item['tenantId']),
            name=item['name'],
            description=item.get('description'),
            category=item['category'],
            duration_minutes=int(item['durationMinutes']),
            price=float(item['price']) if item.get('price') else None,
            required_room_ids=item.get('requiredRoomIds'),
            location_type=item.get('locationType', ["PHYSICAL"]),
            active=item.get('active', True)
        )


class DynamoDBProviderRepository(IProviderRepository):
    """DynamoDB implementation of Provider repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('PROVIDERS_TABLE', 'ChatBooking-Providers')
        )

    def get_by_id(self, tenant_id: TenantId, provider_id: str) -> Optional[Provider]:
        try:
            response = self.table.get_item(
                Key={'tenantId': str(tenant_id), 'providerId': provider_id}
            )
            item = response.get('Item')
            
            if not item:
                return None

            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting provider: {e}")
            return None

    def list_by_tenant(self, tenant_id: TenantId) -> List[Provider]:
        try:
            response = self.table.query(
                KeyConditionExpression=Key('tenantId').eq(str(tenant_id))
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing providers: {e}")
            return []

    def list_by_service(self, tenant_id: TenantId, service_id: str) -> List[Provider]:
        providers = self.list_by_tenant(tenant_id)
        return [p for p in providers if p.can_provide_service(service_id)]

    def save(self, provider: Provider) -> None:
        item = {
            'tenantId': str(provider.tenant_id),
            'providerId': provider.provider_id,
            'name': provider.name,
            'services': provider.service_ids,
            'timezone': provider.timezone,
            'metadata': provider.metadata,
            'active': provider.active
        }
        
        if provider.bio:
            item['bio'] = provider.bio

        self.table.put_item(Item=item)

    def delete(self, tenant_id: TenantId, provider_id: str) -> None:
        self.table.delete_item(
            Key={'tenantId': str(tenant_id), 'providerId': provider_id}
        )

    def _item_to_entity(self, item: dict) -> Provider:
        return Provider(
            provider_id=item['providerId'],
            tenant_id=TenantId(item['tenantId']),
            name=item['name'],
            bio=item.get('bio'),
            service_ids=item.get('services', []),
            timezone=item['timezone'],
            metadata=item.get('metadata', {}),
            active=item.get('active', True)
        )


class DynamoDBBookingRepository(IBookingRepository):
    """DynamoDB implementation of Booking repository with overbooking prevention"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('BOOKINGS_TABLE', 'ChatBooking-Bookings')
        )

    def get_by_id(self, tenant_id: TenantId, booking_id: str) -> Optional[Booking]:
        # Need to scan with filter since bookingId is not part of key
        try:
            response = self.table.scan(
                FilterExpression=Attr('bookingId').eq(booking_id) & Attr('tenantId').eq(str(tenant_id))
            )
            
            items = response.get('Items', [])
            if not items:
                return None

            return self._item_to_entity(items[0])
        except ClientError as e:
            print(f"Error getting booking: {e}")
            return None

    def list_by_provider(
        self,
        tenant_id: TenantId,
        provider_id: str,
        from_date: datetime,
        to_date: datetime
    ) -> List[Booking]:
        try:
            # Query using Global Secondary Index (GSI)
            response = self.table.query(
                IndexName='providerId-start-index',
                KeyConditionExpression=
                    Key('tenantId_providerId').eq(f"{tenant_id}_{provider_id}") &
                    Key('start').between(from_date.isoformat(), to_date.isoformat())
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing bookings: {e}")
            return []

    def list_by_customer_email(self, tenant_id: TenantId, customer_email: str) -> List[Booking]:
        try:
            response = self.table.query(
                IndexName='clientEmail-index',
                KeyConditionExpression=
                    Key('tenantId').eq(str(tenant_id)) &
                    Key('clientEmail').eq(customer_email)
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing customer bookings: {e}")
            return []
        try:
            # Generate customer_id from email to query GSI
            # Using MD5 for deterministic ID generation (same as create_booking)
            customer_id = hashlib.md5(customer_email.lower().strip().encode()).hexdigest()
            
            gsi_pk = f"{tenant_id}#{customer_id}"
            response = self.table.query(
                IndexName='GSI1',
                KeyConditionExpression=Key('GSI1PK').eq(gsi_pk)
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing customer bookings: {e}")
            return []

    def save(self, booking: Booking) -> None:
        """Save with conditional check to prevent overbooking"""
        pk = f"{booking.tenant_id}#{booking.provider_id}"
        sk = booking.start_time.isoformat()
        
        item = {
            'PK': pk,
            'SK': sk,
            'bookingId': booking.booking_id,
            'tenantId': str(booking.tenant_id),
            'serviceId': booking.service_id,
            'providerId': booking.provider_id,
            'roomId': booking.room_id,
            # GSI Attributes
            'tenantId_providerId': f"{str(booking.tenant_id)}_{booking.provider_id}",
            'start': sk,
            'endTime': booking.end_time.isoformat(),
            'status': booking.status.value,
            'paymentStatus': booking.payment_status.value,
            'createdAt': booking.created_at.isoformat()
        }

        if booking.payment_intent_id:
            item['paymentIntentId'] = booking.payment_intent_id
        if booking.total_amount is not None:
             item['totalAmount'] = str(booking.total_amount) # Store as string for Decimal compatibility
        
        if booking.conversation_id:
            item['conversationId'] = booking.conversation_id
        
        # Add customer info if available
        if booking.customer_info.customer_id:
            item['customerId'] = booking.customer_info.customer_id
            item['GSI1PK'] = f"{booking.tenant_id}#{booking.customer_info.customer_id}"
            item['GSI1SK'] = sk
        if booking.customer_info.name:
            item['clientName'] = booking.customer_info.name
        if booking.customer_info.email:
            item['clientEmail'] = booking.customer_info.email
        if booking.customer_info.phone:
            item['clientPhone'] = booking.customer_info.phone

        try:
            self.table.put_item(
                Item=item,
                ConditionExpression='attribute_not_exists(PK) AND attribute_not_exists(SK)'
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ConflictError(f"Slot at {booking.start_time} is already booked")
            raise

    def update(self, booking: Booking) -> None:
        """Update existing booking (no conditional check)"""
        pk = f"{booking.tenant_id}#{booking.provider_id}"
        sk = booking.start_time.isoformat()
        
        self.table.update_item(
            Key={'PK': pk, 'SK': sk},
            ExpressionAttributeValues={
                ':status': booking.status.value,
                ':payment_status': booking.payment_status.value,
                ':payment_id': booking.payment_intent_id,
                ':total_amount': str(booking.total_amount) if booking.total_amount is not None else None
            }
        )
        # Note: Above update expression is incomplete for new fields.
        # Ideally we should use a more dynamic update builder.
        # For now, let's just create a fuller update expression.
        
        update_expr = 'SET #status = :status, paymentStatus = :payment_status'
        expr_values = {
            ':status': booking.status.value,
            ':payment_status': booking.payment_status.value
        }
        
        if booking.payment_intent_id:
            update_expr += ', paymentIntentId = :payment_id'
            expr_values[':payment_id'] = booking.payment_intent_id
            
        if booking.total_amount is not None:
            update_expr += ', totalAmount = :total_amount'
            expr_values[':total_amount'] = str(booking.total_amount)

        self.table.update_item(
            Key={'PK': pk, 'SK': sk},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues=expr_values
        )

    def _item_to_entity(self, item: dict) -> Booking:
        customer_info = CustomerInfo(
            customer_id=item.get('customerId'),
            name=item.get('clientName') or item.get('customerName'),
            email=item.get('clientEmail') or item.get('customerEmail'),
            phone=item.get('clientPhone') or item.get('customerPhone')
        )
        
        return Booking(
            booking_id=item['bookingId'],
            tenant_id=TenantId(item['tenantId']),
            service_id=item['serviceId'],
            provider_id=item['providerId'],
            room_id=item.get('roomId'),
            customer_info=customer_info,
            start_time=datetime.fromisoformat(item.get('start') or item['SK']),
            end_time=datetime.fromisoformat(item['endTime']),
            status=BookingStatus(item['status']),
            payment_status=PaymentStatus(item.get('paymentStatus', 'NONE')),
            conversation_id=item.get('conversationId'),
            payment_intent_id=item.get('paymentIntentId'),
            total_amount=float(item['totalAmount']) if item.get('totalAmount') else None,
            created_at=datetime.fromisoformat(item['createdAt'])
        )


class DynamoDBConversationRepository(IConversationRepository):
    """DynamoDB implementation of Conversation repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('CONVERSATIONS_TABLE', 'ChatBooking-Conversations')
        )

    def get_by_id(self, tenant_id: TenantId, conversation_id: str) -> Optional[Conversation]:
        try:
            response = self.table.get_item(
                Key={'tenantId': str(tenant_id), 'conversationId': conversation_id}
            )
            item = response.get('Item')
            
            if not item:
                return None

            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting conversation: {e}")
            return None

    def save(self, conversation: Conversation) -> None:
        item = {
            'tenantId': str(conversation.tenant_id),
            'conversationId': conversation.conversation_id,
            'state': conversation.state.value,
            'updatedAt': conversation.updated_at.isoformat(),
            'createdAt': conversation.created_at.isoformat(),
            'context': conversation.context
        }
        
        if conversation.service_id:
            item['serviceId'] = conversation.service_id
        if conversation.provider_id:
            item['providerId'] = conversation.provider_id
        if conversation.slot_start:
            item['slotStart'] = conversation.slot_start.isoformat()
        if conversation.slot_end:
            item['slotEnd'] = conversation.slot_end.isoformat()
        if conversation.booking_id:
            item['bookingId'] = conversation.booking_id
        if conversation.workflow_id:
            item['workflowId'] = conversation.workflow_id
        if conversation.current_step_id:
            item['currentStepId'] = conversation.current_step_id


        # Serialize datetimes and fix floats
        item = self._convert_floats_to_decimals(item)
        self.table.put_item(Item=item)

    def _convert_floats_to_decimals(self, obj):
        """Recursively convert float to Decimal for DynamoDB"""
        from decimal import Decimal
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_floats_to_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimals(v) for v in obj]
        return obj

    def update(self, conversation: Conversation) -> None:
        self.save(conversation)  # DynamoDB put_item is idempotent

    def _item_to_entity(self, item: dict) -> Conversation:
        return Conversation(
            conversation_id=item['conversationId'],
            tenant_id=TenantId(item['tenantId']),
            state=ConversationState(item['state']),
            service_id=item.get('serviceId'),
            provider_id=item.get('providerId'),
            slot_start=datetime.fromisoformat(item['slotStart']) if item.get('slotStart') else None,
            slot_end=datetime.fromisoformat(item['slotEnd']) if item.get('slotEnd') else None,
            booking_id=item.get('bookingId'),
            workflow_id=item.get('workflowId'),
            current_step_id=item.get('currentStepId'),
            context=item.get('context', {}),
            created_at=datetime.fromisoformat(item['createdAt']) if item.get('createdAt') else datetime.fromisoformat(item['updatedAt']),
            updated_at=datetime.fromisoformat(item['updatedAt'])
        )


class DynamoDBFAQRepository(IFAQRepository):
    """DynamoDB implementation of FAQ repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('FAQS_TABLE', 'ChatBooking-FAQs')
        )

    def list_by_tenant(self, tenant_id: TenantId) -> List[FAQ]:
        try:
            response = self.table.query(
                KeyConditionExpression=Key('tenantId').eq(str(tenant_id))
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing FAQs: {e}")
            return []

    def save(self, faq: FAQ) -> None:
        item = {
            'tenantId': str(faq.tenant_id),
            'faqId': faq.faq_id,
            'question': faq.question,
            'answer': faq.answer,
            'category': faq.category,
            'active': faq.active
        }
        
        self.table.put_item(Item=item)

    def delete(self, tenant_id: TenantId, faq_id: str) -> None:
        self.table.delete_item(
            Key={'tenantId': str(tenant_id), 'faqId': faq_id}
        )


    def _item_to_entity(self, item: dict) -> FAQ:
        return FAQ(
            faq_id=item['faqId'],
            tenant_id=TenantId(item['tenantId']),
            question=item['question'],
            answer=item['answer'],
            category=item['category'],
            active=item.get('active', True)
        )


class DynamoDBWorkflowRepository:
    """DynamoDB implementation of Workflow repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('WORKFLOWS_TABLE', 'ChatBooking-Workflows')
        )

    def get_by_id(self, tenant_id: TenantId, workflow_id: str) -> Optional[Workflow]:
        try:
            response = self.table.get_item(
                Key={'tenantId': str(tenant_id), 'workflowId': workflow_id}
            )
            item = response.get('Item')
            if not item:
                return None
            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting workflow: {e}")
            return None

    def list_by_tenant(self, tenant_id: TenantId) -> List[Workflow]:
        try:
            response = self.table.query(
                KeyConditionExpression=Key('tenantId').eq(str(tenant_id))
            )
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing workflows: {e}")
            return []

    def save(self, workflow: Workflow) -> None:
        item = {
            'tenantId': str(workflow.tenant_id),
            'workflowId': workflow.workflow_id,
            'name': workflow.name,
            'description': workflow.description,
            'isActive': workflow.is_active,
            'steps': {sid: self._step_to_dict(s) for sid, s in workflow.steps.items()},
            'metadata': workflow.metadata,
            'createdAt': workflow.created_at.isoformat(),
            'updatedAt': workflow.updated_at.isoformat()
        }
        self.table.put_item(Item=item)

    def _step_to_dict(self, step: WorkflowStep) -> dict:
        return {
            'stepId': step.step_id,
            'type': step.type,
            'content': step.content,
            'next': step.next_step
        }

    def _item_to_entity(self, item: dict) -> Workflow:
        steps_dict = item.get('steps', {})
        steps = {}
        for sid, sdata in steps_dict.items():
            steps[sid] = WorkflowStep(
                step_id=sdata['stepId'],
                type=sdata['type'],
                content=sdata.get('content', {}),
                next_step=sdata.get('next')
            )
            
        return Workflow(
            workflow_id=item['workflowId'],
            tenant_id=TenantId(item['tenantId']),
            name=item['name'],
            description=item.get('description'),
            is_active=item.get('isActive', True),
            steps=steps,
            metadata=item.get('metadata', {}),
            created_at=datetime.fromisoformat(item['createdAt']),
            updated_at=datetime.fromisoformat(item['updatedAt'])
        )


class DynamoDBRoomRepository(IRoomRepository):
    """DynamoDB implementation of Room repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('ROOMS_TABLE', 'ChatBooking-Rooms')
        )

    def list_by_tenant(self, tenant_id: TenantId) -> List[Room]:
        try:
            response = self.table.query(
                IndexName='byTenant',
                KeyConditionExpression=Key('tenantId').eq(str(tenant_id))
            )
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error listing rooms: {e}")
            return []

    def get_by_id(self, tenant_id: TenantId, room_id: str) -> Optional[Room]:
        try:
            response = self.table.get_item(
                Key={'roomId': room_id}
            )
            item = response.get('Item')
            if not item:
                return None
            
            # Verify tenant ownership
            if item['tenantId'] != str(tenant_id):
                return None

            return self._item_to_entity(item)
        except ClientError as e:
            print(f"Error getting room: {e}")
            return None

    def save(self, room: Room) -> None:
        item = {
            'tenantId': str(room.tenant_id),
            'roomId': room.room_id,
            'name': room.name,
            'description': room.description,
            'capacity': room.capacity,
            'status': room.status,
            'isVirtual': room.is_virtual,
            'minDuration': room.min_duration,
            'maxDuration': room.max_duration,
            'operatingHours': room.operating_hours,
            'metadata': room.metadata,
            'createdAt': room.created_at.isoformat(),
            'updatedAt': room.updated_at.isoformat()
        }
        self.table.put_item(Item=item)

    def delete(self, tenant_id: TenantId, room_id: str) -> None:
        self.table.delete_item(
            Key={'roomId': room_id}
        )

    def _item_to_entity(self, item: dict) -> Room:
        return Room(
            room_id=item['roomId'],
            tenant_id=TenantId(item['tenantId']),
            name=item['name'],
            description=item.get('description'),
            capacity=int(item['capacity']) if item.get('capacity') else None,
            status=item['status'],
            is_virtual=item.get('isVirtual', False),
            min_duration=int(item['minDuration']) if item.get('minDuration') else None,
            max_duration=int(item['maxDuration']) if item.get('maxDuration') else None,
            operating_hours=item.get('operatingHours'),
            metadata=item.get('metadata', {}),
            created_at=datetime.fromisoformat(item['createdAt']),
            updated_at=datetime.fromisoformat(item['updatedAt'])
        )
