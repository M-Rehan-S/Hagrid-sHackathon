from datetime import date

from sqlalchemy import Date, DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base


class Citizen(Base):
    __tablename__ = "citizens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    father_name: Mapped[str | None] = mapped_column(String)
    cnic: Mapped[str | None] = mapped_column(String)
    dob: Mapped[date | None] = mapped_column(Date)
    district: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'ur'"))
    name_normalized: Mapped[str | None] = mapped_column(String)
    name_phonetic: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
