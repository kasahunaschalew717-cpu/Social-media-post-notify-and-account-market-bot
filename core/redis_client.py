import redis.asyncio as aioredis
from typing import Optional
from core.config import settings
from core.logger import logger

redis_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
)


def get_redis_client() -> aioredis.Redis:
    """Returns an async Redis client."""
    return aioredis.Redis(connection_pool=redis_pool)


class RedisService:
    def __init__(self):
        self.redis = get_redis_client()

    async def is_post_duplicate(self, platform: str, post_id: str, ttl_seconds: int = 86400 * 7) -> bool:
        """
        Deduplication check using Redis SETNX with TTL.
        Returns True if the post was already seen, False if new.
        """
        key = f"seen_post:{platform}:{post_id}"
        is_new = await self.redis.set(key, "1", ex=ttl_seconds, nx=True)
        return not bool(is_new)

    async def store_secret_credential(self, secret_token: str, credential_payload: str, ttl_seconds: int = 86400 * 3) -> None:
        """Store encrypted credential with TTL (3 days by default)."""
        key = f"escrow:secret:{secret_token}"
        await self.redis.set(key, credential_payload, ex=ttl_seconds)

    async def pop_secret_credential(self, secret_token: str) -> Optional[str]:
        """
        One-time view retrieval: retrieves and deletes credential simultaneously
        to prevent subsequent snooping.
        """
        key = f"escrow:secret:{secret_token}"
        pipe = self.redis.pipeline()
        pipe.get(key)
        pipe.delete(key)
        results = await pipe.execute()
        return results[0] if results and results[0] else None

    async def peek_secret_credential(self, secret_token: str) -> Optional[str]:
        """Read credential without deleting (for backup recovery prior to expiration)."""
        key = f"escrow:secret:{secret_token}"
        return await self.redis.get(key)

    async def check_rate_limit(self, key_prefix: str, identifier: str, max_calls: int = 30, period_seconds: int = 60) -> bool:
        """
        Simple sliding/token counter rate limit.
        Returns True if allowed, False if exceeded.
        """
        key = f"ratelimit:{key_prefix}:{identifier}"
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, period_seconds)
        return current <= max_calls

    async def close(self):
        await self.redis.close()


redis_service = RedisService()

