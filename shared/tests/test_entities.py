"""
Unit tests for domain entities
"""

import pytest
from datetime import datetime, timedelta
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
    ApiKey
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
            available=True,
            created_at=datetime.utcnow()
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
            available=False,
            created_at=datetime.utcnow()
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
            available=True,
            created_at=datetime.utcnow()
        )
        
        assert provider.can_provide_service("svc_1")
        assert provider.can_provide_service("svc_2")
        assert not provider.can_provide_service("svc_3")


class TestBooking:
    """Test Booking entity"""
    
    def test_booking_creation(self):
        start = datetime(2025, 12, 15, 10, 0)
        end = datetime(2025, 12, 15, 11, 0)
        
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            start=start,
            end=end,
            status=BookingStatus.PENDING,
            client_name="Jane Smith",
            client_email="jane@example.com",
            payment_status=PaymentStatus.PENDING,
            total_amount=50.0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        assert booking.is_active()
    
    def test_booking_confirmation(self):
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0),
            status=BookingStatus.PENDING,
            client_name="Jane Smith",
            client_email="jane@example.com",
            payment_status=PaymentStatus.PENDING,
            total_amount=50.0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        booking.confirm()
        assert booking.status == BookingStatus.CONFIRMED
    
    def test_booking_cancellation(self):
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0),
            status=BookingStatus.PENDING,
            client_name="Jane Smith",
            client_email="jane@example.com",
            payment_status=PaymentStatus.PENDING,
            total_amount=50.0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        booking.cancel()
        assert booking.status == BookingStatus.CANCELLED
        assert not booking.is_active()
    
    def test_booking_overlap_detection(self):
        start1 = datetime(2025, 12, 15, 10, 0)
        end1 = datetime(2025, 12, 15, 11, 0)
        
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=TenantId("test123"),
            service_id="svc_123",
            provider_id="pro_123",
            start=start1,
            end=end1,
            status=BookingStatus.CONFIRMED,
            client_name="Jane Smith",
            client_email="jane@example.com",
            payment_status=PaymentStatus.PENDING,
            total_amount=50.0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        # Overlapping slot
        overlapping_slot = TimeSlot(
            start=datetime(2025, 12, 15, 10, 30),
            end=datetime(2025, 12, 15, 11, 30)
        )
        assert booking.overlaps_with(overlapping_slot)
        
        # Non-overlapping slot
        non_overlapping_slot = TimeSlot(
            start=datetime(2025, 12, 15, 11, 0),
            end=datetime(2025, 12, 15, 12, 0)
        )
        assert not booking.overlaps_with(non_overlapping_slot)


class TestTimeSlot:
    """Test TimeSlot value object"""
    
    def test_time_slot_duration(self):
        slot = TimeSlot(
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0)
        )
        
        assert slot.duration_minutes() == 60
    
    def test_overlapping_slots(self):
        slot1 = TimeSlot(
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0)
        )
        
        slot2 = TimeSlot(
            start=datetime(2025, 12, 15, 10, 30),
            end=datetime(2025, 12, 15, 11, 30)
        )
        
        assert slot1.overlaps_with(slot2)
        assert slot2.overlaps_with(slot1)
    
    def test_non_overlapping_slots(self):
        slot1 = TimeSlot(
            start=datetime(2025, 12, 15, 10, 0),
            end=datetime(2025, 12, 15, 11, 0)
        )
        
        slot2 = TimeSlot(
            start=datetime(2025, 12, 15, 11, 0),
            end=datetime(2025, 12, 15, 12, 0)
        )
        
        assert not slot1.overlaps_with(slot2)


class TestConversation:
    """Test Conversation entity"""
    
    def test_conversation_state_transition(self):
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.INIT,
            context={},
            messages=[],
            channel="widget",
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        conversation.transition_to(ConversationState.SERVICE_PENDING)
        assert conversation.state == ConversationState.SERVICE_PENDING
    
    def test_conversation_ready_for_booking(self):
        conversation = Conversation(
            conversation_id="conv_123",
            tenant_id=TenantId("test123"),
            state=ConversationState.CONFIRM_PENDING,
            context={
                "serviceId": "svc_123",
                "providerId": "pro_123",
                "selectedSlot": {"start": "2025-12-15T10:00:00Z"},
                "clientName": "John Doe",
                "clientEmail": "john@example.com"
            },
            messages=[],
            channel="widget",
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        assert conversation.is_ready_for_booking()


class TestApiKey:
    """Test ApiKey entity"""
    
    def test_valid_api_key(self):
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["https://example.com"],
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        assert api_key.is_valid()
    
    def test_inactive_api_key(self):
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["https://example.com"],
            is_active=False,
            created_at=datetime.utcnow()
        )
        
        assert not api_key.is_valid()
    
    def test_origin_validation(self):
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["https://example.com", "https://test.com"],
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        assert api_key.is_origin_allowed("https://example.com")
        assert api_key.is_origin_allowed("https://test.com")
        assert not api_key.is_origin_allowed("https://malicious.com")
    
    def test_wildcard_origin(self):
        api_key = ApiKey(
            api_key_id="key_123",
            tenant_id=TenantId("test123"),
            key_hash="hashed_key",
            description="Test key",
            allowed_origins=["*"],
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        assert api_key.is_origin_allowed("https://any-domain.com")
