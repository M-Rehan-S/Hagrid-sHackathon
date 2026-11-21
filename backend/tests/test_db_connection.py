"""Opt-in read-only integration check for the configured Supabase Postgres DB.

From ``backend/``, run ``RUN_DB_INTEGRATION=1 venv/bin/python -m pytest
tests/test_db_connection.py -q``. This only connects and selects from existing
tables.
"""

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_INTEGRATION") != "1",
    reason="set RUN_DB_INTEGRATION=1 to run against the configured database",
)


def test_configured_database_and_service_tables_are_reachable():
    from app import create_app
    from app.extensions import db
    from app.models import (
        Case,
        CaseEvent,
        Citizen,
        Consent,
        Decision,
        Document,
        EvalRun,
        HelperCitizenLink,
        IdempotencyKey,
        MockIdentityRecord,
        MockPayment,
        Rule,
        Tenant,
        User,
    )
    from app.services.identity_match import match_identity
    from app.services.rule_service import get_active_rule

    app = create_app()
    try:
        with app.app_context():
            assert db.session.execute(text("SELECT 1")).scalar_one() == 1
            for model in (
                Case,
                CaseEvent,
                Citizen,
                Consent,
                Decision,
                Document,
                EvalRun,
                HelperCitizenLink,
                IdempotencyKey,
                MockIdentityRecord,
                MockPayment,
                Rule,
                Tenant,
                User,
            ):
                # LIMIT 0 checks table/column mapping without returning citizen data.
                db.session.execute(select(model).limit(0))

            # Exercise the real, read-only service queries against seeded data.
            identity = match_identity({
                "full_name": "Fatima Bibi",
                "father_name": "Muhammad Aslam",
                "cnic": "4210112345671",
                "dob": "1978-04-12",
            })
            assert identity.status == "exact"

            tenant = db.session.query(Tenant).filter_by(slug="relief").one()
            active_rule = get_active_rule(str(tenant.id), "relief_eligibility")
            assert active_rule is not None
    except SQLAlchemyError:
        pytest.fail(
            "Database integration check failed; connection and query details are suppressed.",
            pytrace=False,
        )
