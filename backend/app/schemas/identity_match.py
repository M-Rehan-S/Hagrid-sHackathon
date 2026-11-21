"""
app/schemas/identity_match.py

Pydantic v2 schema for IdentityMatch — the output of match_identity().
Shape is frozen by PROPOSAL.md §6.2.

Internal field `is_deceased` is NOT in the API response; it is used by
decision_engine.py (§8.5 step 7) to flag a deceased record as an anomaly.
"""

from typing import Optional
from pydantic import BaseModel, Field


class IdentityCandidate(BaseModel):
    """One candidate from mock_identity_records (§6.2 candidates array)."""
    record_id: str
    name: str
    score: float


class IdentityMatch(BaseModel):
    """
    Result of match_identity(form).
    Frozen field names from PROPOSAL.md §6.2 — do not rename.
    """
    # §6.2 fields (exposed in API trace)
    status: str          # "exact" | "probable" | "ambiguous" | "none"
    score: float         # best name similarity score 0..100
    confidence: float    # 0..1 — fed into decision_engine confidence formula
    matched_record_id: Optional[str] = None
    candidates: list[IdentityCandidate] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    # Internal only — used by decision_engine §8.5 step 7 anomaly check.
    # Never serialised into the public API envelope.
    is_deceased: bool = Field(default=False, exclude=True)
