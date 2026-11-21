from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IdentityLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cnic: str | None = None
    full_name: str | None = None
    father_name: str | None = None
    dob: date | None = None


class MockPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    amount: Decimal = Field(gt=0)


class MockComplaintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value
