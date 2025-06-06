"""
Encryption utilities for sensitive data like API keys
"""
import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings


class EncryptionService:
    """Service for encrypting and decrypting sensitive data"""

    def __init__(self):
        self._fernet = self._get_fernet()

    def _get_fernet(self) -> Fernet:
        """Get Fernet instance for encryption/decryption"""
        # Use the secret key from settings as the encryption key base
        secret_key = settings.SECRET_KEY.encode()

        # Generate a consistent salt for key derivation
        salt = b'copilot_llm_salt'  # In production, this could be configurable

        # Derive a proper encryption key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret_key))
        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string and return base64 encoded ciphertext"""
        if not plaintext:
            return ""

        encrypted_data = self._fernet.encrypt(plaintext.encode())
        return base64.urlsafe_b64encode(encrypted_data).decode()

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt base64 encoded ciphertext and return plaintext string"""
        if not encrypted_data:
            return ""

        try:
            decoded_data = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_data = self._fernet.decrypt(decoded_data)
            return decrypted_data.decode()
        except Exception as e:
            raise ValueError(f"Failed to decrypt data: {e}")

    def is_encrypted(self, data: str) -> bool:
        """Check if a string appears to be encrypted (base64 encoded)"""
        if not data:
            return False

        try:
            # Try to decode as base64
            decoded = base64.urlsafe_b64decode(data.encode())
            # If it decodes and has reasonable length, likely encrypted
            return len(decoded) > 16  # Fernet adds overhead
        except Exception:
            return False


# Global encryption service instance
encryption_service = EncryptionService()
