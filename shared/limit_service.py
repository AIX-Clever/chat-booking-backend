"""
Tenant Limit Service (Infrastructure Layer)

Service for checking if a tenant has exceeded their plan limits.
Integrates Tenant Entity logic with MetricsService data.
"""

from typing import Optional, Dict, Any
from .domain.entities import Tenant, TenantId
from .domain.repositories import ITenantRepository
from .metrics import MetricsService
from .utils import Logger


class TenantLimitService:
    """
    Service to enforce subscription plan limits.
    """

    def __init__(self, tenant_repo: ITenantRepository, metrics_service: MetricsService):
        self._tenant_repo = tenant_repo
        self._metrics_service = metrics_service
        self.logger = Logger()

    def check_can_send_message(self, tenant_id: TenantId) -> bool:
        """
        Check if tenant can send more messages.
        """
        try:
            # 1. Get Tenant to know the plan
            tenant = self._tenant_repo.get_by_id(tenant_id)
            if not tenant:
                self.logger.warning(
                    "Tenant not found during limit check", tenant_id=tenant_id.value
                )
                return False

            # 2. Get Usage
            usage = self._metrics_service.get_usage_for_plan_limits(tenant_id.value)
            current_messages = usage.get("messages", 0)

            # 3. Check Limit
            can_send = tenant.check_limit("messages", current_messages)

            if not can_send:
                self.logger.info(
                    "Message limit exceeded",
                    tenant_id=tenant_id.value,
                    plan=tenant.plan.value,
                    usage=current_messages,
                )

            return can_send

        except Exception as e:
            self.logger.error("Error checking message limit", error=e)
            # Fail open (allow) to avoid blocking valid traffic on system error
            return True

    def check_can_create_booking(self, tenant_id: TenantId) -> bool:
        """
        Check if tenant can create more bookings.
        """
        try:
            tenant = self._tenant_repo.get_by_id(tenant_id)
            if not tenant:
                return False

            usage = self._metrics_service.get_usage_for_plan_limits(tenant_id.value)
            current_bookings = usage.get("bookings", 0)

            can_book = tenant.check_limit("bookings", current_bookings)

            if not can_book:
                self.logger.info(
                    "Booking limit exceeded",
                    tenant_id=tenant_id.value,
                    plan=tenant.plan.value,
                    usage=current_bookings,
                )

            return can_book

        except Exception as e:
            self.logger.error("Error checking booking limit", error=e)
            return True

    def check_can_use_ai(self, tenant_id: TenantId) -> bool:
        """
        Check if tenant can usage AI features (Tokens + AI Enabled flag).
        """
        try:
            tenant = self._tenant_repo.get_by_id(tenant_id)
            if not tenant:
                return False

            # 1. Check if AI is enabled in Plan
            limits = tenant.get_plan_limits()
            if not limits.get("ai_enabled", False):
                return False

            # 2. Check Token Limit
            usage = self._metrics_service.get_usage_for_plan_limits(tenant_id.value)
            current_tokens = usage.get("tokensIA", 0)

            can_use = tenant.check_limit("tokensIA", current_tokens)

            if not can_use:
                self.logger.info(
                    "AI Token limit exceeded",
                    tenant_id=tenant_id.value,
                    plan=tenant.plan.value,
                    usage=current_tokens,
                )

            return can_use

        except Exception as e:
            self.logger.error("Error checking AI limit", error=e)
            return False  # Fail closed for AI (fallback to FSM)
