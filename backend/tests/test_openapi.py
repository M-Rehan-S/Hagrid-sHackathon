from app import create_app


def test_swagger_ui_and_openapi_document_are_available():
    app = create_app({"DATABASE_URL": "sqlite://", "TESTING": True})
    client = app.test_client()

    landing = client.get("/apidocs")
    swagger = client.get("/apidocs/swagger/")
    document = client.get("/apidocs/openapi.json")

    assert landing.status_code == 302
    assert landing.headers["Location"].endswith("/apidocs/swagger/")
    assert swagger.status_code == 200
    assert "swagger-ui" in swagger.get_data(as_text=True).lower()
    assert document.status_code == 200

    paths = document.get_json()["paths"]
    expected = {
        "/api/v1/auth/session": {"post"},
        "/api/v1/auth/me": {"get"},
        "/api/v1/citizens": {"post"},
        "/api/v1/citizens/{citizen_id}": {"get", "patch"},
        "/api/v1/citizens/{citizen_id}/export": {"get"},
        "/api/v1/helper/citizens": {"get"},
        "/api/v1/helper/citizens/{citizen_id}/link": {"post"},
        "/api/v1/cases": {"get", "post"},
        "/api/v1/cases/{case_id}": {"get"},
        "/api/v1/cases/{case_id}/form": {"patch"},
        "/api/v1/cases/{case_id}/submit": {"post"},
        "/api/v1/cases/{case_id}/documents": {"post"},
        "/api/v1/cases/{case_id}/assign": {"post"},
        "/api/v1/cases/{case_id}/escalate": {"post"},
        "/api/v1/cases/{case_id}/decision": {"post"},
        "/api/v1/cases/{case_id}/close": {"post"},
        "/api/v1/ai/transcribe": {"post"},
        "/api/v1/ai/extract-form": {"post"},
        "/api/v1/ai/scam-check": {"post"},
        "/api/v1/ai/ask": {"post"},
        "/api/v1/rules": {"get", "post"},
        "/api/v1/rules/{rule_id}/activate": {"post"},
        "/api/v1/twin/simulate": {"post"},
        "/api/v1/consents": {"get", "post"},
        "/api/v1/consents/{consent_id}/withdraw": {"post"},
        "/api/v1/audit-logs": {"get"},
        "/api/v1/audit-logs/verify": {"get"},
        "/api/v1/audit-logs/mine": {"get"},
        "/api/v1/mock/identity/lookup": {"post"},
        "/api/v1/mock/payments": {"post"},
        "/api/v1/mock/payments/{payment_id}": {"get"},
        "/api/v1/mock/complaints": {"post"},
        "/api/v1/api-keys": {"get", "post"},
        "/api/v1/api-keys/{key_id}/revoke": {"post"},
        "/api/v1/public/scam-check": {"post"},
        "/api/v1/public/cases/{case_id}/status": {"get"},
        "/api/v1/sync/batch": {"post"},
        "/api/v1/eval/summary": {"get"},
        "/health": {"get"},
    }
    assert {path: set(methods) for path, methods in paths.items()} == expected
