import enum
from datetime import datetime
from sqlalchemy import (
    String,
    Numeric,
    Integer,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Enum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class EscrowStatus(str, enum.Enum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    FUNDS_HELD = "FUNDS_HELD"
    TRANSFER_IN_PROGRESS = "TRANSFER_IN_PROGRESS"
    BUYER_CONFIRMATION_PENDING = "BUYER_CONFIRMATION_PENDING"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class EscrowTransaction(Base, TimestampMixin):
    __tablename__ = "escrow_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    escrow_reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    
    listing_id: Mapped[int] = mapped_column(ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    fee_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    seller_receives_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    status: Mapped[EscrowStatus] = mapped_column(
        Enum(EscrowStatus, native_enum=False),
        default=EscrowStatus.AWAITING_PAYMENT,
        nullable=False,
        index=True,
    )

    payment_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Secure credential exchange
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    one_time_view_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_credentials_viewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Deadlines and protection periods
    inspection_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooling_off_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Disputes & resolutions
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    disputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Ratings
    buyer_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seller_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    listing = relationship("MarketplaceListing", back_populates="escrows")
    buyer = relationship("User", foreign_keys=[buyer_id], back_populates="buyer_escrows")
    seller = relationship("User", foreign_keys=[seller_id], back_populates="seller_escrows")

    def __repr__(self) -> str:
        return f"<EscrowTransaction {self.escrow_reference} (${self.amount_usd}) [{self.status.value}]>"

