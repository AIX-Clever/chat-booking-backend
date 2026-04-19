import os
import requests
import logging
from typing import Optional
from shared.domain.security_interfaces import CaptchaService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

class GoogleRecaptchaAdapter(CaptchaService):
    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or os.environ.get('RECAPTCHA_SECRET_KEY')
        if not self.secret_key:
            logger.warning("RECAPTCHA_SECRET_KEY not configured. Validation maps to True (Open).")

    def verify(self, token: str, action_name: str) -> bool:
        """
        Valida el token recibido del frontend contra Google reCAPTCHA v3.
        Retorna True si es humano, False si es bot o si la acción no coincide.
        """
        if not self.secret_key:
            return True
            
        verify_url = 'https://www.google.com/recaptcha/api/siteverify'
        
        payload = {
            'secret': self.secret_key,
            'response': token
        }
        
        try:
            response = requests.post(verify_url, data=payload, timeout=5)
            result = response.json()
            
            # Validaciones clave:
            # 1. success debe ser True
            # 2. score debe ser aceptable (0.5 es un estándar seguro)
            # 3. action debe coincidir
            
            success = result.get('success', False)
            score = result.get('score', 0)
            action = result.get('action', '')
            
            if success and score >= 0.5 and action == action_name:
                return True
            
            logger.warning(f"Failed reCAPTCHA: success={success}, score={score}, action={action}, expected_action={action_name}")
            return False
            
        except Exception as e:
            logger.error(f"Error connecting to Google reCAPTCHA: {e}")
            # Fail safe: Block on error strongly recommended for security, 
            # but currently returning False to block.
            return False
