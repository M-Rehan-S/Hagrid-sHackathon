"""HTTP adapters for simulated identity, payment, and complaint services."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_auth, require_role
from app.models.mock_payment import MockPayment
from app.schemas.mock_services import (
    IdentityLookupRequest,
    MockComplaintRequest,
    MockPaymentRequest,
)
from app.services.mock_services import (
    MockServiceError,
    create_mock_payment,
    get_mock_payment,
    lookup_identity,
    submit_mock_complaint,
)


mock_services_bp = Blueprint("mock_services", __name__)


@mock_services_bp.errorhandler(MockServiceError)
def handle_mock_service_error(error: MockServiceError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


def _parse(model):
    try:
        return model.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise MockServiceError("VALIDATION_ERROR", "Request body is invalid.", 400) from exc


def _payment_data(payment: MockPayment) -> dict:
    return {
        "id": str(payment.id),
        "case_id": str(payment.case_id),
        "amount": float(payment.amount),
        "status": payment.status,
        "reference": payment.reference,
    }


@mock_services_bp.post("/identity/lookup")
@require_role("citizen", "helper")
def post_identity_lookup():
    body = _parse(IdentityLookupRequest)
    match = lookup_identity(g.current_user, body.model_dump(mode="json", exclude_none=True))
    return jsonify({"data": match.model_dump(), "error": None})


@mock_services_bp.post("/payments")
@require_role("admin", "officer")
def post_mock_payment():
    body = _parse(MockPaymentRequest)
    payment, created = create_mock_payment(
        g.current_user,
        case_id=str(body.case_id),
        amount=Decimal(body.amount),
    )
    return jsonify({"data": _payment_data(payment), "error": None}), 201 if created else 200


@mock_services_bp.get("/payments/<uuid:payment_id>")
@require_auth
def get_mock_payment_status(payment_id):
    payment = get_mock_payment(g.current_user, str(payment_id))
    return jsonify({"data": _payment_data(payment), "error": None})


@mock_services_bp.post("/complaints")
@require_role("citizen", "helper")
def post_mock_complaint():
    body = _parse(MockComplaintRequest)
    reference = submit_mock_complaint(
        g.current_user, case_id=str(body.case_id), complaint_text=body.text
    )
    return jsonify({"data": {"complaint_reference": reference}, "error": None}), 201
