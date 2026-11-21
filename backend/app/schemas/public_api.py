from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicScamCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=10000)


class ScamCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["scam", "legit", "unsure"]
    confidence: float = Field(ge=0, le=1)
    category: str | None = None
    reasons: list[str]
    advice_en: str
    advice_ur: str
