import enum
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class VerificationMethod(str, enum.Enum):
    BIO_CODE = "BIO_CODE"
    COMMUNITY_POST = "COMMUNITY_POST"
    BOT_ADMIN_CHECK = "BOT_ADMIN_CHECK"
    SECONDARY_DASHBOARD_VIDEO = "SECONDARY_DASHBOARD_VIDEO"


class VerificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class OwnershipVerification(Base, TimestampMixin):
    __tablename__ = "ownership_verifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("marketplace_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    challenge_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    method: Mapped[VerificationMethod] = mapped_column(
        Enum(VerificationMethod, native_enum=False),
        default=VerificationMethod.BIO_CODE,
        nullable=False,
    )
    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, native_enum=False),
        default=VerificationStatus.PENDING,
        nullable=False,
        index=True,
    )
    verification_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    listing = relationship("MarketplaceListing", back_populates="verifications")

    def __repr__(self) -> str:
        return f"<OwnershipVerification listing_id={self.listing_id} code={self.challenge_code} status={self.status.value}>"

