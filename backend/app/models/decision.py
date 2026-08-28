import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, DECIMAL, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class Decision(Base, UUIDMixin):
    __tablename__ = "decisions"

    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, unique=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # APPROVED, REJECTED, NEEDS_MORE_INFO
    chosen_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    chosen_offer_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("commercial_offers.id"), nullable=True)
    margin_at_decision: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    risk_level_at_decision: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
