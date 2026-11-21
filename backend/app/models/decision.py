from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.enums import DecisionActor, DecisionOutcome, RouteType


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    case_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("cases.id"), nullable=False)
    actor_type: Mapped[DecisionActor] = mapped_column(SqlEnum(DecisionActor, name="decision_actor", values_callable=lambda enum: [item.value for item in enum]), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))
    route: Mapped[RouteType | None] = mapped_column(SqlEnum(RouteType, name="route_type", values_callable=lambda enum: [item.value for item in enum]))
    outcome: Mapped[DecisionOutcome] = mapped_column(SqlEnum(DecisionOutcome, name="decision_outcome", values_callable=lambda enum: [item.value for item in enum]), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    rule_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("rules.id"))
    model_version: Mapped[str | None] = mapped_column(String)
    reason_en: Mapped[str] = mapped_column(String, nullable=False)
    reason_ur: Mapped[str] = mapped_column(String, nullable=False)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
