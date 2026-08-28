import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import BigInteger, Boolean, DateTime, DECIMAL, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDMixin

class CommercialOffer(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "commercial_offers"
    lot_supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lot_suppliers.id"), nullable=False)
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False)
    source_communication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("communications.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PROCESSING")
    coverage: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    clarification_needed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    clarification_items: Mapped[List[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    total_cost: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    delivery_cost: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    total_cost_with_delivery: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    total_cost_with_all: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    margin_absolute: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    margin_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payment_terms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    delivery_terms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_text_snippet: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    positions: Mapped[List["OfferPosition"]] = relationship(back_populates="offer", cascade="all, delete-orphan")
    lot_supplier: Mapped["LotSupplier"] = relationship(back_populates="commercial_offers")

class OfferPosition(Base, UUIDMixin):
    __tablename__ = "offer_positions"
    commercial_offer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("commercial_offers.id"), nullable=False)
    tender_position_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("tender_positions.id"), nullable=True)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="not_found")
    match_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_per_unit: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 4), nullable=True)
    quantity_available: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 4), nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(nullable=True)
    nds_included: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    nds_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    offer: Mapped["CommercialOffer"] = relationship(back_populates="positions")

class CommunicationAttachment(Base, UUIDMixin):
    __tablename__ = "communication_attachments"
    communication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("communications.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, server_default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
