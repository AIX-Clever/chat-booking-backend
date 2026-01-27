from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any


class SubscriptionStatus(Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class PlanType(Enum):
    LITE = "lite"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


@dataclass
class Subscription:
    tenant_id: str
    subscription_id: str
    status: SubscriptionStatus
    plan_id: PlanType
    current_price: float
    mp_preapproval_id: str
    is_promo_active: bool = False
    promo_scheduler_arn: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_item(self) -> Dict[str, Any]:
        item = {
            "tenantId": self.tenant_id,
            "subscriptionId": self.subscription_id,
            "status": self.status.value,
            "planId": (
                self.plan_id.value
                if hasattr(self.plan_id, "value")
                else str(self.plan_id)
            ),
            "currentPrice": str(self.current_price),
            "mpPreapprovalId": self.mp_preapproval_id,
            "isPromoActive": self.is_promo_active,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
        if self.promo_scheduler_arn:
            item["promoSchedulerArn"] = self.promo_scheduler_arn
        return item


@dataclass
class PaymentAudit:
    tenant_id: str
    payment_id: str
    amount: float
    status: str
    processed_at: str
    raw_data: str

    def to_item(self) -> Dict[str, Any]:
        return {
            "tenantId": self.tenant_id,
            "paymentId": self.payment_id,  # Range Key
            "amount": str(self.amount),
            "status": self.status,
            "processedAt": self.processed_at,
            "rawData": self.raw_data,
        }
