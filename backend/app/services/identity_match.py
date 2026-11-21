"""
app/services/identity_match.py  —  Person B owns this file.

Implements:
  §8.1  normalize_name(name: str) -> str
  §8.1  name_phonetic_key(normalized: str) -> str
  §8.2  match_identity(form: dict) -> IdentityMatch

Consumes:
  app.models.mock_identity_record.MockIdentityRecord  (Person A delivers this)
  app.extensions.db                                   (Person A delivers this)

Returns:
  app.schemas.identity_match.IdentityMatch

COLLABORATION RULES (PROPOSAL.md §3):
  - Do NOT call any LLM here. This is a pure algorithmic service.
  - Do NOT write to audit_logs directly. The decision_engine calls audit.log().
  - Do NOT modify models/. Import only.
"""

import re
from typing import Optional

from rapidfuzz import fuzz
from doublemetaphone import doublemetaphone

from app.schemas.identity_match import IdentityCandidate, IdentityMatch


# ── §8.1  Constants ────────────────────────────────────────────────────────────

#: Honorifics stripped before matching.
HONORIFICS: frozenset[str] = frozenset({
    "mr", "mrs", "miss", "ms", "dr",
    "bibi", "begum", "sahib", "syed", "syeda", "khanum",
    "hafiz", "haji", "maulana", "sheikh", "chaudhry", "ch",
})

#: Canonical Pakistani name variant dictionary (§8.1).
#: Maps every alias → canonical form. Extend here when new variants surface.
NAME_VARIANTS: dict[str, str] = {
    # Muhammad
    "muhammad": "muhammad",
    "mohammad": "muhammad",
    "muhammed": "muhammad",
    "mohammed":  "muhammad",
    "mohd":      "muhammad",
    "md":        "muhammad",
    "muhamad":   "muhammad",
    "mohamad":   "muhammad",
    "muhamed":   "muhammad",
    # Ahmad / Ahmed
    "ahmed": "ahmad",
    "ahmad": "ahmad",
    "ahmd":  "ahmad",
    # Hussain
    "hussain": "hussain",
    "hussein": "hussain",
    "husain":  "hussain",
    "husein":  "hussain",
    # Ali
    "alee": "ali",
    "alie": "ali",
    # Fatima
    "fathima":  "fatima",
    "fatimah":  "fatima",
    "faatima":  "fatima",
    # Aisha / Ayesha
    "ayesha": "aisha",
    "aysha":  "aisha",
    "aaisha": "aisha",
    # Usman
    "osman":  "usman",
    "uthman": "usman",
    "othman": "usman",
    # Ibrahim
    "ebrahim":  "ibrahim",
    "ibraham":  "ibrahim",
    "ibraheem": "ibrahim",
    # Ismail
    "esmail":  "ismail",
    "ismael":  "ismail",
    "ismaeel": "ismail",
    # Abdul
    "abdull": "abdul",
    # Hassan
    "hasan":   "hassan",
    "hassaan": "hassan",
    # Khalid
    "khaled":  "khalid",
    "khaalid": "khalid",
    # Aslam
    "aslum": "aslam",
    # Bibi (kept as name token when not used as honorific)
    # Zainab
    "zainub": "zainab",
    "zeynab": "zainab",
}

# Common Urdu-script spellings translated to the same Latin tokens used by
# NAME_VARIANTS. Keep this deliberately token-based so mixed Urdu/Roman names
# normalize consistently without changing the matching algorithm.
URDU_NAME_TOKENS: dict[str, str] = {
    "محمد": "muhammad",
    "احمد": "ahmad",
    "حسین": "hussain",
    "علی": "ali",
    "فاطمہ": "fatima",
    "عائشہ": "aisha",
    "عثمان": "usman",
    "ابراہیم": "ibrahim",
    "اسماعیل": "ismail",
    "حسن": "hassan",
    "خالد": "khalid",
    "اسلم": "aslam",
    "زینب": "zainab",
    "خان": "khan",
    "بیبی": "bibi",
    "بی": "bibi",
    "بیگم": "begum",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


# ── §8.1  normalize_name ───────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """
    §8.1 — Normalise a name string for fuzzy comparison.

    Steps (exactly as specified):
      1. Lowercase; strip punctuation.
      2. Remove honorific tokens.
      3. Map each remaining token through NAME_VARIANTS (canonical collapse).

    Returns a whitespace-normalised string of canonical tokens.
    """
    if not name:
        return ""

    # Step 1
    s = name.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()

    # Steps 2 & 3
    tokens = []
    for token in s.split():
        token = URDU_NAME_TOKENS.get(token, token)
        if token in HONORIFICS:
            continue
        tokens.append(NAME_VARIANTS.get(token, token))

    return " ".join(tokens)


def name_phonetic_key(normalized: str) -> str:
    """
    §8.1 — Double Metaphone of each token joined by space.

    Stored as `name_phonetic` in citizens / mock_identity_records for
    phonetic-index lookups. Used by Person A's seed script and model hooks;
    exposed here so both Person A and Person B derive it the same way.
    """
    keys: list[str] = []
    for token in normalized.split():
        primary, _ = doublemetaphone(token)
        if primary:
            keys.append(primary)
    return " ".join(keys)


# ── §8.2  match_identity ───────────────────────────────────────────────────────

#: Minimum name similarity score to consider a record a candidate at all.
_MIN_CANDIDATE_SCORE: float = 50.0

#: "Within 5 points" threshold for the multi-candidate ambiguity rule.
_CLOSE_BAND: float = 5.0


def match_identity(form: dict) -> IdentityMatch:
    """
    §8.2 — Compare ClaimForm fields against mock_identity_records.

    Hard rules (§8.2):
      - Never match on name alone (always need CNIC or dob/father corroboration).
      - Never auto-merge duplicate people.
      - is_deceased=True on best match → flag is_deceased=True in result;
        decision_engine treats this as an anomaly (§8.5 step 7).

    Matching table (priority order):
      A. CNIC match + name_score >= 85       → exact,     conf formula
      B. CNIC match + name_score <  85       → ambiguous, 0.50
      C. No CNIC + name_score>=90 + (dob OR father>=85) → probable, 0.75
      D. Multiple candidates within 5 pts    → ambiguous, 0.50
      E. Anything else                       → none,      0.20

    Rules A and C are downgraded to ambiguous (0.50) if rule D fires too.
    """
    # Deferred imports — avoids circular deps and tolerates Person A's model
    # being wired up after this file is first imported.
    from app.extensions import db  # noqa: PLC0415
    from app.models.mock_identity_record import MockIdentityRecord  # noqa: PLC0415

    # -- Extract form fields ------------------------------------------------
    input_cnic: Optional[str] = (form.get("cnic") or "").strip() or None
    input_name: str = form.get("full_name", "")
    input_father: str = form.get("father_name", "")
    input_dob: Optional[str] = (form.get("dob") or "").strip() or None

    input_norm = normalize_name(input_name)
    input_father_norm = normalize_name(input_father)

    # -- Query mock registry -----------------------------------------------
    records: list[MockIdentityRecord] = db.session.query(MockIdentityRecord).all()

    if not records:
        return IdentityMatch(
            status="none",
            score=0.0,
            confidence=0.20,
            matched_record_id=None,
            candidates=[],
            reasons=["No records in identity registry"],
            is_deceased=False,
        )

    # -- Score every record ------------------------------------------------
    scored: list[dict] = []
    for rec in records:
        rec_norm = normalize_name(rec.full_name or "")
        name_score: float = fuzz.token_sort_ratio(input_norm, rec_norm)

        father_score: float = 0.0
        if input_father_norm and rec.father_name:
            father_score = fuzz.token_sort_ratio(
                input_father_norm, normalize_name(rec.father_name)
            )

        cnic_match = bool(
            input_cnic and rec.cnic and input_cnic == rec.cnic
        )
        dob_match = bool(
            input_dob and rec.dob and str(rec.dob) == input_dob
        )

        scored.append({
            "record_id":  str(rec.id),
            "name":        rec.full_name,
            "name_score":  name_score,
            "father_score": father_score,
            "cnic_match":  cnic_match,
            "dob_match":   dob_match,
            "is_deceased": bool(rec.is_deceased),
        })

    # Sort descending by name score
    scored.sort(key=lambda x: x["name_score"], reverse=True)
    best = scored[0]
    best_score: float = best["name_score"]

    # Candidates above the minimum threshold
    candidates_above_min = [
        s for s in scored if s["name_score"] >= _MIN_CANDIDATE_SCORE
    ]

    # "Close" candidates: within _CLOSE_BAND of the best score
    close: list[dict] = [
        s for s in candidates_above_min
        if s["name_score"] >= best_score - _CLOSE_BAND
    ]
    multi_close: bool = len(close) > 1

    # Build candidate list for the response (top 5)
    candidates_out: list[IdentityCandidate] = [
        IdentityCandidate(
            record_id=s["record_id"],
            name=s["name"],
            score=round(s["name_score"], 1),
        )
        for s in close[:5]
    ]

    reasons: list[str] = []

    # ── Rule A: CNIC matches ───────────────────────────────────────────────
    if best["cnic_match"]:
        reasons.append("CNIC matches")

        if best["name_score"] >= 85:
            reasons.append(
                f"Name similarity {best['name_score']:.1f} after normalization"
            )
            if multi_close:
                # Rule D fires — downgrade to ambiguous
                reasons.append(
                    f"{len(close)} candidates within {_CLOSE_BAND} points — ambiguous"
                )
                return _result(
                    "ambiguous", best_score, 0.50,
                    best["record_id"], candidates_out, reasons, best["is_deceased"],
                )
            # §8.2 exact confidence formula: 0.90 + 0.09*(score-85)/15, capped 0.99
            conf = round(0.90 + 0.09 * (best["name_score"] - 85.0) / 15.0, 3)
            conf = min(conf, 0.99)
            return _result(
                "exact", best_score, conf,
                best["record_id"], candidates_out, reasons, best["is_deceased"],
            )
        else:
            # Rule B: CNIC matches but name too weak
            reasons.append(
                f"Name similarity {best['name_score']:.1f} is below the 85 threshold"
            )
            return _result(
                "ambiguous", best_score, 0.50,
                best["record_id"], candidates_out, reasons, best["is_deceased"],
            )

    # ── Rule C: No/different CNIC — probable if name>=90 + secondary corr. ─
    if best["name_score"] >= 90:
        secondary = best["dob_match"] or best["father_score"] >= 85
        if secondary:
            if best["dob_match"]:
                reasons.append("Date of birth matches")
            if best["father_score"] >= 85:
                reasons.append(
                    f"Father name similarity {best['father_score']:.1f}"
                )
            reasons.append(
                f"Name similarity {best['name_score']:.1f} without CNIC"
            )
            if multi_close:
                # Rule D fires — downgrade to ambiguous
                reasons.append(
                    f"{len(close)} candidates within {_CLOSE_BAND} points — ambiguous"
                )
                return _result(
                    "ambiguous", best_score, 0.50,
                    best["record_id"], candidates_out, reasons, best["is_deceased"],
                )
            return _result(
                "probable", best_score, 0.75,
                best["record_id"], candidates_out, reasons, best["is_deceased"],
            )

    # ── Rule D: Multiple close candidates (name alone, no other corroboration)
    if multi_close:
        reasons.append(
            f"Multiple candidates within {_CLOSE_BAND} points of best "
            f"score {best_score:.1f} — cannot determine unique match"
        )
        return _result(
            "ambiguous", best_score, 0.50,
            None, candidates_out, reasons, False,
        )

    # ── Rule E: Nothing matched well enough ───────────────────────────────
    reasons.append(
        f"Best name similarity {best_score:.1f} — below any matching threshold"
    )
    return _result(
        "none", best_score, 0.20,
        None, candidates_out[:3], reasons, False,
    )


# ── Helper ────────────────────────────────────────────────────────────────────

def _result(
    status: str,
    score: float,
    confidence: float,
    matched_record_id: Optional[str],
    candidates: list[IdentityCandidate],
    reasons: list[str],
    is_deceased: bool,
) -> IdentityMatch:
    return IdentityMatch(
        status=status,
        score=round(score, 1),
        confidence=confidence,
        matched_record_id=matched_record_id,
        candidates=candidates,
        reasons=reasons,
        is_deceased=is_deceased,
    )
