import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "DualEngine-Telegram-Bot"
    DEBUG: bool = False
    BASE_WEBHOOK_URL: str = "https://yourdomain.com"
    API_PORT: int = 8000
    API_HOST: str = "0.0.0.0"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(..., description="Telegram Bot Token from @BotFather")
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = "super-secret-telegram-webhook-token"
    ADMIN_USER_IDS: List[int] = Field(default_factory=list, description="List of Telegram User IDs with admin privileges")

    # Database & Cache
    DATABASE_URL: str = Field(
        "postgresql+asyncpg://postgres:postgres@postgres:5432/telegram_bot_db",
        description="Async PostgreSQL connection string",
    )
    SYNC_DATABASE_URL: str = Field(
        "postgresql://postgres:postgres@postgres:5432/telegram_bot_db",
        description="Synchronous PostgreSQL connection string for Alembic/Celery",
    )
    REDIS_URL: str = Field("redis://redis:6379/0", description="Redis connection URL for cache and queues")
    CELERY_BROKER_URL: str = Field("redis://redis:6379/1", description="Celery broker URL")
    CELERY_RESULT_BACKEND: str = Field("redis://redis:6379/2", description="Celery result backend URL")

    # Security & Encryption
    SECRET_KEY: str = Field("replace-with-a-very-long-32-byte-secret-key-12345", description="App secret key for HMAC")
    ENCRYPTION_KEY: str = Field(
        "k_8V9QZ4l2pXvF6W3d8s9A1c4E7h0J2m",
        description="32-character key for AES credential encryption",
    )

    # YouTube / PubSubHubbub
    YOUTUBE_API_KEY: Optional[str] = None
    PUBSUBHUBBUB_HUB_URL: str = "https://pubsubhubbub.appspot.com/subscribe"
    PUBSUBHUBBUB_SECRET: str = "pubsubhubbub-shared-hmac-secret-string"

    # Meta Graph API (Instagram & Facebook)
    META_APP_ID: Optional[str] = None
    META_APP_SECRET: Optional[str] = None
    META_GRAPH_API_VERSION: str = "v19.0"
    INSTAGRAM_ACCESS_TOKEN: Optional[str] = None
    FACEBOOK_ACCESS_TOKEN: Optional[str] = None

    # TikTok Integration
    TIKTOK_CLIENT_KEY: Optional[str] = None
    TIKTOK_CLIENT_SECRET: Optional[str] = None
    APIFY_API_TOKEN: Optional[str] = None

    # Telegram Userbot / Client (Optional for private monitoring)
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_SESSION_STRING: Optional[str] = None

    # Marketplace & Escrow
    PLATFORM_ESCROW_FEE_PERCENT: float = 5.0  # 5% platform fee
    HIGH_VALUE_THRESHOLD_USD: float = 500.0   # $500 triggers secondary proof and 7-day cooling off
    INSPECTION_WINDOW_HOURS: int = 48         # 48 hours for buyer account review
    COOLING_OFF_PERIOD_DAYS: int = 7          # 7 days cooling off for high-value accounts
    LISTING_EXPIRY_DAYS: int = 30             # Listings expire in 30 days
    ESCROW_PAYMENT_WALLET_USDT_TRC20: str = "TX1234567890EscrowPlatformWalletAddress"


settings = Settings()

