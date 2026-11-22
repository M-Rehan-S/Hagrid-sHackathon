"""Postgres enum labels frozen by PROPOSAL.md §5."""

from enum import Enum


class UserRole(str, Enum):
    citizen = "citizen"
    helper = "helper"
    officer = "officer"
    admin = "admin"
    auditor = "auditor"


class CaseType(str, Enum):
    relief_claim = "relief_claim"
    scam_report = "scam_report"


class ScamLabel(str, Enum):
    scam = "scam"
    legit = "legit"
    unsure = "unsure"


class CaseStatus(str, Enum):
    draft = "draft"
    needs_info = "needs_info"
    submitted = "submitted"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    closed = "closed"


class RouteType(str, Enum):
    auto_approve = "auto_approve"
    ask_more = "ask_more"
    human_review = "human_review"


class DecisionActor(str, Enum):
    ai = "ai"
    officer = "officer"


class DecisionOutcome(str, Enum):
    approved = "approved"
    rejected = "rejected"
    needs_more_proof = "needs_more_proof"
    human_review = "human_review"


class RuleStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ConsentStatus(str, Enum):
    granted = "granted"
    withdrawn = "withdrawn"


class ConsentScope(str, Enum):
    identity = "identity"
    documents = "documents"
    claim_data = "claim_data"
    contact = "contact"
