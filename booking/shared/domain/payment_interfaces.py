from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class IPaymentGateway(ABC):
    """
    Abstract Interface for Payment Gateways (Strategy Pattern).
    Allows switching between Stripe, MercadoPago, etc.
    """
    
    @abstractmethod
    def create_payment_intent(
        self, 
        amount: float, 
        currency: str, 
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a payment intent/process.
        
        Args:
            amount: The amount to charge (in main currency unit, e.g. 10.50)
            currency: 'usd', 'clp', etc.
            metadata: Additional data to attach (booking_id, tenant_id)
            
        Returns:
            Dict containing at least 'client_secret' and 'payment_id'
        """
        pass

    @abstractmethod
    def verify_webhook_signature(
        self, 
        payload: str, 
        sig_header: str, 
        secret: str
    ) -> Dict[str, Any]:
        """
        Verify the webhook signature from the provider.
        """
        pass
