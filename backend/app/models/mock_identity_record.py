from datetime import date

from sqlalchemy import Boolean, Date, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base


class MockIdentityRecord(Base):
    __tablename__ = "mock_identity_records"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    cnic: Mapped[str | None] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    father_name: Mapped[str | None] = mapped_column(String)
    dob: Mapped[date | None] = mapped_column(Date)
    district: Mapped[str | None] = mapped_column(String)
    name_normalized: Mapped[str | None] = mapped_column(String)
    name_phonetic: Mapped[str | None] = mapped_column(String)
    is_deceased: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
