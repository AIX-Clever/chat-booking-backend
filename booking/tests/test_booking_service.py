"""
Unit tests for booking service
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
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
    CustomerInfo,
)
from shared.domain.exceptions import (
    EntityNotFoundError,
    TenantNotActiveError,
    ServiceNotAvailableError,
    ProviderNotAvailableError,
    SlotNotAvailableError,
    ValidationError,
)
from booking.service import BookingService


class TestBookingService:
    """Test BookingService"""

    @pytest.fixture
    def tenant_id(self):
        return TenantId("test123")

    @pytest.fixture
    def active_tenant(self, tenant_id):
        return Tenant(
            tenant_id=tenant_id,
            name="Test Tenant",
            slug="test-tenant",
            status=TenantStatus.ACTIVE,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="billing@test.com",
        )

    @pytest.fixture
    def service(self, tenant_id):
        return Service(
            service_id="svc_123",
            tenant_id=tenant_id,
            name="Massage",
            description="60 min massage",
            category="wellness",
            duration_minutes=60,
            price=50.0,
            active=True,
        )

    @pytest.fixture
    def provider(self, tenant_id):
        return Provider(
            provider_id="pro_123",
            tenant_id=tenant_id,
            name="John Doe",
            bio="Expert therapist",
            service_ids=["svc_123"],
            timezone="timezone.utc",
            active=True,
        )

    @pytest.fixture
    def mock_repos(self):
        return {
            "booking": Mock(),
            "service": Mock(),
            "provider": Mock(),
            "tenant": Mock(),
            "metrics": Mock(),
        }

    @pytest.fixture
    def booking_service(self, mock_repos):
        return BookingService(
            mock_repos["booking"],
            mock_repos["service"],
            mock_repos["provider"],
            mock_repos["tenant"],
            metrics_service=mock_repos["metrics"],
        )

    def test_create_booking_success(
        self, booking_service, mock_repos, tenant_id, active_tenant, service, provider
    ):
        """Test successful booking creation"""
        # Setup
        start = datetime.now(timezone.utc) + timedelta(days=1)
        end = start + timedelta(minutes=60)

        mock_repos["tenant"].get_by_id.return_value = active_tenant
        mock_repos["service"].get_by_id.return_value = service
        mock_repos["provider"].get_by_id.return_value = provider
        mock_repos["booking"].list_by_provider.return_value = []

        # Execute
        booking = booking_service.create_booking(
            tenant_id=tenant_id,
            service_id="svc_123",
            provider_id="pro_123",
            start=start,
            end=end,
            client_name="Jane Smith",
            client_email="jane@example.com",
        )

        # Assert
        assert booking.status == BookingStatus.PENDING
        assert booking.customer_info.name == "Jane Smith"
        assert booking.customer_info.email == "jane@example.com"
        assert booking.start_time == start
        assert booking.end_time == end
        mock_repos["booking"].save.assert_called_once()

    def test_create_booking_tenant_not_active(
        self, booking_service, mock_repos, tenant_id
    ):
        """Test booking creation with suspended tenant"""
        suspended_tenant = Tenant(
            tenant_id=tenant_id,
            name="Test Tenant",
            slug="test-tenant",
            status=TenantStatus.SUSPENDED,
            plan=TenantPlan.PRO,
            owner_user_id="user_123",
            billing_email="billing@test.com",
        )

        mock_repos["tenant"].get_by_id.return_value = suspended_tenant

        start = datetime.now(timezone.utc) + timedelta(days=1)
        end = start + timedelta(minutes=60)

        with pytest.raises(TenantNotActiveError):
            booking_service.create_booking(
                tenant_id=tenant_id,
                service_id="svc_123",
                provider_id="pro_123",
                start=start,
                end=end,
                client_name="Jane Smith",
                client_email="jane@example.com",
            )

    def test_create_booking_service_not_available(
        self, booking_service, mock_repos, tenant_id, active_tenant
    ):
        """Test booking creation with unavailable service"""
        unavailable_service = Service(
            service_id="svc_123",
            tenant_id=tenant_id,
            name="Massage",
            description="60 min massage",
            category="wellness",
            duration_minutes=60,
            price=50.0,
            active=False,
        )

        mock_repos["tenant"].get_by_id.return_value = active_tenant
        mock_repos["service"].get_by_id.return_value = unavailable_service

        start = datetime.now(timezone.utc) + timedelta(days=1)
        end = start + timedelta(minutes=60)

        with pytest.raises(ServiceNotAvailableError):
            booking_service.create_booking(
                tenant_id=tenant_id,
                service_id="svc_123",
                provider_id="pro_123",
                start=start,
                end=end,
                client_name="Jane Smith",
                client_email="jane@example.com",
            )

    def test_create_booking_provider_cannot_provide_service(
        self, booking_service, mock_repos, tenant_id, active_tenant, service
    ):
        """Test booking with provider who doesn't provide service"""
        wrong_provider = Provider(
            provider_id="pro_123",
            tenant_id=tenant_id,
            name="John Doe",
            bio="Expert therapist",
            service_ids=["svc_999"],  # Different service
            timezone="timezone.utc",
            active=True,
        )

        mock_repos["tenant"].get_by_id.return_value = active_tenant
        mock_repos["service"].get_by_id.return_value = service
        mock_repos["provider"].get_by_id.return_value = wrong_provider

        start = datetime.now(timezone.utc) + timedelta(days=1)
        end = start + timedelta(minutes=60)

        with pytest.raises(ProviderNotAvailableError):
            booking_service.create_booking(
                tenant_id=tenant_id,
                service_id="svc_123",
                provider_id="pro_123",
                start=start,
                end=end,
                client_name="Jane Smith",
                client_email="jane@example.com",
            )

    def test_create_booking_slot_conflict(
        self, booking_service, mock_repos, tenant_id, active_tenant, service, provider
    ):
        """Test booking creation with slot conflict"""
        start = datetime.now(timezone.utc) + timedelta(days=1)
        end = start + timedelta(minutes=60)

        # Existing booking
        customer = CustomerInfo(
            customer_id=None, name="Someone Else", email="other@example.com", phone=None
        )
        existing_booking = Booking(
            booking_id="bkg_existing",
            tenant_id=tenant_id,
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=start,
            end_time=end,
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )

        mock_repos["tenant"].get_by_id.return_value = active_tenant
        mock_repos["service"].get_by_id.return_value = service
        mock_repos["provider"].get_by_id.return_value = provider
        mock_repos["booking"].list_by_provider.return_value = [existing_booking]

        with pytest.raises(SlotNotAvailableError):
            booking_service.create_booking(
                tenant_id=tenant_id,
                service_id="svc_123",
                provider_id="pro_123",
                start=start,
                end=end,
                client_name="Jane Smith",
                client_email="jane@example.com",
            )

    def test_create_booking_in_past(
        self, booking_service, mock_repos, tenant_id, active_tenant, service, provider
    ):
        """Test booking creation in the past"""
        start = datetime.now(timezone.utc) - timedelta(days=1)
        end = start + timedelta(minutes=60)

        mock_repos["tenant"].get_by_id.return_value = active_tenant
        mock_repos["service"].get_by_id.return_value = service
        mock_repos["provider"].get_by_id.return_value = provider

        with pytest.raises(ValidationError):
            booking_service.create_booking(
                tenant_id=tenant_id,
                service_id="svc_123",
                provider_id="pro_123",
                start=start,
                end=end,
                client_name="Jane Smith",
                client_email="jane@example.com",
            )

    def test_confirm_booking(self, booking_service, mock_repos, tenant_id):
        """Test booking confirmation"""
        customer = CustomerInfo(
            customer_id=None, name="Jane Smith", email="jane@example.com", phone=None
        )
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=tenant_id,
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime.now(timezone.utc) + timedelta(days=1),
            end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING,
        )

        mock_repos["booking"].get_by_id.return_value = booking

        result = booking_service.confirm_booking(tenant_id, "bkg_123")

        assert result.status == BookingStatus.CONFIRMED
        mock_repos["booking"].update.assert_called_once()

    def test_cancel_booking(self, booking_service, mock_repos, tenant_id):
        """Test booking cancellation"""
        customer = CustomerInfo(
            customer_id=None, name="Jane Smith", email="jane@example.com", phone=None
        )
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=tenant_id,
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime.now(timezone.utc) + timedelta(days=1),
            end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )

        mock_repos["booking"].get_by_id.return_value = booking

        result = booking_service.cancel_booking(
            tenant_id, "bkg_123", reason="Client requested"
        )

        assert result.status == BookingStatus.CANCELLED
        mock_repos["booking"].update.assert_called_once()

    def test_mark_as_no_show(self, booking_service, mock_repos, tenant_id):
        """Test marking booking as no show"""
        customer = CustomerInfo(
            customer_id=None, name="Jane Smith", email="jane@example.com", phone=None
        )
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=tenant_id,
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime.now(timezone.utc) + timedelta(days=1),
            end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )

        mock_repos["booking"].get_by_id.return_value = booking

        result = booking_service.mark_as_no_show(tenant_id, "bkg_123")

        assert result.status == BookingStatus.NO_SHOW
        mock_repos["booking"].update.assert_called_once()


class TestBookingQueryService:
    """Test BookingQueryService"""

    @pytest.fixture
    def tenant_id(self):
        return TenantId("test123")

    @pytest.fixture
    def mock_repos(self):
        return {"booking": Mock(), "conversation": Mock()}

    @pytest.fixture
    def query_service(self, mock_repos):
        from booking.service import BookingQueryService

        return BookingQueryService(mock_repos["booking"], mock_repos["conversation"])

    def test_get_booking_success(self, query_service, mock_repos, tenant_id):
        """Test getting booking by ID"""
        customer = CustomerInfo(
            customer_id=None, name="Jane Smith", email="jane@example.com", phone=None
        )
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=tenant_id,
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime.now(timezone.utc) + timedelta(days=1),
            end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )

        mock_repos["booking"].get_by_id.return_value = booking

        result = query_service.get_booking(tenant_id, "bkg_123")

        assert result.booking_id == "bkg_123"
        mock_repos["booking"].get_by_id.assert_called_once_with(tenant_id, "bkg_123")

    def test_get_booking_not_found(self, query_service, mock_repos, tenant_id):
        """Test getting non-existent booking"""
        mock_repos["booking"].get_by_id.return_value = None

        with pytest.raises(EntityNotFoundError):
            query_service.get_booking(tenant_id, "bkg_999")

    def test_list_by_provider(self, query_service, mock_repos, tenant_id):
        """Test listing bookings by provider"""
        start_date = datetime.now(timezone.utc)
        end_date = start_date + timedelta(days=7)

        bookings = []
        mock_repos["booking"].list_by_provider.return_value = bookings

        result = query_service.list_by_provider(
            tenant_id, "pro_123", start_date, end_date
        )

        assert result == bookings
        mock_repos["booking"].list_by_provider.assert_called_once_with(
            tenant_id, "pro_123", start_date, end_date
        )

    def test_list_by_client(self, query_service, mock_repos, tenant_id):
        """Test listing bookings by client email"""
        bookings = []
        mock_repos["booking"].list_by_customer_email.return_value = bookings

        result = query_service.list_by_client(tenant_id, "client@example.com")

        assert result == bookings
        mock_repos["booking"].list_by_customer_email.assert_called_once_with(
            tenant_id, "client@example.com"
        )

    def test_get_booking_by_conversation(self, query_service, mock_repos, tenant_id):
        """Test getting booking by conversation ID"""
        customer = CustomerInfo(
            customer_id=None, name="Jane Smith", email="jane@example.com", phone=None
        )
        booking = Booking(
            booking_id="bkg_123",
            tenant_id=tenant_id,
            service_id="svc_123",
            provider_id="pro_123",
            customer_info=customer,
            start_time=datetime.now(timezone.utc) + timedelta(days=1),
            end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
        )

        # Setup conversation with booking_id
        conversation = Mock()
        conversation.booking_id = "bkg_123"
        mock_repos["conversation"].get_by_id.return_value = conversation

        mock_repos["booking"].get_by_id.return_value = booking

        result = query_service.get_booking_by_conversation(tenant_id, "conv_123")

        assert result == booking
        mock_repos["conversation"].get_by_id.assert_called_once_with(
            tenant_id, "conv_123"
        )
        mock_repos["booking"].get_by_id.assert_called_once_with(tenant_id, "bkg_123")

    def test_get_booking_by_conversation_no_booking(
        self, query_service, mock_repos, tenant_id
    ):
        """Test getting booking when conversation has no booking"""
        conversation = Mock()
        conversation.booking_id = None
        mock_repos["conversation"].get_by_id.return_value = conversation

        result = query_service.get_booking_by_conversation(tenant_id, "conv_123")

        assert result is None
        mock_repos["conversation"].get_by_id.assert_called_once_with(
            tenant_id, "conv_123"
        )
        mock_repos["booking"].get_by_id.assert_not_called()
