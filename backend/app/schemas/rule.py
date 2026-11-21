from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in"]
    value: Any
    reason_en: str = ""
    reason_ur: str = ""


class RuleThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_approve: float = Field(ge=0, le=1)
    ask_more: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def thresholds_are_ordered(self):
        if self.ask_more > self.auto_approve:
            raise ValueError("ask_more must not exceed auto_approve")
        return self


class RuleCost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wrong_approval: float = Field(gt=0)
    manual_review: float = Field(ge=0)


class AnomalyToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class HelperBurstRule(AnomalyToggle):
    max_per_window: int = Field(ge=0)
    window_minutes: int = Field(gt=0)
    max_per_day: int = Field(ge=0)


class RuleAnomaly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duplicate_open_claim: AnomalyToggle
    helper_burst: HelperBurstRule
    deceased_match: AnomalyToggle


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_key: str = Field(min_length=1)
    match: Literal["all"]
    conditions: list[RuleCondition]
    required_documents: list[str]
    amount: float = Field(gt=0)
    thresholds: RuleThresholds
    cost: RuleCost
    anomaly: RuleAnomaly

    @model_validator(mode="after")
    def auto_approval_respects_costs(self):
        minimum = 1 - self.cost.manual_review / self.cost.wrong_approval
        if self.thresholds.auto_approve < minimum:
            raise ValueError("auto_approve is below the cost-derived minimum threshold")
        return self


class RuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_key: str = Field(min_length=1)
    definition: RuleDefinition
    note: str | None = None

    @model_validator(mode="after")
    def definition_key_matches_request(self):
        if self.definition.rule_key != self.rule_key:
            raise ValueError("definition.rule_key must match rule_key")
        return self
