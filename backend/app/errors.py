"""Application-wide JSON error responses for the frontend API client."""

from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException


_HTTP_ERROR_CODES = {
    400: ("VALIDATION_ERROR", "Request is invalid."),
    405: ("VALIDATION_ERROR", "This HTTP method is not supported for the resource."),
    413: ("VALIDATION_ERROR", "The request payload is too large."),
    415: ("VALIDATION_ERROR", "The request content type is not supported."),
    401: ("UNAUTHENTICATED", "Authentication is required."),
    403: ("FORBIDDEN_ROLE", "This action is not allowed."),
    404: ("NOT_FOUND", "The requested resource was not found."),
    409: ("CONFLICT", "The request conflicts with the current resource state."),
    422: ("LOW_CONFIDENCE", "The request could not be completed safely."),
    429: ("RATE_LIMITED", "Request limit reached. Try again shortly."),
    502: ("AI_UNAVAILABLE", "A required service is temporarily unavailable."),
}


def _error_response(code: str, message: str, status_code: int):
    return jsonify({
        "data": None,
        "error": {"code": code, "message": message, "details": {}},
    }), status_code


def register_error_handlers(app: Flask) -> None:
    """Keep framework and unexpected errors inside the documented JSON envelope."""

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        status_code = error.code or 500
        code, message = _HTTP_ERROR_CODES.get(
            status_code, ("INTERNAL_ERROR", "The request could not be completed.")
        )
        return _error_response(code, message, status_code)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(_error: Exception):
        return _error_response(
            "INTERNAL_ERROR", "An unexpected error occurred.", 500
        )
