import sys
import os
from datetime import datetime, date, time
sys.path.append(os.getcwd())
from shared.application.availability_service import AvailabilityService
from shared.domain.entities import TenantId, TimeSlot, ExceptionRule, TimeRange, ProviderAvailability
from zoneinfo import ZoneInfo

class MockService:
    duration_minutes = 60
    service_id = "test_service"

svc = AvailabilityService(None, None, None, None)

day = date(2025, 5, 24) # A Saturday
provider_tz = "America/Santiago"
tz = ZoneInfo(provider_tz)

rule1 = ProviderAvailability(
    tenant_id=TenantId("test"),
    provider_id="test_pro",
    day_of_week="SAT",
    time_ranges=[TimeRange("09:00", "18:00")],
    breaks=[]
)

print("--- EXCEPTION OVERRIDE: Working ONLY 10:00 to 12:00 ---")
ex = ExceptionRule(date="2025-05-24", time_ranges=[TimeRange("10:00", "12:00")])
slots = svc._calculate_day_slots(
    tenant_id=TenantId("123"), day=day, provider_id="321",
    service=MockService(), availability_rules=[rule1], exceptions=[ex],
    bookings=[], external_busy_slots=[], timezone_str=provider_tz
)
print([s.start.isoformat() for s in slots])

print("--- FULL DAY OFF EXCEPTION ---")
ex = ExceptionRule(date="2025-05-24", time_ranges=[])
slots = svc._calculate_day_slots(
    tenant_id=TenantId("123"), day=day, provider_id="321",
    service=MockService(), availability_rules=[rule1], exceptions=[ex],
    bookings=[], external_busy_slots=[], timezone_str=provider_tz
)
print([s.start.isoformat() for s in slots])

