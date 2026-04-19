from abc import ABC, abstractmethod

class CaptchaService(ABC):
    @abstractmethod
    def verify(self, token: str, action_name: str) -> bool:
        """
        Verifies the captcha token.
        :param token: The token provided by the client.
        :param action_name: The expected action name.
        :return: True if valid, False otherwise.
        """
        pass
