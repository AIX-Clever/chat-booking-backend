
import boto3
import os
import sys
from datetime import datetime, timedelta
from typing import List

# Add project root to path to import modules
sys.path.append(os.getcwd())

# Mock auth services to avoid dependency issues
from unittest.mock import MagicMock
sys.modules['shared.infrastructure.google_auth_service'] = MagicMock()
sys.modules['shared.infrastructure.microsoft_auth_service'] = MagicMock()

# Import Service and Entities
from availability.service import AvailabilityService
from shared.domain.entities import TenantId, ProviderAvailability, TimeRange
# We need to mock repositories or implement simple ones that use boto3
from shared.domain.repositories import (
    IAvailabilityRepository,
    IBookingRepository,
    IServiceRepository,
    IProviderRepository,
    IProviderIntegrationRepository,
)

# Mock/Stub Repositories
class BotoAvailabilityRepo(IAvailabilityRepository):
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table('ChatBooking-ProviderAvailability')
        
    def get_provider_availability(self, tenant_id, provider_id):
        pk = f"{tenant_id}#{provider_id}"
        response = self.table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('tenantId_providerId').eq(pk)
        )
        items = response.get('Items', [])
        availabilities = []
        for item in items:
            # Convert to Entities
            time_ranges = [TimeRange(tr['startTime'], tr['endTime']) for tr in item.get('timeRanges', [])]
            breaks = [TimeRange(br['startTime'], br['endTime']) for br in item.get('breaks', [])]
            
            availabilities.append(ProviderAvailability(
                tenant_id=tenant_id,
                provider_id=provider_id,
                day_of_week=item['dayOfWeek'],
                time_ranges=time_ranges,
                breaks=breaks,
                exceptions=[] # Simplify
            ))
        return availabilities

    def save_availability(self, availability): pass
    def get_provider_exceptions(self, tenant_id, provider_id): return []
    def save_provider_exceptions(self, tenant_id, provider_id, exceptions): pass

class MockBookingRepo(IBookingRepository):
    def save(self, booking): pass
    def get_by_id(self, tenant_id, booking_id): return None
    def list_by_provider(self, tenant_id, provider_id, start, end): return [] # Return empty for now
    def list_by_client(self, client_email): return []
    def get_by_conversation(self, conversation_id): return None
    def update_status(self, tenant_id, booking_id, status): pass
    def list_by_customer_email(self, email): return []
    def update(self, booking): pass

class MockServiceRepo(IServiceRepository):
    def get_by_id(self, tenant_id, service_id):
        # Stub
        from shared.domain.entities import Service
        return Service(
            tenant_id=tenant_id,
            service_id=service_id,
            name="Test Service",
            description=None,
            category="cat_1",
            duration_minutes=15,
            price=0,
            active=True,
            required_room_ids=[]
        )
    def list_all(self, tenant_id): return []
    def save(self, service): pass
    def delete(self, tenant_id, service_id): pass
    def list_by_tenant(self, tenant_id): return []
    def search(self, tenant_id, query): return []

class MockProviderRepo(IProviderRepository):
    def get_by_id(self, tenant_id, provider_id):
        from shared.domain.entities import Provider
        return Provider(
            tenant_id=tenant_id,
            provider_id=provider_id,
            name="Lucy",
            bio=None,
            service_ids=["svc_1", "svc_0cc8a65b"],
            timezone="America/Santiago",
            active=True
        )
    def list_all(self, tenant_id): return []
    def save(self, provider): pass
    def delete(self, tenant_id, provider_id): pass
    def list_by_service(self, tenant_id, service_id): return []
    def find_by_slug(self, tenant_id, slug): return None
    def list_by_tenant(self, tenant_id): return []

class MockProviderIntegrationRepo(IProviderIntegrationRepository):
    def get_google_creds(self, tenant_id, provider_id): return None
    def save_google_creds(self, tenant_id, provider_id, creds): pass
    def get_microsoft_creds(self, tenant_id, provider_id): return None
    def save_microsoft_creds(self, tenant_id, provider_id, creds): pass
    def delete_google_creds(self, tenant_id, provider_id): pass
    def delete_microsoft_creds(self, tenant_id, provider_id): pass


def run_test():
    # Setup
    avail_repo = BotoAvailabilityRepo()
    service = AvailabilityService(
        availability_repo=avail_repo,
        booking_repo=MockBookingRepo(),
        service_repo=MockServiceRepo(),
        provider_repo=MockProviderRepo(),
        provider_integration_repo=MockProviderIntegrationRepo()
    )

    tenant_id = "1109a560"
    provider_id = "pro_ce496733"
    service_id = "svc_0cc8a65b"
    
    # Date range: Tomorrow full day
    tomorrow = datetime.now() + timedelta(days=1)
    from_date = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    to_date = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999)

    print(f"Fetching slots for {provider_id} on {from_date.date()}...")
    
    try:
        slots = service.get_available_slots(
            tenant_id, service_id, provider_id, from_date, to_date
        )
        
        print(f"Found {len(slots)} slots.")
        for s in slots:
            print(f"{s.start.isoformat()} - {s.end.isoformat()}")
            
        # Check duplicates
        seen = set()
        duplicates = []
        for s in slots:
            key = s.start.isoformat()
            if key in seen:
                duplicates.append(key)
            seen.add(key)
            
        if duplicates:
            print(f"FAIL: Found {len(duplicates)} duplicate slots!")
            print(duplicates)
        else:
            print("SUCCESS: No duplicates found.")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
