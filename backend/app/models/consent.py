from datetime import datetime

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.enums import ConsentScope, ConsentStatus, UserRole


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    citizen_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("citizens.id"), nullable=False)
    grantee_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))
    grantee_role: Mapped[UserRole | None] = mapped_column(
        SqlEnum(UserRole, name="user_role", values_callable=lambda enum: [item.value for item in enum])
    )
    scope: Mapped[ConsentScope] = mapped_column(
        SqlEnum(ConsentScope, name="consent_scope", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    status: Mapped[ConsentStatus] = mapped_column(
        SqlEnum(ConsentStatus, name="consent_status", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        server_default=text("'granted'"),
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
