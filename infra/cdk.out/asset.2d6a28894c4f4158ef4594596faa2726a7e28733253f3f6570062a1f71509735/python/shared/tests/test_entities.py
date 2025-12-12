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
    CustomerInfo
)
from shared.domain.exceptions import ValidationError


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
            billing_email="billing@test.com"
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
            billing_email="billing@test.com"
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
            active=True
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
            active=False
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
            active=True
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
            name="Jane Smith",
            email="jane@example.com",
            phone="+1234567890"
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
            payment_status=PaymentStatus.PENDING
        )
        
        assert booking.is_active()
    
    def test_booking_confirmation(self):
        customer = CustomerInfo(
            customer_id="cust_123",
            name="Jane Smith",
            email="jane@example.com",
            phone="+1234567890"
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
            payment_status=PaymentStatus.PENDING
        )
        
        booking.confirm()
        assert booking.status == BookingStatus.CONFIRMED
    
    def test_booking_cancellation(self):
        customer = CustomerInfo(
            customer_id="cust_123",
            name="Jane Smith",
            email="jane@example.com",
            phone="+1234567890"
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
            payment_status=PaymentStatus.PENDING
        )
        
        booking.cancel()
        assert booking.status == BookingStatus.CANCELLED
        assert not booking.is_active()
    
    def test_booking_overlap_detection(self):
        customer = CustomerInfo(
            customer_id="cust_123",
            name="Jane Smith",
            email="jane@example.com",
            phone="+1234567890"
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
            payment_status=PaymentStatus.PENDING
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
            payment_status=PaymentStatus.PENDING
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
            payment_status=PaymentStatus.PENDING
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
            is_available=True
        )
        
        assert slot.duration_minutes() == 60
    
    def test_available_slot(self):
        slot = TimeSlot(
            provider_id="pro_123",
            service_id="svc_123",
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0),
            is_available=True
        )
        
        assert slot.is_available
    
    def test_unavailable_slot(self):
        slot = TimeSlot(
            provider_id="pro_123",
            service_id="svc_123",
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0),
            is_available=False
        )
        
        assert not slot.is_available


class TestConversation:
    """Test Conversation entity"""
    
    def test_conversation_state_transition(self):
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.INIT
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
            slot_end=datetime(2025, 12, 15, 11, 0)
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
            created_at=datetime.now(UTC)
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
            created_at=datetime.now(UTC)
        )
        
        assert not api_key.is_valid()
