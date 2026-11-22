from pydantic import BaseModel, ConfigDict, Field


class APIKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=120)
