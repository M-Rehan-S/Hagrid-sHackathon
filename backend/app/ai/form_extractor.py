"""Form extraction module for POST /api/v1/ai/extract-form (PROPOSAL.md §7.5).

Primary path: Groq→Gemini LLM chat() with structured JSON prompt.
Fallback: deterministic regex extractor always present.

Returns::

    {
        "form": {<ClaimForm fields>},
        "missing_fields": [str, ...],
        "confidence": float,
    }
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.ai.llm_client import chat

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
ELIGIBLE_DISTRICTS = [
    "Karachi East", "Karachi West", "Karachi South", "Thatta", "Badin"
]

CLAIMFORM_FIELDS = [
    "full_name",
    "father_name",
    "cnic",
    "dob",
    "district",
    "household_size",
    "monthly_income",
    "is_widow",
    "phone",
]

REQUIRED_FIELDS = [
    "full_name",
    "cnic",
    "dob",
    "district",
    "monthly_income",
    "is_widow",
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM = """You are a form-extraction assistant for Pakistan's widow relief program.
Extract the following fields from the user's text and return ONLY valid JSON (no markdown).
Fields: full_name, father_name, cnic (13-digit number, no dashes), dob (YYYY-MM-DD),
district (one of: Karachi East, Karachi West, Karachi South, Thatta, Badin),
household_size (integer), monthly_income (integer PKR), is_widow (true/false), phone (11 digits starting 03).
Use null for any field not found. Output format:
{"full_name": null, "father_name": null, "cnic": null, "dob": null,
 "district": null, "household_size": null, "monthly_income": null,
 "is_widow": null, "phone": null}"""


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------
def _extract_llm(
    text: str, lang: str, existing_form: Optional[dict]
) -> Optional[dict]:
    context = ""
    if existing_form:
        context = f"\nExisting partial form: {json.dumps(existing_form, ensure_ascii=False)}"
    user_prompt = f"Text (lang={lang}):\n{text}{context}\n\nExtract and return JSON only."
    raw = chat(_SYSTEM, user_prompt)
    if not raw:
        return None
    # Strip markdown code blocks if present
    raw = re.sub(r"^```[a-z]*\n?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return _clean_form(data)
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Regex extraction fallback
# ---------------------------------------------------------------------------
def _extract_regex(text: str, existing_form: Optional[dict]) -> dict:
    form: dict[str, Any] = {f: None for f in CLAIMFORM_FIELDS}

    # CNIC: 13 consecutive digits (may have dashes)
    m = re.search(r"\b(\d{5}[-\s]?\d{7}[-\s]?\d)\b", text)
    if m:
        form["cnic"] = re.sub(r"[\s-]", "", m.group(1))

    # Phone: 03xxxxxxxxx (11 digits starting with 03)
    m = re.search(r"\b(03\d{9})\b", text)
    if m:
        form["phone"] = m.group(1)

    # District
    for dist in ELIGIBLE_DISTRICTS:
        if re.search(re.escape(dist), text, re.IGNORECASE):
            form["district"] = dist
            break

    # Monthly income: PKR followed by number, or just a number near income keywords
    m = re.search(
        r"(?:pkr|rs\.?|rupee[s]?|income|تنخواہ|آمدنی|aamdani)\s*[:\-]?\s*([\d,]+)",
        text,
        re.IGNORECASE,
    )
    if m:
        try:
            form["monthly_income"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Household size
    m = re.search(
        r"(?:household|family|afrad|bachay|members?)\s*[:\-]?\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    if m:
        try:
            form["household_size"] = int(m.group(1))
        except ValueError:
            pass

    # is_widow
    if re.search(r"\b(widow|bewa|بیوہ|marhoom\s+shohar|husband\s+died)\b", text, re.IGNORECASE):
        form["is_widow"] = True

    # DOB: common date patterns
    m = re.search(
        r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})\b", text
    )
    if m:
        raw_date = m.group(1)
        # Normalise to YYYY-MM-DD if possible
        parts = re.split(r"[-/]", raw_date)
        if len(parts) == 3:
            if len(parts[0]) == 4:
                form["dob"] = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
            else:
                form["dob"] = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"

    # Merge with existing_form (existing values win where our regex found nothing)
    if existing_form:
        for k, v in existing_form.items():
            if k in form and form[k] is None and v is not None:
                form[k] = v

    return form


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_form(raw: dict) -> dict:
    """Sanitise LLM output: keep only known fields, enforce types."""
    form: dict[str, Any] = {f: None for f in CLAIMFORM_FIELDS}
    for field in CLAIMFORM_FIELDS:
        val = raw.get(field)
        if val in (None, "", "null"):
            form[field] = None
        elif field == "cnic" and val:
            form[field] = re.sub(r"[\s-]", "", str(val))
        elif field in ("household_size", "monthly_income") and val is not None:
            try:
                form[field] = int(str(val).replace(",", ""))
            except (ValueError, TypeError):
                form[field] = None
        elif field == "is_widow" and val is not None:
            if isinstance(val, bool):
                form[field] = val
            else:
                form[field] = str(val).lower() in ("true", "yes", "1", "bewa", "widow")
        else:
            form[field] = val
    return form


def _compute_missing(form: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not form.get(f)]


def _confidence(form: dict) -> float:
    filled = sum(1 for f in CLAIMFORM_FIELDS if form.get(f) is not None)
    return round(filled / len(CLAIMFORM_FIELDS), 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract_form(
    text: str,
    lang: str = "ur",
    existing_form: Optional[dict] = None,
) -> dict:
    """Extract ClaimForm fields from free-form text.

    Returns:
        {"form": {...}, "missing_fields": [...], "confidence": float}
    """
    # Try LLM first; fall back to regex
    form = _extract_llm(text, lang, existing_form)
    if form is None:
        form = _extract_regex(text, existing_form)

    missing = _compute_missing(form)
    confidence = _confidence(form)
    return {"form": form, "missing_fields": missing, "confidence": confidence}
