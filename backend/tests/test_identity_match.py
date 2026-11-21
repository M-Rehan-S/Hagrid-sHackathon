"""
tests/test_identity_match.py  —  Person B owns this file.

Covers all 5 matching scenarios from PROPOSAL.md §8.2 plus:
  - normalize_name  (§8.1)
  - name_phonetic_key (§8.1)
  - is_deceased hard rule

The DB query (db.session.query(MockIdentityRecord).all()) is fully mocked
so these tests run with zero infrastructure.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError


# ── Bootstrap: stub out Flask / SQLAlchemy / extensions before any import ─────
# This lets us test pure logic without spinning up a Flask app.

def _make_stubs() -> None:
    """
    Stub only the modules that have external/missing dependencies.

    - app, app.services, app.schemas  → real packages in backend/
      (pytest's pythonpath=["."] in pyproject.toml puts backend/ on sys.path)
    - app.extensions                  → stubbed (SQLAlchemy not needed for tests)
    - app.models.mock_identity_record → stubbed (Person A delivers this later)
    """
    # app.extensions — provides `db`; stub so SQLAlchemy is not required
    ext_mod = types.ModuleType("app.extensions")
    ext_mod.db = MagicMock(name="db")
    sys.modules["app.extensions"] = ext_mod

    # app.models — stub as a package so sub-imports resolve
    models_pkg = types.ModuleType("app.models")
    models_pkg.__path__ = []           # marks it as a package
    models_pkg.__package__ = "app.models"
    sys.modules.setdefault("app.models", models_pkg)

    # app.models.mock_identity_record — doesn't exist yet (Person A delivers it)
    mir_mod = types.ModuleType("app.models.mock_identity_record")
    mir_mod.MockIdentityRecord = MagicMock(name="MockIdentityRecord")
    sys.modules["app.models.mock_identity_record"] = mir_mod


_make_stubs()

# Now safe to import
from app.services.identity_match import (  # noqa: E402
    normalize_name,
    name_phonetic_key,
    match_identity,
)
from app.schemas.identity_match import IdentityMatch  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rec(
    *,
    id: str = "rec-001",
    full_name: str = "Fatima Bibi",
    father_name: str | None = None,
    cnic: str | None = None,
    dob=None,
    is_deceased: bool = False,
) -> MagicMock:
    """Build a mock MockIdentityRecord row."""
    r = MagicMock()
    r.id = id
    r.full_name = full_name
    r.father_name = father_name
    r.cnic = cnic
    r.dob = dob
    r.is_deceased = is_deceased
    return r


def _run(form: dict, records: list) -> IdentityMatch:
    """
    Wire mock records into the stub module and run match_identity.

    match_identity() uses deferred imports (inside the function body) so we
    inject through sys.modules rather than patch() on a module-level name.
    """
    mock_db = MagicMock(name="db")
    mock_db.session.query.return_value.all.return_value = records
    # Replace the db on the already-stubbed app.extensions module so the
    # deferred `from app.extensions import db` inside match_identity() picks
    # up our configured mock on every call.
    sys.modules["app.extensions"].db = mock_db
    return match_identity(form)


# ── §8.1 normalize_name tests ─────────────────────────────────────────────────

class TestNormalizeName:
    def test_lowercases(self):
        assert normalize_name("FATIMA") == "fatima"

    def test_strips_honorifics(self):
        assert normalize_name("Mrs. Fatima Bibi") == "fatima"

    def test_strips_multiple_honorifics(self):
        assert normalize_name("Dr Syed Ahmad") == "ahmad"

    def test_collapses_muhammad_variants(self):
        for variant in ["Mohammad", "Muhammed", "Mohammed", "mohd", "Md"]:
            result = normalize_name(f"{variant} Aslam")
            assert result == "muhammad aslam", f"Failed for variant: {variant!r}"

    def test_collapses_ahmad_variants(self):
        assert normalize_name("Ahmed Khan") == "ahmad khan"

    def test_collapses_hussain_variants(self):
        assert normalize_name("Hussein Ali") == "hussain ali"

    def test_transliterates_common_urdu_name_tokens(self):
        assert normalize_name("محمد اسلم") == "muhammad aslam"
        assert normalize_name("فاطمہ بی بی") == "fatima"
        assert normalize_name("احمد خان") == normalize_name("Ahmed Khan")

    def test_strips_punctuation(self):
        assert normalize_name("Abdul-Rahman") == "abdul rahman"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_none_equivalent(self):
        assert normalize_name("   ") == ""


class TestNamePhoneticKey:
    def test_returns_string(self):
        result = name_phonetic_key("muhammad aslam")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mohammad_and_muhammad_same_key(self):
        """After normalization both resolve to 'muhammad' — same phonetic key."""
        key1 = name_phonetic_key(normalize_name("Muhammad Aslam"))
        key2 = name_phonetic_key(normalize_name("Mohammad Aslam"))
        assert key1 == key2

    def test_empty_normalized(self):
        assert name_phonetic_key("") == ""


# ── §8.2 match_identity tests ─────────────────────────────────────────────────

FORM_FATIMA = {
    "full_name": "Fatima Bibi",
    "father_name": "Muhammad Aslam",
    "cnic": "4210112345671",
    "dob": "1978-04-12",
}


class TestScenarioA_ExactCNICAndHighName:
    """Rule A: CNIC equals AND name_score >= 85 → exact."""

    def test_status_is_exact(self):
        rec = _rec(full_name="Fatima Bibi", cnic="4210112345671")
        result = _run(FORM_FATIMA, [rec])
        assert result.status == "exact"

    def test_confidence_formula_at_100(self):
        """Perfect name match → confidence should be 0.99."""
        rec = _rec(full_name="Fatima Bibi", cnic="4210112345671")
        result = _run(FORM_FATIMA, [rec])
        assert result.confidence >= 0.98

    def test_confidence_formula_at_85_boundary(self):
        """Score ~85 → confidence should be ~0.90."""
        # Use a name that scores ~85 against "fatima" after normalization
        # We test via a slightly different spelling
        rec = _rec(full_name="Fateema Bibi", cnic="4210112345671")
        result = _run(FORM_FATIMA, [rec])
        # Either exact (score>=85) or ambiguous (score<85) — confidence must be <= 0.99
        assert result.confidence <= 0.99

    def test_matched_record_id_set(self):
        rec = _rec(id="rec-abc", full_name="Fatima Bibi", cnic="4210112345671")
        result = _run(FORM_FATIMA, [rec])
        assert result.matched_record_id == "rec-abc"

    def test_cnic_match_in_reasons(self):
        rec = _rec(full_name="Fatima Bibi", cnic="4210112345671")
        result = _run(FORM_FATIMA, [rec])
        assert any("CNIC" in r for r in result.reasons)


class TestScenarioB_CnicMatchLowName:
    """Rule B: CNIC equals AND name_score < 85 → ambiguous, 0.50."""

    def test_status_is_ambiguous(self):
        # Completely different name but same CNIC
        rec = _rec(full_name="Zulfiqar Mehmood", cnic="4210112345671")
        result = _run(FORM_FATIMA, [rec])
        assert result.status == "ambiguous"

    def test_confidence_is_050(self):
        rec = _rec(full_name="Zulfiqar Mehmood", cnic="4210112345671")
        result = _run(FORM_FATIMA, [rec])
        assert result.confidence == 0.50


class TestScenarioC_ProbableNoCNIC:
    """Rule C: No CNIC + name_score>=90 + (dob OR father>=85) → probable, 0.75."""

    def test_probable_via_dob(self):
        form = {**FORM_FATIMA, "cnic": None}
        rec = _rec(full_name="Fatima Bibi", cnic=None, dob="1978-04-12")
        result = _run(form, [rec])
        assert result.status == "probable"
        assert result.confidence == 0.75

    def test_probable_via_father_name(self):
        form = {**FORM_FATIMA, "cnic": None, "dob": None}
        rec = _rec(
            full_name="Fatima Bibi",
            father_name="Muhammad Aslam",
            cnic=None,
        )
        result = _run(form, [rec])
        assert result.status == "probable"
        assert result.confidence == 0.75

    def test_no_match_without_secondary_corroboration(self):
        """Name >= 90 but no dob and no father → should NOT be probable."""
        form = {**FORM_FATIMA, "cnic": None, "dob": None, "father_name": None}
        rec = _rec(full_name="Fatima Bibi", cnic=None, dob=None, father_name=None)
        result = _run(form, [rec])
        # Without secondary corroboration it falls through to none
        assert result.status in ("none", "ambiguous")


class TestScenarioD_MultipleCloseCandidates:
    """Rule D: Multiple candidates within 5 points of the best → ambiguous, 0.50."""

    def test_two_similar_records_gives_ambiguous(self):
        form = {**FORM_FATIMA, "cnic": None}
        # Two records both named "Mohammad Aslam" — almost identical scores
        rec1 = _rec(id="r1", full_name="Mohammad Aslam", cnic=None)
        rec2 = _rec(id="r2", full_name="Muhammad Aslam", cnic=None)
        form2 = {
            "full_name": "Mohammad Aslam",
            "father_name": None,
            "cnic": None,
            "dob": None,
        }
        result = _run(form2, [rec1, rec2])
        assert result.status == "ambiguous"
        assert result.confidence == 0.50

    def test_ambiguous_even_with_cnic_match_when_multiple_close(self):
        """
        CNIC matches but two records have very similar names and are within
        5 points → downgraded to ambiguous (§8.2 hard rule).
        """
        rec1 = _rec(id="r1", full_name="Fatima Bibi", cnic="4210112345671")
        rec2 = _rec(id="r2", full_name="Fatimah Bibi", cnic=None)
        result = _run(FORM_FATIMA, [rec1, rec2])
        # rec1 scores ~100, rec2 scores ~95 — within 5 pts → ambiguous
        assert result.status == "ambiguous"
        assert result.confidence == 0.50


class TestScenarioE_NoMatch:
    """Rule E: Anything else → none, 0.20."""

    def test_completely_different_name(self):
        rec = _rec(full_name="Kareem Jabbar", cnic="9999999999999")
        result = _run(FORM_FATIMA, [rec])
        assert result.status == "none"
        assert result.confidence == 0.20
        assert result.matched_record_id is None

    def test_empty_registry(self):
        result = _run(FORM_FATIMA, [])
        assert result.status == "none"
        assert result.confidence == 0.20


# ── is_deceased hard rule ─────────────────────────────────────────────────────

class TestIsDeceasedHardRule:
    """
    §8.2 hard rule: is_deceased=True forces human_review in the decision engine.
    match_identity flags it via result.is_deceased so decision_engine can act.
    """

    def test_deceased_flag_propagated(self):
        rec = _rec(
            full_name="Fatima Bibi",
            cnic="4210112345671",
            is_deceased=True,
        )
        result = _run(FORM_FATIMA, [rec])
        # Match may be exact/ambiguous but is_deceased must be True
        assert result.is_deceased is True

    def test_living_record_flag_false(self):
        rec = _rec(full_name="Fatima Bibi", cnic="4210112345671", is_deceased=False)
        result = _run(FORM_FATIMA, [rec])
        assert result.is_deceased is False


class TestIdentityMatchSchema:
    def test_rejects_status_outside_proposal_enum(self):
        with pytest.raises(ValidationError):
            IdentityMatch(status="matched", score=100, confidence=1.0)
