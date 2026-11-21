from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    case_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    uploaded_by: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
