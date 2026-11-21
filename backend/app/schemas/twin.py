from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TwinSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_rule_id: UUID
    limit: int | None = Field(default=None, ge=1)
