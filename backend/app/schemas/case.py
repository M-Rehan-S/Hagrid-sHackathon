from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CaseType


class CaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citizen_id: UUID
    case_type: CaseType


class CaseFormPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_data_partial: dict[str, Any]
    last_step: str | None = Field(default=None, max_length=100)


class CaseAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    officer_id: UUID


class CaseNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=2000)


class OfficerDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["approved", "rejected", "needs_more_proof"]
    note: str = Field(min_length=1, max_length=2000)
