"""
DynamoDB Availability Repository Implementation
"""

import boto3
import os
from typing import List, Optional
from datetime import datetime
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..domain.entities import TenantId, ProviderAvailability, TimeRange
from ..domain.repositories import IAvailabilityRepository


class DynamoDBAvailabilityRepository(IAvailabilityRepository):
    """DynamoDB implementation of Availability repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('DYNAMODB_AVAILABILITY_TABLE', 'Availability')
        )

    def get_provider_availability(
        self,
        tenant_id: TenantId,
        provider_id: str
    ) -> List[ProviderAvailability]:
        try:
            pk = f"{tenant_id}#{provider_id}"
            response = self.table.query(
                KeyConditionExpression=Key('PK').eq(pk)
            )
            
            items = response.get('Items', [])
            availability_list = []
            
            for item in items:
                # filter out exception items if they are mixed (assuming structure)
                if item['SK'].startswith('EXCEPTION'):
                    continue
                    
                availability_list.append(self._item_to_entity(item))
                
            return availability_list
        except ClientError as e:
            print(f"Error getting availability: {e}")
            return []

    def save_availability(self, availability: ProviderAvailability) -> None:
        item = {
            'PK': f"{availability.tenant_id}#{availability.provider_id}",
            'SK': f"DAY#{availability.day_of_week}",
            'tenantId': str(availability.tenant_id),
            'providerId': availability.provider_id,
            'dayOfWeek': availability.day_of_week,
            'timeRanges': [
                {'start': tr.start_time, 'end': tr.end_time}
                for tr in availability.time_ranges
            ],
            'breaks': [
                {'start': br.start_time, 'end': br.end_time}
                for br in availability.breaks
            ],
            'updatedAt': datetime.now().isoformat()
        }
        
        self.table.put_item(Item=item)

    def get_provider_exceptions(self, tenant_id: TenantId, provider_id: str) -> List[str]:
        try:
            response = self.table.get_item(
                Key={
                    'PK': f"{tenant_id}#{provider_id}",
                    'SK': 'EXCEPTIONS'
                }
            )
            item = response.get('Item')
            
            if not item:
                return []

            return item.get('dates', [])
        except ClientError as e:
            print(f"Error getting exceptions: {e}")
            return []

    def save_provider_exceptions(self, tenant_id: TenantId, provider_id: str, exceptions: List[str]) -> None:
        item = {
            'PK': f"{tenant_id}#{provider_id}",
            'SK': 'EXCEPTIONS',
            'tenantId': str(tenant_id),
            'providerId': provider_id,
            'dates': exceptions,
            'updatedAt': datetime.now().isoformat()
        }
        
        self.table.put_item(Item=item)

    def _item_to_entity(self, item: dict) -> ProviderAvailability:
        return ProviderAvailability(
            tenant_id=TenantId(item['tenantId']),
            provider_id=item['providerId'],
            day_of_week=item['dayOfWeek'],
            time_ranges=[
                TimeRange(tr['start'], tr['end'])
                for tr in item.get('timeRanges', [])
            ],
            breaks=[
                TimeRange(br['start'], br['end'])
                for br in item.get('breaks', [])
            ],
            exceptions=[] # Exceptions stored separately
        )
