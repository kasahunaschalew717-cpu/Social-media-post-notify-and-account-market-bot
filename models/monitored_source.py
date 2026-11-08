import enum
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, JSON, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class PlatformType(str, enum.Enum):
    YOUTUBE = "YOUTUBE"
    TELEGRAM = "TELEGRAM"
    TIKTOK = "TIKTOK"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"


class MonitoredSource(Base, TimestampMixin):
    __tablename__ = "monitored_sources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[PlatformType] = mapped_column(
        Enum(PlatformType, native_enum=False),
        nullable=False,
        index=True,
    )
    handle: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_seen_post_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="source", cascade="all, delete-orphan")
    notification_logs = relationship("NotificationLog", back_populates="source", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<MonitoredSource {self.platform.value}:{self.handle} ({self.source_id})>"

