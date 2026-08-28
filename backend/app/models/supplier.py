from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, DECIMAL, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class Supplier(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown")
    website: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    phone: Mapped[str] = mapped_column(String(50), nullable=False, server_default="")
    telegram: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    whatsapp: Mapped[str] = mapped_column(String(50), nullable=False, server_default="")
    contact_persons: Mapped[List[dict]] = mapped_column(JSONB, nullable=False, server_default="[]")
    inn: Mapped[str] = mapped_column(String(12), nullable=False, server_default="")
    kpp: Mapped[str] = mapped_column(String(9), nullable=False, server_default="")
    ogrn: Mapped[str] = mapped_column(String(15), nullable=False, server_default="")
    legal_address: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    tags: Mapped[List[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    rating: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{"avg_response_time_hours": null, "response_rate": 0, "price_competitiveness": 0, "reliability": 0}')
    total_lots: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    successful_deals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_volume_rub: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
