"""
Availability Repository Implementation (Infrastructure)

Missing implementation for ProviderAvailability repository
"""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import boto3
from typing import List, Optional
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from shared.domain.entities import TenantId, ProviderAvailability, TimeRange
from shared.domain.repositories import IAvailabilityRepository


class DynamoDBAvailabilityRepository(IAvailabilityRepository):
    """DynamoDB implementation of Availability repository"""

    def __init__(self, table_name: Optional[str] = None):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(
            table_name or os.environ.get('DYNAMODB_PROVIDER_AVAILABILITY_TABLE', 'ProviderAvailability')
        )

    def get_provider_availability(
        self,
        tenant_id: TenantId,
        provider_id: str
    ) -> List[ProviderAvailability]:
        """Get weekly availability for provider"""
        try:
            pk = f"{tenant_id}#{provider_id}"
            response = self.table.query(
                KeyConditionExpression=Key('PK').eq(pk)
            )
            
            return [self._item_to_entity(item) for item in response.get('Items', [])]
        except ClientError as e:
            print(f"Error getting availability: {e}")
            return []

    def save_availability(self, availability: ProviderAvailability) -> None:
        """Persist availability schedule"""
        pk = f"{availability.tenant_id}#{availability.provider_id}"
        
        item = {
            'PK': pk,
            'SK': availability.day_of_week,
            'timeRanges': [
                {'startTime': tr.start_time, 'endTime': tr.end_time}
                for tr in availability.time_ranges
            ],
            'breaks': [
                {'startTime': br.start_time, 'endTime': br.end_time}
                for br in availability.breaks
            ],
            'exceptions': availability.exceptions
        }
        
        self.table.put_item(Item=item)

    def _item_to_entity(self, item: dict) -> ProviderAvailability:
        """Convert DynamoDB item to entity"""
        pk_parts = item['PK'].split('#')
        tenant_id = TenantId(pk_parts[0])
        provider_id = pk_parts[1]
        
        time_ranges = [
            TimeRange(tr['startTime'], tr['endTime'])
            for tr in item.get('timeRanges', [])
        ]
        
        breaks = [
            TimeRange(br['startTime'], br['endTime'])
            for br in item.get('breaks', [])
        ]
        
        return ProviderAvailability(
            tenant_id=tenant_id,
            provider_id=provider_id,
            day_of_week=item['SK'],
            time_ranges=time_ranges,
            breaks=breaks,
            exceptions=item.get('exceptions', [])
        )
