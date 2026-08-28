import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import DateTime, DECIMAL, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDMixin

class Decision(Base, UUIDMixin):
    __tablename__ = "decisions"
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, unique=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    chosen_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    chosen_offer_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("commercial_offers.id"), nullable=True)
    margin_at_decision: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    risk_level_at_decision: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    risk_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Relationships
    tender: Mapped["Tender"] = relationship(back_populates="decisions")
    chosen_supplier: Mapped[Optional["Supplier"]] = relationship("Supplier", foreign_keys=[chosen_supplier_id])
    chosen_offer: Mapped[Optional["CommercialOffer"]] = relationship("CommercialOffer", foreign_keys=[chosen_offer_id])
