from typing import Dict, Any, Optional
from shared.domain.payment_interfaces import IPaymentGateway
from shared.subscriptions.config import SubscriptionConfig

class SubscriptionService:
    def __init__(self, payment_gateway: IPaymentGateway):
        self.payment_gateway = payment_gateway

    def create_subscription(
        self,
        tenant_id: str,
        email: str,
        plan_id: str,
        back_url: str
    ) -> Dict[str, Any]:
        """
        Orchestrates subscription creation.
        1. Calculates price (Promo vs Base).
        2. Calls Payment Gateway.
        3. Returns init_point.
        """
        
        # 1. Determine Price
        full_price = SubscriptionConfig.PLAN_PRICES.get(plan_id, 15000)
        
        if plan_id == 'lite':
            price = SubscriptionConfig.PROMO_PRICE
        else:
            price = full_price

        # 2. Call Gateway
        # Using tenant_id as external_reference
        result = self.payment_gateway.create_subscription(
            payer_email=email,
            plan_id=plan_id,
            external_reference=tenant_id,
            back_url=back_url,
            price=price
        )
        
        return {
            'preapproval_id': result.get('id'),
            'init_point': result.get('init_point'),
            'price': price,
            'full_price': full_price
        }
