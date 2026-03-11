"""
Unit Tests for WaitlistService

Tests cover:
- Adding to waitlist successfully
- Plan validation (LITE rejected)
- Provider validation (inactive, no availability)
- Duplicate detection
- Cancellation processing
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from shared.application.waitlist_service import WaitlistService
from shared.domain.entities import (
    TenantId,
    Tenant,
    TenantStatus,
    TenantPlan,
    WaitingListEntry,
    WaitingListStatus,
)
from shared.domain.exceptions import ValidationError


@pytest.fixture
def mock_repos():
    """Create mock repositories for testing."""
    return {
        "waitlist_repo": MagicMock(),
        "tenant_repo": MagicMock(),
        "provider_repo": MagicMock(),
        "availability_repo": MagicMock(),
    }


@pytest.fixture
def service(mock_repos):
    """Create WaitlistService with mocked dependencies."""
    return WaitlistService(
        waitlist_repo=mock_repos["waitlist_repo"],
        tenant_repo=mock_repos["tenant_repo"],
        provider_repo=mock_repos["provider_repo"],
        availability_repo=mock_repos["availability_repo"],
    )


@pytest.fixture
def pro_tenant():
    """Create a PRO plan tenant."""
    return Tenant(
        tenant_id=TenantId("tenant-123"),
        name="Test Business",
        slug="test-business",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.PRO,
        owner_user_id="user-1",
        billing_email="test@example.com",
    )


@pytest.fixture
def lite_tenant():
    """Create a LITE plan tenant."""
    return Tenant(
        tenant_id=TenantId("tenant-lite"),
        name="Lite Business",
        slug="lite-business",
        status=TenantStatus.ACTIVE,
        plan=TenantPlan.LITE,
        owner_user_id="user-2",
        billing_email="lite@example.com",
    )


class TestAddToWaitlist:
    """Tests for adding clients to the waitlist."""

    def test_add_to_waitlist_success(
        self, service, mock_repos, pro_tenant
    ):
        """Successfully add a client to the waitlist."""
        mock_repos["tenant_repo"].get_by_id.return_value = pro_tenant
        mock_repos["provider_repo"].get_by_id.return_value = MagicMock(
            status="ACTIVE"
        )
        mock_repos["availability_repo"].get_weekly_schedule.return_value = [
            {"dayOfWeek": "MONDAY", "timeRanges": []}
        ]
        mock_repos["waitlist_repo"].find_pending_by_client.return_value = (
            None
        )

        result = service.add_to_waitlist(
            tenant_id=TenantId("tenant-123"),
            service_id="service-1",
            client_id="client@email.com",
            provider_id="provider-1",
            preferred_days=["MONDAY", "WEDNESDAY"],
        )

        assert result is not None
        assert result.service_id == "service-1"
        assert result.client_id == "client@email.com"
        assert result.contact_status == WaitingListStatus.PENDING
        mock_repos["waitlist_repo"].save.assert_called_once()

    def test_reject_lite_plan(
        self, service, mock_repos, lite_tenant
    ):
        """Reject waitlist for LITE plan tenants."""
        mock_repos["tenant_repo"].get_by_id.return_value = lite_tenant

        with pytest.raises(ValidationError, match="PRO plan"):
            service.add_to_waitlist(
                tenant_id=TenantId("tenant-lite"),
                service_id="service-1",
                client_id="client@email.com",
            )

    def test_reject_inactive_provider(
        self, service, mock_repos, pro_tenant
    ):
        """Reject if provider is inactive."""
        mock_repos["tenant_repo"].get_by_id.return_value = pro_tenant
        mock_repos["provider_repo"].get_by_id.return_value = MagicMock(
            status="INACTIVE"
        )

        with pytest.raises(ValidationError, match="inactive"):
            service.add_to_waitlist(
                tenant_id=TenantId("tenant-123"),
                service_id="service-1",
                client_id="client@email.com",
                provider_id="provider-1",
            )

    def test_reject_provider_no_availability(
        self, service, mock_repos, pro_tenant
    ):
        """Reject if provider has no availability configured."""
        mock_repos["tenant_repo"].get_by_id.return_value = pro_tenant
        mock_repos["provider_repo"].get_by_id.return_value = MagicMock(
            status="ACTIVE"
        )
        mock_repos["availability_repo"].get_weekly_schedule.return_value = (
            []
        )

        with pytest.raises(
            ValidationError, match="no availability"
        ):
            service.add_to_waitlist(
                tenant_id=TenantId("tenant-123"),
                service_id="service-1",
                client_id="client@email.com",
                provider_id="provider-1",
            )

    def test_reject_duplicate_entry(
        self, service, mock_repos, pro_tenant
    ):
        """Reject if client is already on the waitlist."""
        mock_repos["tenant_repo"].get_by_id.return_value = pro_tenant
        mock_repos["provider_repo"].get_by_id.return_value = MagicMock(
            status="ACTIVE"
        )
        mock_repos["availability_repo"].get_weekly_schedule.return_value = [
            {"dayOfWeek": "MONDAY"}
        ]
        mock_repos["waitlist_repo"].find_pending_by_client.return_value = (
            MagicMock()  # Existing entry
        )

        with pytest.raises(
            ValidationError, match="already on the waiting list"
        ):
            service.add_to_waitlist(
                tenant_id=TenantId("tenant-123"),
                service_id="service-1",
                client_id="client@email.com",
                provider_id="provider-1",
            )

    def test_tenant_not_found(self, service, mock_repos):
        """Reject if tenant does not exist."""
        mock_repos["tenant_repo"].get_by_id.return_value = None

        with pytest.raises(ValidationError, match="not found"):
            service.add_to_waitlist(
                tenant_id=TenantId("nonexistent"),
                service_id="service-1",
                client_id="client@email.com",
            )


class TestProcessCancellation:
    """Tests for processing booking cancellations."""

    def test_process_cancellation_with_candidate(
        self, service, mock_repos, pro_tenant
    ):
        """Return the first candidate when available."""
        mock_repos["tenant_repo"].get_by_id.return_value = pro_tenant
        mock_repos["provider_repo"].get_by_id.return_value = MagicMock(
            status="ACTIVE"
        )
        mock_repos["availability_repo"].get_weekly_schedule.return_value = [
            {"dayOfWeek": "MONDAY"}
        ]

        candidate = WaitingListEntry(
            tenant_id=TenantId("tenant-123"),
            waiting_list_id="wl-1",
            service_id="service-1",
            client_id="first@email.com",
        )
        mock_repos["waitlist_repo"].list_by_service.return_value = [
            candidate
        ]

        result = service.process_cancellation(
            tenant_id=TenantId("tenant-123"),
            service_id="service-1",
            provider_id="provider-1",
        )

        assert result is not None
        assert result.client_id == "first@email.com"

    def test_process_cancellation_no_candidates(
        self, service, mock_repos, pro_tenant
    ):
        """Return None when no candidates available."""
        mock_repos["tenant_repo"].get_by_id.return_value = pro_tenant
        mock_repos["provider_repo"].get_by_id.return_value = MagicMock(
            status="ACTIVE"
        )
        mock_repos["availability_repo"].get_weekly_schedule.return_value = [
            {"dayOfWeek": "MONDAY"}
        ]
        mock_repos["waitlist_repo"].list_by_service.return_value = []

        result = service.process_cancellation(
            tenant_id=TenantId("tenant-123"),
            service_id="service-1",
            provider_id="provider-1",
        )

        assert result is None

    def test_process_cancellation_lite_plan(
        self, service, mock_repos, lite_tenant
    ):
        """Skip processing for LITE plan tenants."""
        mock_repos["tenant_repo"].get_by_id.return_value = lite_tenant

        result = service.process_cancellation(
            tenant_id=TenantId("tenant-lite"),
            service_id="service-1",
        )

        assert result is None

    def test_process_cancellation_inactive_provider(
        self, service, mock_repos, pro_tenant
    ):
        """Skip if provider is inactive."""
        mock_repos["tenant_repo"].get_by_id.return_value = pro_tenant
        mock_repos["provider_repo"].get_by_id.return_value = MagicMock(
            status="INACTIVE"
        )

        result = service.process_cancellation(
            tenant_id=TenantId("tenant-123"),
            service_id="service-1",
            provider_id="provider-1",
        )

        assert result is None
