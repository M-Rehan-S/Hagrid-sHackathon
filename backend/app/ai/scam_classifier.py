"""Scam classifier backed by a scikit-learn pipeline (PROPOSAL.md §8.3).

The callable returned by ``load_classifier()`` accepts a text string and
returns a dict matching ``ScamCheckResult`` (label, confidence, category,
reasons, advice_en, advice_ur).

Label thresholds per PROPOSAL.md §8.3:
  p_scam >= 0.85  → "scam"
  p_scam <= 0.15  → "legit"
  otherwise       → "unsure"
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

MODEL_PATH = Path(__file__).parent / "models" / "scam_classifier.joblib"

# ---------------------------------------------------------------------------
# Hard-coded keyword overrides (always fire before the ML model)
# ---------------------------------------------------------------------------
_SCAM_PATTERNS = [
    (r"\bpin\b", "Requests PIN"),
    (r"\botp\b", "Requests OTP"),
    (r"\bprocessing fee\b|\bregistration fee\b|\badvance fee\b", "Demands advance fee"),
    (r"send.*cnic|cnic.*send|cnic.*bhej|bhej.*cnic", "Requests CNIC via messaging"),
    (r"bit\.ly|tinyurl|\.tk/|\.info/|\.net/claim|\.com/claim", "Contains suspicious shortened/unofficial link"),
    (r"(?:(?!bisp\.gov\.pk|ehsaas\.gov\.pk|nadra\.gov\.pk|finance\.gov\.pk))\S+\.(?:tk|xyz|info|site|online|store)\b", "Suspicious domain"),
    (r"account\s*(number|no)?\s*(send|share|bhej|batao)", "Requests bank account details"),
]

_CATEGORIES = {
    "otp": "otp_phishing",
    "pin": "pin_phishing",
    "fee": "advance_fee_fraud",
    "cnic": "identity_theft",
    "link": "malicious_link",
    "account": "bank_fraud",
    "default": "general_scam",
}

_ADVICE_EN = {
    "scam": (
        "This message appears to be a scam. Do not share your CNIC, OTP, PIN, or bank details. "
        "BISP/Ehsaas never asks for advance fees or sensitive data via SMS or calls. "
        "Report fraud at 0800-26477 or SMS 8171."
    ),
    "unsure": (
        "This message is unverified. Be cautious. Never share OTP, PIN, or bank details. "
        "Verify by calling the official helpline: 0800-26477 or 8171."
    ),
    "legit": (
        "This message appears to be from an official government or bank source. "
        "Always verify by calling 8171 or 0800-26477 if you have doubts."
    ),
}

_ADVICE_UR = {
    "scam": (
        "یہ پیغام ایک فراڈ لگتا ہے۔ اپنا CNIC، OTP، PIN یا بینک تفصیلات شیئر نہ کریں۔ "
        "فراڈ رپورٹ کرنے کے لیے 0800-26477 یا 8171 پر کال کریں۔"
    ),
    "unsure": (
        "یہ پیغام غیر تصدیق شدہ ہے۔ احتیاط برتیں۔ OTP، PIN یا بینک تفصیلات کبھی شیئر نہ کریں۔ "
        "سرکاری ہیلپ لائن 8171 سے تصدیق کریں۔"
    ),
    "legit": (
        "یہ پیغام کسی سرکاری ادارے یا بینک کی جانب سے لگتا ہے۔ "
        "شک ہو تو 8171 یا 0800-26477 پر رابطہ کریں۔"
    ),
}


def _keyword_check(text: str) -> Optional[dict]:
    """Return a scam result if any hard keyword pattern fires, else None."""
    lower = text.lower()
    fired_reasons = []
    fired_category = None
    for pattern, reason in _SCAM_PATTERNS:
        if re.search(pattern, lower):
            fired_reasons.append(reason)
            if fired_category is None:
                # Categorise by which keyword fired first
                if "pin" in pattern:
                    fired_category = _CATEGORIES["pin"]
                elif "otp" in pattern:
                    fired_category = _CATEGORIES["otp"]
                elif "fee" in pattern:
                    fired_category = _CATEGORIES["fee"]
                elif "cnic" in pattern or "link" in pattern:
                    fired_category = _CATEGORIES["link"]
                elif "account" in pattern:
                    fired_category = _CATEGORIES["account"]
                else:
                    fired_category = _CATEGORIES["default"]
    if fired_reasons:
        return {
            "label": "scam",
            "confidence": 0.95,
            "category": fired_category or _CATEGORIES["default"],
            "reasons": fired_reasons,
            "advice_en": _ADVICE_EN["scam"],
            "advice_ur": _ADVICE_UR["scam"],
        }
    return None


def _infer_category(text_lower: str) -> str:
    if re.search(r"\botp\b", text_lower):
        return _CATEGORIES["otp"]
    if re.search(r"\bpin\b", text_lower):
        return _CATEGORIES["pin"]
    if re.search(r"fee|advance", text_lower):
        return _CATEGORIES["fee"]
    if re.search(r"cnic", text_lower):
        return _CATEGORIES["identity_theft"]
    if re.search(r"link|bit\.ly|tinyurl|click", text_lower):
        return _CATEGORIES["link"]
    if re.search(r"account|bank", text_lower):
        return _CATEGORIES["account"]
    return "fake_relief"


def _build_reasons(text_lower: str, p_scam: float) -> list[str]:
    reasons = []
    if re.search(r"\botp\b", text_lower):
        reasons.append("Requests a one-time password (OTP).")
    if re.search(r"\bpin\b", text_lower):
        reasons.append("Requests a PIN number.")
    if re.search(r"fee|charge", text_lower):
        reasons.append("Demands an upfront payment or processing fee.")
    if re.search(r"bit\.ly|tinyurl|click here|click link", text_lower):
        reasons.append("Contains a suspicious or shortened link.")
    if re.search(r"cnic.*send|send.*cnic|cnic.*bhej", text_lower):
        reasons.append("Asks to send CNIC details via messaging.")
    if not reasons and p_scam >= 0.85:
        reasons.append("Message pattern matches known scam templates.")
    if not reasons:
        reasons.append("No specific red flags detected.")
    return reasons


class ScamClassifier:
    """Loads the scikit-learn pipeline and classifies text."""

    def __init__(self):
        import joblib
        self._pipeline = joblib.load(MODEL_PATH)
        # Determine which index corresponds to "scam"
        classes = list(self._pipeline.classes_)
        self._scam_idx = classes.index("scam")

    def __call__(self, text: str) -> dict:
        # 1. Keyword hard override
        kw = _keyword_check(text)
        if kw is not None:
            return kw

        # 2. ML model
        proba = self._pipeline.predict_proba([text])[0]
        p_scam = float(proba[self._scam_idx])

        if p_scam >= 0.85:
            label = "scam"
        elif p_scam <= 0.15:
            label = "legit"
        else:
            label = "unsure"

        confidence = round(max(p_scam, 1.0 - p_scam), 3)
        text_lower = text.lower()
        return {
            "label": label,
            "confidence": confidence,
            "category": _infer_category(text_lower) if label != "legit" else None,
            "reasons": _build_reasons(text_lower, p_scam),
            "advice_en": _ADVICE_EN[label],
            "advice_ur": _ADVICE_UR[label],
        }


def load_classifier() -> Optional[ScamClassifier]:
    """Return a ScamClassifier instance, or None if the model file is missing."""
    if not MODEL_PATH.exists():
        return None
    try:
        return ScamClassifier()
    except Exception:
        return None
