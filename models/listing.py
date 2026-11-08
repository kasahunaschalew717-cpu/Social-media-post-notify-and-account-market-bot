import enum
from datetime import datetime
from sqlalchemy import (
    String,
    Numeric,
    Integer,
    Float,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Enum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin
from models.monitored_source import PlatformType


class ListingStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    IN_ESCROW = "IN_ESCROW"
    SOLD = "SOLD"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class MarketplaceListing(Base, TimestampMixin):
    __tablename__ = "marketplace_listings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    platform: Mapped[PlatformType] = mapped_column(
        Enum(PlatformType, native_enum=False),
        nullable=False,
        index=True,
    )
    account_handle: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    account_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    asking_price_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, index=True)
    follower_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    engagement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    niche: Mapped[str] = mapped_column(String(64), default="General", nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    status: Mapped[ListingStatus] = mapped_column(
        Enum(ListingStatus, native_enum=False),
        default=ListingStatus.PENDING_VERIFICATION,
        nullable=False,
        index=True,
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    secondary_proof_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    seller = relationship("User", back_populates="seller_listings")
    verifications = relationship("OwnershipVerification", back_populates="listing", cascade="all, delete-orphan")
    escrows = relationship("EscrowTransaction", back_populates="listing")

    def __repr__(self) -> str:
        return f"<MarketplaceListing #{self.id} {self.platform.value}:{self.account_handle} (${self.asking_price_usd}) [{self.status.value}]>"

