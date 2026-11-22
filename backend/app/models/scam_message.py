from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.enums import ScamLabel


class ScamMessage(Base):
    __tablename__ = "scam_messages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[ScamLabel] = mapped_column(SqlEnum(ScamLabel, name="scam_label", values_callable=lambda enum: [item.value for item in enum]), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    category: Mapped[str | None] = mapped_column(String)
    area: Mapped[str | None] = mapped_column(String)
    reported_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
