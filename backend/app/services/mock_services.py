"""Backends for the deliberately simulated external services."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models.case import Case
from app.models.enums import CaseStatus, UserRole
from app.models.mock_payment import MockPayment
from app.models.rule import Rule
from app.models.user import User
from app.services.audit import audit
from app.services.case_service import CaseError, _require_case_access
from app.services.identity_match import match_identity


class MockServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def lookup_identity(actor: User, form: dict):
    result = match_identity(form)
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action="data.read_pii",
        entity_type="mock_identity_record",
        entity_id=result.matched_record_id,
        payload={"query_fields": sorted(key for key, value in form.items() if value is not None)},
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()
    return result


def create_mock_payment(actor: User, *, case_id: str, amount: Decimal) -> tuple[MockPayment, bool]:
    role = str(getattr(actor.role, "value", actor.role))
    if role not in (UserRole.admin.value, UserRole.officer.value):
        raise MockServiceError("FORBIDDEN_ROLE", "Only admins and officers can create mock payments.", 403)

    case_item = db.session.query(Case).filter_by(
        id=case_id, tenant_id=actor.tenant_id
    ).first()
    if case_item is None:
        raise MockServiceError("NOT_FOUND", "Case was not found.", 404)
    if str(getattr(case_item.status, "value", case_item.status)) != CaseStatus.approved.value:
        raise MockServiceError("CONFLICT", "Mock payments require an approved case.", 409)

    if role == UserRole.officer.value:
        try:
            _require_case_access(actor, case_item)
        except CaseError as exc:
            raise MockServiceError(exc.code, exc.message, exc.status_code) from exc

    rule = db.session.query(Rule).filter_by(
        id=case_item.rule_version_id, tenant_id=case_item.tenant_id
    ).first()
    if rule is None or "amount" not in rule.definition:
        raise MockServiceError("CONFLICT", "The case rule has no mock payment amount.", 409)
    expected_amount = Decimal(str(rule.definition["amount"])).quantize(Decimal("0.01"))
    if amount != expected_amount:
        raise MockServiceError("CONFLICT", "Amount must match the case's rule version.", 409)

    existing = db.session.query(MockPayment).filter_by(case_id=case_item.id).first()
    if existing is not None:
        return existing, False

    payment = MockPayment(
        case_id=str(case_item.id),
        amount=expected_amount,
        reference=f"MOCK-{uuid4().hex.upper()}",
    )
    db.session.add(payment)
    db.session.flush()
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action="mock.payment.create",
        entity_type="mock_payment",
        entity_id=str(payment.id) if payment.id else None,
        payload={"case_id": str(case_item.id), "amount": str(expected_amount)},
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()
    return payment, True


def get_mock_payment(actor: User, payment_id: str) -> MockPayment:
    payment = (
        db.session.query(MockPayment)
        .join(Case, MockPayment.case_id == Case.id)
        .filter(MockPayment.id == payment_id, Case.tenant_id == actor.tenant_id)
        .first()
    )
    if payment is None:
        raise MockServiceError("NOT_FOUND", "Payment was not found.", 404)
    case_item = db.session.query(Case).filter_by(
        id=payment.case_id, tenant_id=actor.tenant_id
    ).first()
    role = str(getattr(actor.role, "value", actor.role))
    if role in (UserRole.citizen.value, UserRole.helper.value, UserRole.officer.value):
        try:
            _require_case_access(actor, case_item)
        except CaseError as exc:
            raise MockServiceError(exc.code, exc.message, exc.status_code) from exc
    else:
        raise MockServiceError("FORBIDDEN_ROLE", "Your role cannot view payment status.", 403)
    return payment


def submit_mock_complaint(actor: User, *, case_id: str, complaint_text: str) -> str:
    role = str(getattr(actor.role, "value", actor.role))
    if role not in (UserRole.citizen.value, UserRole.helper.value):
        raise MockServiceError("FORBIDDEN_ROLE", "Only citizens and helpers can submit complaints.", 403)
    case_item = db.session.query(Case).filter_by(
        id=case_id, tenant_id=actor.tenant_id
    ).first()
    if case_item is None:
        raise MockServiceError("NOT_FOUND", "Case was not found.", 404)
    try:
        _require_case_access(actor, case_item)
    except CaseError as exc:
        raise MockServiceError(exc.code, exc.message, exc.status_code) from exc
    # This endpoint simulates an external complaints service; it deliberately
    # does not persist the complaint text or a local complaint row.
    return f"CMP-{uuid4().hex[:12].upper()}"
