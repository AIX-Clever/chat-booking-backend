"""
Waitlist Application Service

Business logic for the Intelligent Waiting List feature.
Validates plan eligibility, provider status, and manages
the waitlist lifecycle.
"""

import uuid
import time
from typing import Optional, List

from ..domain.entities import (
    TenantId,
    WaitingListEntry,
    WaitingListStatus,
    PLAN_LIMITS,
)
from ..domain.repositories import (
    IWaitingListRepository,
    ITenantRepository,
    IProviderRepository,
    IAvailabilityRepository,
)
from ..domain.exceptions import ValidationError
from ..utils import Logger

logger = Logger()

# TTL: 30 days in seconds
WAITING_LIST_TTL_SECONDS = 30 * 24 * 60 * 60


class WaitlistService:
    """Application service for waitlist operations"""

    def __init__(
        self,
        waitlist_repo: IWaitingListRepository,
        tenant_repo: ITenantRepository,
        provider_repo: IProviderRepository,
        availability_repo: IAvailabilityRepository,
    ):
        self.waitlist_repo = waitlist_repo
        self.tenant_repo = tenant_repo
        self.provider_repo = provider_repo
        self.availability_repo = availability_repo

    def add_to_waitlist(
        self,
        tenant_id: TenantId,
        service_id: str,
        client_id: str,
        provider_id: Optional[str] = None,
        preferred_days: Optional[List[str]] = None,
        requested_dates: Optional[List[str]] = None,
    ) -> WaitingListEntry:
        """Add a client to the waiting list for a service.

        Validates:
        1. Tenant has PRO plan or higher (waitlist_enabled)
        2. Provider is active (if specified)
        3. Provider has availability configured
        4. Client is not already on the waitlist for this service
        """
        # 1. Validate tenant plan
        tenant = self.tenant_repo.get_by_id(tenant_id)
        if not tenant:
            raise ValidationError("Tenant not found")

        plan_limits = PLAN_LIMITS.get(tenant.plan, {})
        if not plan_limits.get("waitlist_enabled", False):
            raise ValidationError(
                "Waitlist is only available for PRO plan and above"
            )

        # 2. Validate provider is active (if specified)
        if provider_id:
            provider = self.provider_repo.get_by_id(
                tenant_id, provider_id
            )
            if not provider:
                raise ValidationError("Provider not found")
            if hasattr(provider, "status") and provider.status == "INACTIVE":
                raise ValidationError(
                    "Provider is inactive, cannot accept waitlist entries"
                )

            # 3. Validate provider has availability configured
            availability = self.availability_repo.get_weekly_schedule(
                tenant_id, provider_id
            )
            if not availability:
                raise ValidationError(
                    "Provider has no availability configured"
                )

        # 4. Check for duplicate entry
        existing = self.waitlist_repo.find_pending_by_client(
            tenant_id, service_id, client_id
        )
        if existing:
            raise ValidationError(
                "Client is already on the waiting list for this service"
            )

        # Create and save entry
        entry = WaitingListEntry(
            tenant_id=tenant_id,
            waiting_list_id=str(uuid.uuid4()),
            service_id=service_id,
            client_id=client_id,
            contact_status=WaitingListStatus.PENDING,
            provider_id=provider_id,
            preferred_days=preferred_days or [],
            requested_dates=requested_dates or [],
            ttl=int(time.time()) + WAITING_LIST_TTL_SECONDS,
        )

        self.waitlist_repo.save(entry)
        logger.info(
            f"Client {client_id} added to waitlist for "
            f"service {service_id} (tenant: {tenant_id})"
        )
        return entry

    def process_cancellation(
        self,
        tenant_id: TenantId,
        service_id: str,
        provider_id: Optional[str] = None,
    ) -> Optional[WaitingListEntry]:
        """Find the next candidate to notify after a booking cancellation.

        Returns the first PENDING entry for the service, or None.
        Validates provider is still active before returning a candidate.
        """
        # Validate tenant plan
        tenant = self.tenant_repo.get_by_id(tenant_id)
        if not tenant:
            logger.warning(f"Tenant {tenant_id} not found")
            return None

        plan_limits = PLAN_LIMITS.get(tenant.plan, {})
        if not plan_limits.get("waitlist_enabled", False):
            return None

        # Validate provider is still active
        if provider_id:
            provider = self.provider_repo.get_by_id(
                tenant_id, provider_id
            )
            if not provider:
                logger.warning(
                    f"Provider {provider_id} not found"
                )
                return None
            if hasattr(provider, "status") and provider.status == "INACTIVE":
                logger.warning(
                    f"Provider {provider_id} is inactive, "
                    "skipping waitlist notification"
                )
                return None

            # Check provider still has availability
            availability = self.availability_repo.get_weekly_schedule(
                tenant_id, provider_id
            )
            if not availability:
                logger.warning(
                    f"Provider {provider_id} has no availability"
                )
                return None

        # Get ordered candidates (FIFO by createdAt)
        candidates = self.waitlist_repo.list_by_service(
            tenant_id, service_id
        )

        if not candidates:
            logger.info(
                f"No waitlist candidates for service {service_id}"
            )
            return None

        # Return first candidate
        candidate = candidates[0]
        logger.info(
            f"Waitlist candidate found: {candidate.client_id} "
            f"for service {service_id}"
        )
        return candidate

    def mark_contacted(
        self, tenant_id: TenantId, waiting_list_id: str
    ) -> None:
        """Mark a waitlist entry as contacted."""
        self.waitlist_repo.update_status(
            tenant_id,
            waiting_list_id,
            WaitingListStatus.CONTACTED.value,
        )

    def mark_booked(
        self, tenant_id: TenantId, waiting_list_id: str
    ) -> None:
        """Mark a waitlist entry as booked (client accepted)."""
        self.waitlist_repo.update_status(
            tenant_id,
            waiting_list_id,
            WaitingListStatus.BOOKED.value,
        )

    def mark_declined(
        self, tenant_id: TenantId, waiting_list_id: str
    ) -> None:
        """Mark a waitlist entry as declined (client refused)."""
        self.waitlist_repo.update_status(
            tenant_id,
            waiting_list_id,
            WaitingListStatus.DECLINED.value,
        )
