from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class ProcessedEvent(Base):
    """Used to guarantee webhook idempotency and avoid duplicate processing."""
    __tablename__ = "processed_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(256), unique=True, index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ProcessedEvent {self.source}:{self.event_id}>"

