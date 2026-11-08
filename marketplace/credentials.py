from typing import Optional, Tuple
from core.security import encrypt_payload, decrypt_payload, generate_secure_token
from core.redis_client import redis_service
from core.logger import logger


class SecureCredentialVault:
    """
    Handles secure one-time transfer of sensitive account credentials.
    Prevents credentials from lingering in unencrypted chat logs.
    Uses Fernet symmetric encryption and self-destructing tokens in Redis.
    """

    async def store_credentials(self, raw_credentials: str, escrow_ref: str) -> Tuple[str, str]:
        """
        Encrypts raw credentials and stores them in Redis with a 3-day TTL.
        Returns:
            token: URL-safe one-time retrieval token
            encrypted_payload: ciphertext for database audit/backup
        """
        token = generate_secure_token(32)
        encrypted_payload = encrypt_payload(raw_credentials)

        # Store in Redis with 72-hour TTL
        await redis_service.store_secret_credential(
            secret_token=token,
            credential_payload=encrypted_payload,
            ttl_seconds=86400 * 3,
        )

        logger.info(f"Stored encrypted credentials for escrow {escrow_ref} with one-time token {token[:8]}...")
        return token, encrypted_payload

    async def consume_credentials(self, token: str, encrypted_fallback: Optional[str] = None) -> Optional[str]:
        """
        Retrieves credentials and destroys the Redis key to ensure one-time delivery.
        Falls back to database decrypt if Redis key expired or peek requested.
        """
        # Pop from Redis (atomic get + delete)
        encrypted_data = await redis_service.pop_secret_credential(token)

        if not encrypted_data and encrypted_fallback:
            logger.info("Redis secret expired or empty; decrypting fallback payload from DB.")
            encrypted_data = encrypted_fallback

        if not encrypted_data:
            return None

        plain_text = decrypt_payload(encrypted_data)
        return plain_text


credential_vault = SecureCredentialVault()

