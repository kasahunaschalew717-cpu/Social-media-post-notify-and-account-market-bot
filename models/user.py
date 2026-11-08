import enum
from sqlalchemy import BigInteger, String, Float, Integer, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    SUPPORT = "SUPPORT"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False),
        default=UserRole.USER,
        nullable=False,
    )
    reputation_score: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    total_completed_deals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    seller_listings = relationship("MarketplaceListing", back_populates="seller")
    buyer_escrows = relationship("EscrowTransaction", foreign_keys="EscrowTransaction.buyer_id", back_populates="buyer")
    seller_escrows = relationship("EscrowTransaction", foreign_keys="EscrowTransaction.seller_id", back_populates="seller")

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id} username=@{self.username}>"

