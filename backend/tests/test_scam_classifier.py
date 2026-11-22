"""Tests for the ScamClassifier (backend/app/ai/scam_classifier.py).

These tests use the trained .joblib model already committed to disk.
"""

from __future__ import annotations

import pytest

from app.ai.scam_classifier import ScamClassifier, _keyword_check, load_classifier


# ---------------------------------------------------------------------------
# Unit tests: load_classifier
# ---------------------------------------------------------------------------

def test_load_classifier_returns_callable():
    clf = load_classifier()
    assert clf is not None, "Expected model file to be on disk"
    assert callable(clf)


# ---------------------------------------------------------------------------
# Unit tests: ScamClassifier output shape
# ---------------------------------------------------------------------------

def test_classifier_output_shape():
    clf = ScamClassifier()
    result = clf("Send your CNIC and PIN to claim BISP payment.")
    assert isinstance(result, dict)
    assert "label" in result
    assert "confidence" in result
    assert "category" in result
    assert "reasons" in result
    assert "advice_en" in result
    assert "advice_ur" in result
    assert result["label"] in ("scam", "legit", "unsure")
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["reasons"], list)


# ---------------------------------------------------------------------------
# Keyword override tests
# ---------------------------------------------------------------------------

def test_keyword_override_pin():
    result = _keyword_check("Please share your ATM pin to process your BISP payment.")
    assert result is not None
    assert result["label"] == "scam"
    assert result["confidence"] >= 0.90


def test_keyword_override_otp():
    result = _keyword_check("Your OTP is 123456. Share it immediately with the agent.")
    assert result is not None
    assert result["label"] == "scam"


def test_keyword_override_fee():
    result = _keyword_check("Pay Rs 500 processing fee before your relief is released.")
    assert result is not None
    assert result["label"] == "scam"


def test_keyword_override_link():
    result = _keyword_check("Click here bit.ly/abc to claim your BISP Rs 25000.")
    assert result is not None
    assert result["label"] == "scam"


def test_keyword_no_match_on_legit():
    result = _keyword_check("Your Ehsaas Kafaalat payment of Rs 14000 is ready. Visit nearest outlet with CNIC.")
    # Legit message should not trigger keyword override
    assert result is None


# ---------------------------------------------------------------------------
# ML model classification tests
# ---------------------------------------------------------------------------

def test_scam_message_classified():
    clf = ScamClassifier()
    result = clf("Mubarak! Ap ki lottery jeeti hai. Processing fee Rs 1000 bhejein aur CNIC share karein.")
    assert result["label"] in ("scam",)


def test_legit_message_classified():
    clf = ScamClassifier()
    result = clf("Your Ehsaas Kafaalat payment of Rs 14000 is credited. Visit nearest HBL bank with CNIC.")
    assert result["label"] in ("legit", "unsure")


def test_reasons_list_not_empty():
    clf = ScamClassifier()
    result = clf("Send your CNIC and OTP to verify your BISP account.")
    assert len(result["reasons"]) >= 1


def test_advice_en_non_empty():
    clf = ScamClassifier()
    result = clf("Fake Ehsaas message.")
    assert len(result["advice_en"]) > 10


def test_advice_ur_non_empty():
    clf = ScamClassifier()
    result = clf("Fake Ehsaas message.")
    assert len(result["advice_ur"]) > 10


def test_unsure_confidence_in_range():
    """confidence should always be in [0, 1]."""
    clf = ScamClassifier()
    for text in [
        "Some neutral message about Ehsaas program.",
        "BISP payment schedule updated.",
        "Call 8171 for information.",
    ]:
        result = clf(text)
        assert 0.0 <= result["confidence"] <= 1.0, f"confidence out of range for: {text}"
