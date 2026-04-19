import pytest
from unittest.mock import MagicMock
from shared.domain.entities import Tenant, TenantPlan, TenantStatus, TenantId

# from shared.limit_service import TenantLimitService
# from booking.service import BookingService
from shared.domain.exceptions import ValidationError


def test_booking_limit_enforcement():
    # Setup
    tenant_id = TenantId("test-tenant")
    tenant = Tenant(
        tenant_id=tenant_id,
        name="Test Tenant",
        slug="test",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.LITE,
        owner_user_id="owner",
        billing_email="test@example.com",
    )

    # Mock Repositories
    tenant_repo = MagicMock()
    tenant_repo.get_by_id.return_value = tenant

    metrics_service = MagicMock()
    # LITE limit is 50. Let's simulate 50 bookings already made.
    metrics_service.get_usage_for_plan_limits.return_value = {
        "bookings": 50,
        "messages": 10,
    }

    service = MagicMock()
    service.duration_minutes = 60
    service.price = 0
    service.required_room_ids = []
    service.is_available.return_value = True

    service_repo = MagicMock()
    service_repo.get_by_id.return_value = service

    # Initialize Limit Service
    from shared.limit_service import TenantLimitService

    limit_service = TenantLimitService(tenant_repo, metrics_service)

    # Initialize Booking Service with the limit service
    from booking.service import BookingService

    booking_service = BookingService(
        booking_repo=MagicMock(),
        service_repo=service_repo,
        provider_repo=MagicMock(),
        tenant_repo=tenant_repo,
        limit_service=limit_service,
        email_service=MagicMock(),
    )

    # Attempt to create a booking should fail
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)

    with pytest.raises(ValidationError) as excinfo:
        booking_service.create_booking(
            tenant_id=tenant_id,
            service_id="svc-1",
            provider_id="prov-1",
            start=start,
            end=end,
            client_first_name="John",
            client_last_name="Doe",
            client_email="john@example.com",
        )

    assert "Has excedido el límite de reservas" in str(excinfo.value)
    print("✅ Booking limit enforcement verified.")


def test_message_limit_enforcement():
    # Setup
    tenant_id = TenantId("test-tenant")
    tenant = Tenant(
        tenant_id=tenant_id,
        name="Test",
        slug="test",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.LITE,
        owner_user_id="owner",
        billing_email="test@example.com",
    )

    tenant_repo = MagicMock()
    tenant_repo.get_by_id.return_value = tenant

    metrics_service = MagicMock()
    # LITE limit is 500 msgs. Simulate 500.
    metrics_service.get_usage_for_plan_limits.return_value = {
        "messages": 500,
        "bookings": 0,
    }

    from shared.limit_service import TenantLimitService

    limit_service = TenantLimitService(tenant_repo, metrics_service)

    assert limit_service.check_can_send_message(tenant_id) is False
    print("✅ Message limit enforcement verified.")


def test_ai_limit_enforcement_lite():
    # Setup
    tenant_id = TenantId("test-tenant")
    tenant = Tenant(
        tenant_id=tenant_id,
        name="Test",
        slug="test",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.LITE,
        owner_user_id="owner",
        billing_email="test@example.com",
    )

    tenant_repo = MagicMock()
    tenant_repo.get_by_id.return_value = tenant

    metrics_service = MagicMock()
    metrics_service.get_usage_for_plan_limits.return_value = {
        "messages": 0,
        "bookings": 0,
        "tokensIA": 0,
    }

    from shared.limit_service import TenantLimitService

    limit_service = TenantLimitService(tenant_repo, metrics_service)

    # LITE should NOT be able to use AI
    assert limit_service.check_can_use_ai(tenant_id) is False
    print("✅ AI limit enforcement (LITE) verified.")


if __name__ == "__main__":
    test_booking_limit_enforcement()
    test_message_limit_enforcement()
    test_ai_limit_enforcement_lite()
