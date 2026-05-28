import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, Float, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    price_monthly: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    price_yearly: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    paddle_price_id_monthly: Mapped[str] = mapped_column(String(255), nullable=True)
    paddle_price_id_yearly: Mapped[str] = mapped_column(String(255), nullable=True)
    paddle_product_id: Mapped[str] = mapped_column(String(255), nullable=True)
    words_per_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    words_per_request: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    modes: Mapped[dict] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
