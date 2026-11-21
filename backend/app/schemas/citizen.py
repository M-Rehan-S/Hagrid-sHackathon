from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CitizenCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    father_name: str | None = Field(default=None, max_length=200)
    cnic: str | None = Field(default=None, max_length=15)
    dob: date | None = None
    district: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
