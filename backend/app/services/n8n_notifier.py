"""Best-effort notifications to the configured n8n webhook."""

from __future__ import annotations

import os
import json
import logging
from urllib import request as urllib_request

try:
    import requests
except ImportError:  # Requirements install requests; keep optional dev envs bootable.
    requests = None

logger = logging.getLogger(__name__)


def _value(value):
    return getattr(value, "value", value)


def notify_n8n(event: str, payload: dict) -> None:
    url = os.getenv("N8N_WEBHOOK_URL")
    if not url:
        return
    try:
        safe_payload = dict(payload)
        # Do not send to fake @demo.pk seed addresses; None lets n8n use its
        # verified fallback inbox.
        email = safe_payload.get("recipient_email")
        if email and email.endswith("@demo.pk"):
            safe_payload["recipient_email"] = None
        body = {"event": event, **safe_payload}
        if requests is not None:
            response = requests.post(url, json=body, timeout=2)
            response.raise_for_status()
        else:
            req = urllib_request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=2):
                pass
    except Exception as exc:
        # Notifications must never fail the main API operation.
        logger.warning("n8n %s notification failed (%s)", event, type(exc).__name__)


def notify_case_decision(case, decision, *, officer_approval: bool = False) -> None:
    """Build the approved notification payload from committed case records."""
    if not os.getenv("N8N_WEBHOOK_URL"):
        return
    try:
        from app.extensions import db
        from app.models.citizen import Citizen
        from app.models.enums import DecisionOutcome
        from app.models.rule import Rule
        from app.models.user import User

        if officer_approval:
            if _value(decision.outcome) != DecisionOutcome.approved.value:
                return
            event = "case.approved"
            status = "approved"
            officer_note = None
        elif (
            _value(getattr(decision, "actor_type", None)) == "officer"
            and _value(decision.outcome) == DecisionOutcome.rejected.value
        ):
            event = "case.rejected"
            status = "rejected"
            trace = getattr(decision, "trace", None) or {}
            officer_note = trace.get("note") if isinstance(trace, dict) else None
        else:
            route = _value(decision.route)
            if route == "auto_approve":
                event, status = "case.approved", "approved"
            elif route == "human_review":
                event, status = "case.human_review", "in_review"
            else:
                return
            officer_note = None

        citizen = db.session.query(Citizen).filter_by(
            id=str(case.citizen_id), tenant_id=str(case.tenant_id)
        ).first()
        if citizen is None:
            return
        user = None
        if citizen.user_id:
            user = db.session.query(User).filter_by(
                id=str(citizen.user_id), tenant_id=str(case.tenant_id)
            ).first()
        rule = None
        if decision.rule_version_id:
            rule = db.session.query(Rule).filter_by(
                id=str(decision.rule_version_id), tenant_id=str(case.tenant_id)
            ).first()
        rule_amount = rule.definition.get("amount") if rule and rule.definition else None
        reason_en = officer_note or decision.reason_en
        reason_ur = officer_note or decision.reason_ur
        payload = {
            "citizen_name": citizen.full_name,
            "case_id": str(case.id),
            "status": status,
            "amount": rule_amount,
            "reason_en": reason_en,
            "reason_ur": reason_ur,
            "recipient_email": user.email if user else None,
        }
        if officer_note:
            payload["officer_note"] = officer_note
        notify_n8n(event, payload)
    except Exception:
        # Post-commit lookups or notifications cannot roll back a decision or
        # turn a successful API operation into a failure.
        pass


def notify_scam_detected(current_user, result) -> None:
    """Send the scam alert requested for the authenticated AI scam-check API."""
    if getattr(result, "label", None) != "scam":
        return
    notify_n8n("scam.detected", {
        "citizen_name": current_user.full_name,
        "case_id": "SCAM-ALERT",
        "status": "scam",
        "amount": 0,
        "reason_en": result.advice_en,
        "reason_ur": result.advice_ur,
        "recipient_email": current_user.email,
    })
