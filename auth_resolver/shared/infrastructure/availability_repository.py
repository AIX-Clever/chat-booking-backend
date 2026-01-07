"""
Availability Repository Implementation (Infrastructure)

Missing implementation for ProviderAvailability repository
"""

import os
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
            table_name or os.environ.get('AVAILABILITY_TABLE', 'ChatBooking-Availability')
        )

    def get_provider_availability(
        self,
        tenant_id: TenantId,
        provider_id: str
    ) -> List[ProviderAvailability]:
        """Get weekly availability for provider (excludes EXCEPTIONS item)"""
        try:
            pk = f"{tenant_id}#{provider_id}"
            response = self.table.query(
                KeyConditionExpression=Key('tenantId_providerId').eq(pk)
            )
            
            # Filter out EXCEPTIONS item (it's stored separately)
            items = [item for item in response.get('Items', []) 
                     if item.get('dayOfWeek') != 'EXCEPTIONS']
            
            return [self._item_to_entity(item) for item in items]
        except ClientError as e:
            print(f"Error getting availability: {e}")
            return []

    def get_provider_exceptions(
        self,
        tenant_id: TenantId,
        provider_id: str
    ) -> List[str]:
        """Get exception dates for provider (stored in dedicated EXCEPTIONS item)"""
        try:
            pk = f"{tenant_id}#{provider_id}"
            response = self.table.get_item(
                Key={
                    'tenantId_providerId': pk,
                    'dayOfWeek': 'EXCEPTIONS'
                }
            )
            
            item = response.get('Item')
            if item:
                return item.get('exceptionDates', [])
            return []
        except ClientError as e:
            print(f"Error getting exceptions: {e}")
            return []

    def save_provider_exceptions(
        self,
        tenant_id: TenantId,
        provider_id: str,
        exception_dates: List[str]
    ) -> None:
        """Save exception dates for provider in dedicated EXCEPTIONS item"""
        pk = f"{tenant_id}#{provider_id}"
        
        item = {
            'tenantId_providerId': pk,
            'dayOfWeek': 'EXCEPTIONS',  # Special SK for exceptions
            'exceptionDates': exception_dates
        }
        
        self.table.put_item(Item=item)

    def save_availability(self, availability: ProviderAvailability) -> None:
        """Persist availability schedule for a specific day"""
        pk = f"{availability.tenant_id}#{availability.provider_id}"
        
        item = {
            'tenantId_providerId': pk,
            'dayOfWeek': availability.day_of_week,
            'timeRanges': [
                {'startTime': tr.start_time, 'endTime': tr.end_time}
                for tr in availability.time_ranges
            ],
            'breaks': [
                {'startTime': br.start_time, 'endTime': br.end_time}
                for br in availability.breaks
            ]
            # Note: exceptions are NOT stored per-day anymore
        }
        
        self.table.put_item(Item=item)

    def _item_to_entity(self, item: dict) -> ProviderAvailability:
        """Convert DynamoDB item to entity"""
        pk_parts = item['tenantId_providerId'].split('#')
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
            day_of_week=item['dayOfWeek'],
            time_ranges=time_ranges,
            breaks=breaks,
            exceptions=[]  # Exceptions are now fetched separately
        )

