"""SQLAlchemy mappings for proposal-owned database tables.

The numbered SQL migrations own DDL; these mappings only describe existing
tables and are never used with ``metadata.create_all``.
"""

from app.models.audit_log import AuditLog
from app.models.api_key import APIKey
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.citizen import Citizen
from app.models.consent import Consent
from app.models.decision import Decision
from app.models.document import Document
from app.models.eval_run import EvalRun
from app.models.helper_citizen_link import HelperCitizenLink
from app.models.idempotency_key import IdempotencyKey
from app.models.mock_identity_record import MockIdentityRecord
from app.models.mock_payment import MockPayment
from app.models.rule import Rule
from app.models.scam_message import ScamMessage
from app.models.tenant import Tenant
from app.models.user import User

__all__ = [
    "AuditLog",
    "APIKey",
    "Case",
    "CaseEvent",
    "Citizen",
    "Consent",
    "Decision",
    "Document",
    "EvalRun",
    "HelperCitizenLink",
    "IdempotencyKey",
    "MockIdentityRecord",
    "MockPayment",
    "Rule",
    "ScamMessage",
    "Tenant",
    "User",
]
