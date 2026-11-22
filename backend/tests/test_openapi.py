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
    assert "/api/v1/cases/{case_id}/submit" in paths
    assert "/api/v1/rules/{rule_id}/activate" in paths
    assert "/api/v1/api-keys/{key_id}/revoke" in paths
    assert "/api/v1/public/scam-check" in paths
