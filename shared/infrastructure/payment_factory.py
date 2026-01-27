import os
from typing import Optional
from shared.domain.payment_interfaces import IPaymentGateway
from shared.infrastructure.stripe_adapter import StripeAdapter


class PaymentGatewayFactory:
    """
    Factory to obtain the correct Payment Gateway based on context (Tenant, Country).
    """

    @staticmethod
    def get_gateway(tenant_country: str = "US") -> IPaymentGateway:
        """
        Returns the appropriate payment gateway.
        For now, defaults to Stripe for everyone.
        Future: If tenant_country == 'CL' -> return MercadoPagoAdapter()
        """
        # Default strategy: Stripe
        return StripeAdapter()

    @staticmethod
    def get_gateway_by_name(provider_name: str) -> IPaymentGateway:
        """
        Returns a specific gateway adapter by name.
        """
        if provider_name.lower() == "stripe":
            return StripeAdapter()

        raise ValueError(f"Unknown payment provider: {provider_name}")
