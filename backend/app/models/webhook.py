import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin

class Webhook(Base, UUIDMixin):
    __tablename__ = "webhooks"
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
