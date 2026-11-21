from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.enums import RuleStatus


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    rule_key: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RuleStatus] = mapped_column(SqlEnum(RuleStatus, name="rule_status", values_callable=lambda enum: [item.value for item in enum]), nullable=False, server_default=text("'draft'"))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
