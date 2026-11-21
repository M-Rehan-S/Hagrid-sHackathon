from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import ConsentScope, UserRole


class ConsentGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citizen_id: UUID
    grantee_user_id: UUID | None = None
    grantee_role: UserRole | None = None
    scope: ConsentScope

    @model_validator(mode="after")
    def validate_exactly_one_grantee(self):
        if (self.grantee_user_id is None) == (self.grantee_role is None):
            raise ValueError("exactly one of grantee_user_id or grantee_role is required")
        return self
