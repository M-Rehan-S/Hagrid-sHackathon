from flask import Flask

from app.errors import register_error_handlers


def _app():
    app = Flask(__name__)
    app.config.update(TESTING=True)
    register_error_handlers(app)
    return app


def test_unknown_route_returns_standard_json_not_found_envelope():
    response = _app().test_client().get("/missing")

    assert response.status_code == 404
    assert response.is_json
    assert response.json == {
        "data": None,
        "error": {
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
            "details": {},
        },
    }


def test_unsupported_method_returns_standard_json_envelope():
    app = _app()

    @app.get("/resource")
    def get_resource():
        return {"ok": True}

    response = app.test_client().post("/resource")

    assert response.status_code == 405
    assert response.is_json
    assert response.json["data"] is None
    assert response.json["error"]["code"] == "VALIDATION_ERROR"


def test_unexpected_exception_returns_sanitized_standard_json_envelope():
    app = _app()

    @app.get("/explode")
    def explode():
        raise RuntimeError("sensitive implementation detail")

    response = app.test_client().get("/explode")

    assert response.status_code == 500
    assert response.is_json
    assert response.json == {
        "data": None,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
            "details": {},
        },
    }
    assert "sensitive implementation detail" not in response.get_data(as_text=True)
