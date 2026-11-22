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
        AuditLog,
        Case,
        CaseEvent,
        Citizen,
        Consent,
        Decision,
        Document,
        APIKey,
        EvalRun,
        HelperCitizenLink,
        IdempotencyKey,
        MockIdentityRecord,
        MockPayment,
        Rule,
        ScamMessage,
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
                APIKey,
                AuditLog,
                EvalRun,
                HelperCitizenLink,
                IdempotencyKey,
                MockIdentityRecord,
                MockPayment,
                Rule,
                ScamMessage,
                Tenant,
                User,
            ):
                # LIMIT 0 checks table/column mapping without returning citizen data.
                db.session.execute(select(model).limit(0))

            # RAG uses a raw pgvector query rather than an ORM model; verify
            # its migrated table and all columns used by the retrieval query.
            db.session.execute(text(
                "SELECT doc_name, chunk_index, content, embedding FROM policy_chunks LIMIT 0"
            ))

            # Exercise the real, read-only service queries against seeded data.
            identity = match_identity({
                "full_name": "Fatima Bibi",
                "father_name": "Muhammad Aslam",
                "cnic": "4210112345671",
                "dob": "1978-04-12",
            })
            assert identity.status == "exact"

            # Ensure seed data required by the frontend demo and Person C's
            # endpoints exists in the same configured database.
            assert db.session.query(MockIdentityRecord).count() >= 200
            assert db.session.query(ScamMessage).count() >= 3
            assert db.session.query(HelperCitizenLink).filter_by(
                helper_user_id="b0000000-0000-0000-0000-000000000002"
            ).count() == 5
            seeded_policy_docs = set(db.session.execute(text(
                "SELECT DISTINCT doc_name FROM policy_chunks"
            )).scalars())
            assert seeded_policy_docs >= {
                "01_eligibility_rules.txt",
                "02_required_documents.txt",
                "03_how_to_appeal.txt",
                "04_spot_scams.txt",
            }

            tenant = db.session.query(Tenant).filter_by(slug="relief").one()
            active_rule = get_active_rule(str(tenant.id), "relief_eligibility")
            assert active_rule is not None
    except SQLAlchemyError:
        pytest.fail(
            "Database integration check failed; connection and query details are suppressed.",
            pytrace=False,
        )
