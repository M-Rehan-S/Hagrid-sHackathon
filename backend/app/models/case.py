from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, DateTime, Enum as SqlEnum, ForeignKey, Numeric, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.enums import CaseStatus, CaseType, RouteType


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    case_type: Mapped[CaseType] = mapped_column(SqlEnum(CaseType, name="case_type", values_callable=lambda enum: [item.value for item in enum]), nullable=False)
    citizen_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("citizens.id"), nullable=False)
    created_by: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_to: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[CaseStatus] = mapped_column(SqlEnum(CaseStatus, name="case_status", values_callable=lambda enum: [item.value for item in enum]), nullable=False, server_default=text("'draft'"))
    route: Mapped[RouteType | None] = mapped_column(SqlEnum(RouteType, name="route_type", values_callable=lambda enum: [item.value for item in enum]))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("2"))
    form_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    missing_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    rule_version_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"))
    last_step: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
