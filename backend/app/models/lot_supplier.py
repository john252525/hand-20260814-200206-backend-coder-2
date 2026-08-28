import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDMixin

class LotSupplier(Base, UUIDMixin):
    __tablename__ = "lot_suppliers"
    __table_args__ = (UniqueConstraint("tender_id", "supplier_id", name="idx_ls_tender_supplier"),)
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="PENDING")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    match_relevance: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    tender: Mapped["Tender"] = relationship(back_populates="lot_suppliers")
    supplier: Mapped["Supplier"] = relationship()
    commercial_offers: Mapped[List["CommercialOffer"]] = relationship(back_populates="lot_supplier")
