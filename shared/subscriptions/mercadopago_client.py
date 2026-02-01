import os
import mercadopago
from typing import Dict, Any


from shared.domain.payment_interfaces import IPaymentGateway

class MercadoPagoClient(IPaymentGateway):
    def __init__(self):
        self.access_token = os.environ.get("MP_ACCESS_TOKEN", "")
        if not self.access_token:
            print("WARNING: MP_ACCESS_TOKEN is not set")
        self.sdk = mercadopago.SDK(self.access_token)

    def create_payment_intent(self, amount: float, currency: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        # Implementation for single payments (not used in subscription flow yet)
        return {}

    def verify_webhook_signature(self, payload: str, sig_header: str, secret: str) -> Dict[str, Any]:
        # Implementation for webhook verification
        return {}

    def create_subscription(
        self,
        payer_email: str,
        plan_id: str,
        external_reference: str,
        back_url: str,
        price: float,
    ) -> Dict[str, Any]:
        return self.create_preapproval(payer_email, plan_id, external_reference, back_url, price)

    def create_preapproval(
        self,
        payer_email: str,
        plan_id: str,
        external_reference: str,
        back_url: str,
        price: float,
    ) -> Dict[str, Any]:
        """
        Creates a preapproval (subscription) in Mercado Pago.
        """
        # Create a "reason" dynamically or use a standard one
        reason = f"Suscripción Hola Lucía {plan_id.upper()}"

        preapproval_data = {
            "payer_email": payer_email,
            "back_url": back_url,
            "reason": reason,
            "external_reference": external_reference,
            "auto_recurring": {
                "frequency": 1,
                "frequency_type": "months",
                "transaction_amount": price,
                "currency_id": "CLP",  # Assuming Chile based on conversation
            },
        }

        request_options = mercadopago.config.RequestOptions()
        
        try:
            result = self.sdk.preapproval().create(preapproval_data, request_options)
            
            if result["status"] == 201:
                return result["response"]
            else:
                error_msg = result.get('response', {}).get('message', 'Unknown error')
                print(f"MP Create Error: {result}")
                
                # Check for Sandbox collision (Real vs Test users)
                if "payer and collector must be real or test users" in error_msg:
                     raise Exception("Sandbox Error: Use a Test User email for payment (e.g., test_user_1954@testuser.com)")
                     
                raise Exception(f"Failed to create preapproval: {error_msg}")
        except Exception as e:
            # Re-raise nicely formatted
            raise e

    def update_preapproval(
        self, preapproval_id: str, new_amount: float
    ) -> Dict[str, Any]:
        """
        Updates the auto_recurring amount of a preapproval.
        Used for removing promos (upgrade price) or downgrades.
        """
        update_data = {"auto_recurring": {"transaction_amount": new_amount}}

        result = self.sdk.preapproval().update(preapproval_id, update_data)

        if result["status"] == 200:
            return result["response"]
        else:
            print(f"MP Update Error: {result}")
            raise Exception(f"Failed to update preapproval {preapproval_id}")
