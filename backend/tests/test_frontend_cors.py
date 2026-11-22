from app import create_app


def test_frontend_origin_can_preflight_authorized_api_requests():
    app = create_app({
        "DATABASE_URL": "sqlite://",
        "TESTING": True,
        "CORS_ORIGINS": ["http://localhost:5173"],
    })

    response = app.test_client().options(
        "/api/v1/auth/session",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()


def test_unconfigured_frontend_origin_does_not_receive_cors_access():
    app = create_app({
        "DATABASE_URL": "sqlite://",
        "TESTING": True,
        "CORS_ORIGINS": ["http://localhost:5173"],
    })

    response = app.test_client().options(
        "/api/v1/auth/session",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.headers.get("Access-Control-Allow-Origin") is None
