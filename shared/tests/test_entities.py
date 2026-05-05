"""
Unit tests for domain entities
"""

import pytest
from datetime import datetime, UTC, timedelta
from shared.domain.entities import (
    TenantId,
    Tenant,
    TenantStatus,
    TenantPlan,
    Service,
    Provider,
    Booking,
    BookingStatus,
    PaymentStatus,
    TimeSlot,
    Conversation,
    ConversationState,
    ApiKey,
    CustomerInfo,
    Room,
    RoomAssignment,
)
from shared.application.booking_service import _booking_period, _periods_overlap, _day_of_week


class TestTenantId:
    """Test TenantId value object"""

    def test_valid_tenant_id(self):
        tenant_id = TenantId("test123")
        assert tenant_id.value == "test123"
        assert str(tenant_id) == "test123"

    def test_invalid_tenant_id_too_short(self):
        with pytest.raises(ValueError):
            TenantId("ab")

    def test_tenant_id_equality(self):
        id1 = TenantId("test123")
        id2 = TenantId("test123")
        id3 = TenantId("other")

        assert id1 == id2
        assert id1 != id3

    def test_tenant_id_hashable(self):
        id1 = TenantId("test123")
        id2 = TenantId("test123")

        tenant_set = {id1, id2}
        assert len(tenant_set) == 1


class TestTenant:
    """Test Tenant aggregate"""

    def test_active_tenant_can_create_booking(self):
        tenant = Tenant(
            tenant_id=TenantId("test123"),
            name="Test Tenant",
            slug="test-tenant",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="billing@test.com",
        )

        assert tenant.is_active()
        assert tenant.can_create_booking()

    def test_suspended_tenant_cannot_create_booking(self):
        tenant = Tenant(
            tenant_id=TenantId("test123"),
            name="Test Tenant",
            slug="test-tenant",
            status=TenantStatus.SUSPENDED,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="billing@test.com",
        )

        assert not tenant.is_active()
        assert not tenant.can_create_booking()


class TestService:
    """Test Service entity"""

    def test_available_service(self):
        service = Service(
            service_id="svc_123",
            tenant_id=TenantId("test123"),
            name="Massage",
            description="60 min massage",
            category="wellness",
            duration_minutes=60,
            price=50.0,
            active=True,
        )

        assert service.is_available()

    def test_unavailable_service(self):
        service = Service(
            service_id="svc_123",
            tenant_id=TenantId("test123"),
            name="Massage",
            description="60 min massage",
            category="wellness",
            duration_minutes=60,
            price=50.0,
            active=False,
        )

        assert not service.is_available()


class TestProvider:
    """Test Provider entity"""

    def test_provider_can_provide_service(self):
        provider = Provider(
            provider_id="pro_123",
            tenant_id=TenantId("test123"),
            name="John Doe",
            bio="Expert therapist",
            service_ids=["svc_1", "svc_2"],
            timezone="UTC",
            active=True,
        )

        assert provider.can_provide_service("svc_1")
        assert provider.can_provide_service("svc_2")
        assert not provider.can_provide_service("svc_3")


class TestBooking:
    """Test Booking entity"""

    def test_booking_creation(self):
        start = datetime(2025, 12, 15, 10, 0)
        end = datetime(2025, 12, 15, 11, 0)
        customer = CustomerInfo(
            customer_id="cust_123",
            given_name="Jane",
            family_name="Smith",
            email="jane@example.com",
            phone="+1234567890",
        )

        booking = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=start,
            end_time=end,
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
        )

        assert booking.is_active()

    def test_booking_confirmation(self):
        customer = CustomerInfo(
            customer_id="cust_123",
            given_name="Jane",
            family_name="Smith",
            email="jane@example.com",
            phone="+1234567890",
        )

        booking = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime(2025, 12, 15, 10, 0),
            end_time=datetime(2025, 12, 15, 11, 0),
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
        )

        booking.confirm()
        assert booking.status == BookingStatus.CONFIRMED

    def test_booking_cancellation(self):
        customer = CustomerInfo(
            customer_id="cust_123",
            given_name="Jane",
            family_name="Smith",
            email="jane@example.com",
            phone="+1234567890",
        )

        booking = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime(2025, 12, 15, 10, 0),
            end_time=datetime(2025, 12, 15, 11, 0),
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
        )

        booking.cancel()
        assert booking.status == BookingStatus.CANCELLED
        assert not booking.is_active()

    def test_booking_overlap_detection(self):
        customer = CustomerInfo(
            customer_id="cust_123",
            given_name="Jane",
            family_name="Smith",
            email="jane@example.com",
            phone="+1234567890",
        )

        booking1 = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime(2025, 12, 15, 10, 0),
            end_time=datetime(2025, 12, 15, 11, 0),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )

        # Overlapping booking
        booking2 = Booking(
            booking_id="bkg_456",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime(2025, 12, 15, 10, 30),
            end_time=datetime(2025, 12, 15, 11, 30),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )
        assert booking1.overlaps_with(booking2)

        # Non-overlapping booking
        booking3 = Booking(
            booking_id="bkg_789",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime(2025, 12, 15, 11, 0),
            end_time=datetime(2025, 12, 15, 12, 0),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )
        assert not booking1.overlaps_with(booking3)


class TestTimeSlot:
    """Test TimeSlot value object"""

    def test_time_slot_duration(self):
        slot = TimeSlot(
            provider_id="pro_123",
            service_id="svc_123",
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0),
            is_available=True,
        )

        assert slot.duration_minutes() == 60

    def test_available_slot(self):
        slot = TimeSlot(
            provider_id="pro_123",
            service_id="svc_123",
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0),
            is_available=True,
        )

        assert slot.is_available

    def test_unavailable_slot(self):
        slot = TimeSlot(
            provider_id="pro_123",
            service_id="svc_123",
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0),
            is_available=False,
        )

        assert not slot.is_available


class TestConversation:
    """Test Conversation entity"""

    def test_conversation_state_transition(self):
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.INIT,
        )

        conversation.transition_to(ConversationState.SERVICE_PENDING)
        assert conversation.state == ConversationState.SERVICE_PENDING

    def test_conversation_ready_for_booking(self):
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.SLOT_PENDING,
            service_id="svc_123",
            provider_id="pro_123",
            slot_start=datetime(2025, 12, 15, 10, 0),
            slot_end=datetime(2025, 12, 15, 11, 0),
        )

        assert conversation.is_ready_for_booking()


class TestApiKey:
    """Test ApiKey entity"""

    def test_valid_api_key(self):
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            api_key_hash="hashed_key",
            status="ACTIVE",
            allowed_origins=["https://example.com"],
            rate_limit=1000,
            created_at=datetime.now(UTC),
        )

        assert api_key.is_valid()

    def test_inactive_api_key(self):
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            api_key_hash="hashed_key",
            status="REVOKED",
            allowed_origins=["https://example.com"],
            rate_limit=1000,
            created_at=datetime.now(UTC),
        )

        assert not api_key.is_valid()


class TestRoom:
    """Test Room entity"""

    def test_room_defaults(self):
        room = Room(
            room_id="rm-1",
            tenant_id=TenantId("test123"),
            name="Sala Alma",
        )
        assert room.status == "ACTIVE"
        assert room.is_virtual is False
        assert room.period_split is None

    def test_room_with_period_split(self):
        room = Room(
            room_id="rm-1",
            tenant_id=TenantId("test123"),
            name="Sala Alma",
            period_split="13:00",
        )
        assert room.period_split == "13:00"


class TestRoomAssignment:
    """Test RoomAssignment entity"""

    def test_assignment_creation(self):
        assignment = RoomAssignment(
            tenant_id=TenantId("test123"),
            room_id="rm-1",
            provider_id="pv-1",
            day_periods={"MON": "FULL", "WED": "AFTERNOON"},
        )
        assert assignment.room_id == "rm-1"
        assert assignment.provider_id == "pv-1"
        assert assignment.day_periods["MON"] == "FULL"
        assert assignment.day_periods["WED"] == "AFTERNOON"


class TestRoomAssignmentHelpers:
    """Test booking_service helper functions for room assignment logic"""

    def test_day_of_week_monday(self):
        # 2026-05-04 is a Monday
        dt = datetime(2026, 5, 4, 10, 0)
        assert _day_of_week(dt) == "MON"

    def test_day_of_week_saturday(self):
        # 2026-05-09 is a Saturday
        dt = datetime(2026, 5, 9, 10, 0)
        assert _day_of_week(dt) == "SAT"

    def test_booking_period_no_split(self):
        start = datetime(2026, 5, 4, 9, 0)
        end = datetime(2026, 5, 4, 10, 0)
        assert _booking_period(start, end, None) == "FULL"

    def test_booking_period_morning(self):
        start = datetime(2026, 5, 4, 9, 0)
        end = datetime(2026, 5, 4, 12, 0)
        assert _booking_period(start, end, "13:00") == "MORNING"

    def test_booking_period_afternoon(self):
        start = datetime(2026, 5, 4, 14, 0)
        end = datetime(2026, 5, 4, 16, 0)
        assert _booking_period(start, end, "13:00") == "AFTERNOON"

    def test_booking_period_spans_split(self):
        start = datetime(2026, 5, 4, 11, 0)
        end = datetime(2026, 5, 4, 15, 0)
        assert _booking_period(start, end, "13:00") == "FULL"

    def test_periods_overlap_full_vs_morning(self):
        assert _periods_overlap("FULL", "MORNING") is True

    def test_periods_overlap_full_vs_afternoon(self):
        assert _periods_overlap("AFTERNOON", "FULL") is True

    def test_periods_overlap_morning_vs_morning(self):
        assert _periods_overlap("MORNING", "MORNING") is True

    def test_periods_no_overlap_morning_vs_afternoon(self):
        assert _periods_overlap("MORNING", "AFTERNOON") is False
