import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, DateTime, DECIMAL, Float, ForeignKey, String, Text, func, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDMixin

class Tender(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tenders"
    __table_args__ = (UniqueConstraint("source_id", "source_tender_id", name="idx_tenders_source_id"),)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tender_sources.id"), nullable=False)
    source_tender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    nmck: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="RUB")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    customer_inn: Mapped[str] = mapped_column(String(12), nullable=False, server_default="")
    customer_kpp: Mapped[str] = mapped_column(String(9), nullable=False, server_default="")
    platform: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    source_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="NEW")
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1536), nullable=True)
    structured_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    matched_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_components: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    selected_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True
    )
    final_margin_absolute: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    final_margin_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    risk_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    source: Mapped["TenderSource"] = relationship()
    category: Mapped[Optional["Category"]] = relationship("Category", foreign_keys=[matched_category_id])
    documents: Mapped[List["TenderDocument"]] = relationship(back_populates="tender", cascade="all, delete-orphan")
    positions: Mapped[List["TenderPosition"]] = relationship(back_populates="tender", cascade="all, delete-orphan")
    status_history: Mapped[List["TenderStatusHistory"]] = relationship(back_populates="tender", cascade="all, delete-orphan")
    lot_suppliers: Mapped[List["LotSupplier"]] = relationship(back_populates="tender", cascade="all, delete-orphan")
    decisions: Mapped[Optional["Decision"]] = relationship(back_populates="tender", uselist=False, cascade="all, delete-orphan")

class TenderDocument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tender_documents"
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, server_default="application/octet-stream")
    source_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    storage_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    parsed_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    parse_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tender: Mapped["Tender"] = relationship(back_populates="documents")

class TenderPosition(Base, UUIDMixin):
    __tablename__ = "tender_positions"
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False)
    position_number: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    characteristics: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    gost: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    okpd2: Mapped[str] = mapped_column(String(20), nullable=False, server_default="")
    quantity: Mapped[Decimal] = mapped_column(DECIMAL(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, server_default="шт")
    is_essential: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    tender: Mapped["Tender"] = relationship(back_populates="positions")

class TenderRequirement(Base, UUIDMixin):
    __tablename__ = "tender_requirements"
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, unique=True)
    delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    delivery_conditions: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    license_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    sro_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    security_bid: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    security_contract: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(18, 2), nullable=True)
    prepayment_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stages_count: Mapped[int] = mapped_column(nullable=False, server_default="1")
    special_conditions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

class TenderStatusHistory(Base, UUIDMixin):
    __tablename__ = "tender_status_history"
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    tender: Mapped["Tender"] = relationship(back_populates="status_history")
