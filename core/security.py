import hmac
import hashlib
import secrets
import string
import base64
from typing import Optional
from cryptography.fernet import Fernet
from core.config import settings
from core.logger import logger


def verify_hmac_sha1_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """
    Verifies YouTube PubSubHubbub X-Hub-Signature header.
    Format: sha1=<signature_hex>
    """
    if not signature_header or not signature_header.startswith("sha1="):
        return False

    expected_sig = signature_header.split("sha1=", 1)[1].strip()
    computed_mac = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha1
    ).hexdigest()

    return hmac.compare_digest(expected_sig, computed_mac)


def generate_verification_code(length: int = 6) -> str:
    """
    Generates a human-readable, non-forgeable challenge code.
    Example: VERIFY-8K2Q9P
    """
    alphabet = string.ascii_uppercase + string.digits
    # Remove ambiguous characters (0, O, 1, I)
    clean_alphabet = "".join([c for c in alphabet if c not in "0O1I"])
    random_part = "".join(secrets.choice(clean_alphabet) for _ in range(length))
    return f"VERIFY-{random_part}"


def generate_secure_token(nbytes: int = 24) -> str:
    """Generates a URL-safe random token for escrow secrets."""
    return secrets.token_urlsafe(nbytes)


def _get_fernet_cipher() -> Fernet:
    """Derives a Fernet instance from the application ENCRYPTION_KEY."""
    raw_key = settings.ENCRYPTION_KEY.encode("utf-8")
    # Fernet requires a 32-byte base64 encoded key
    hashed_32 = hashlib.sha256(raw_key).digest()
    b64_key = base64.urlsafe_b64encode(hashed_32)
    return Fernet(b64_key)


def encrypt_payload(plain_text: str) -> str:
    """Encrypts sensitive plaintext credentials (e.g. passwords, 2FA backup codes)."""
    cipher = _get_fernet_cipher()
    encrypted_bytes = cipher.encrypt(plain_text.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_payload(encrypted_text: str) -> Optional[str]:
    """Decrypts ciphertext into original plaintext."""
    try:
        cipher = _get_fernet_cipher()
        decrypted_bytes = cipher.decrypt(encrypted_text.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None

