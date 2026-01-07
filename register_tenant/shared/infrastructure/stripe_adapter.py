import os
import logging
import stripe # type: ignore
from typing import Dict, Any
from shared.domain.payment_interfaces import IPaymentGateway

logger = logging.getLogger()

class StripeAdapter(IPaymentGateway):
    """
    Stripe Implementation of IPaymentGateway.
    """
    
    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or os.environ.get('STRIPE_SECRET_KEY')
        if not self.secret_key:
            logger.warning("Stripe Secret Key not found in environment")
        stripe.api_key = self.secret_key

    def create_payment_intent(
        self, 
        amount: float, 
        currency: str, 
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            # Stripe expects amount in cents for most currencies (usd, eur)
            # For CLP (Zero-decimal currency), it's just the amount.
            # Simple heuristic: if USD/EUR -> *100. If CLP -> *1.
            # TODO: Refine currency logic. Assuming USD for now.
            amount_cents = int(amount * 100) if currency.lower() in ['usd', 'eur'] else int(amount)
            
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                metadata=metadata,
                automatic_payment_methods={'enabled': True},
            )
            
            return {
                'payment_id': intent['id'],
                'client_secret': intent['client_secret'],
                'status': intent['status']
            }
        except Exception as e:
            logger.error(f"Stripe Create Intent Failed: {e}")
            raise e

    def verify_webhook_signature(
        self, 
        payload: str, 
        sig_header: str, 
        secret: str
    ) -> Dict[str, Any]:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, secret
            )
            return event
        except ValueError as e:
            raise Exception(f"Invalid payload: {e}")
        except stripe.error.SignatureVerificationError as e:
            raise Exception(f"Invalid signature: {e}")
