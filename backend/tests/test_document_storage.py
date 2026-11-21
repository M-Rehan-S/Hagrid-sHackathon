from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.services import document_storage
from app.services.document_storage import DocumentStorageError


def test_signed_document_url_uses_private_bucket_and_five_minute_expiry(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SUPABASE_URL="https://storage.example.test",
        SUPABASE_SERVICE_KEY="test-service-key",
        SUPABASE_BUCKET="private-documents",
    )
    storage = MagicMock()
    storage.from_.return_value.create_signed_url.return_value = {
        "signedURL": "https://storage.example.test/signed/private/path"
    }
    client = SimpleNamespace(storage=storage)
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(document_storage, "_storage_client", factory)

    with flask_app.app_context():
        signed_url = document_storage.create_document_download_url("tenant/case/file")

    assert signed_url.endswith("/signed/private/path")
    factory.assert_called_once_with("https://storage.example.test", "test-service-key")
    storage.from_.assert_called_once_with("private-documents")
    storage.from_.return_value.create_signed_url.assert_called_once_with("tenant/case/file", 300)


def test_signed_document_url_fails_closed_when_storage_not_configured():
    flask_app = Flask(__name__)
    flask_app.config.update(SUPABASE_URL=None, SUPABASE_SERVICE_KEY=None)

    with flask_app.app_context(), pytest.raises(DocumentStorageError):
        document_storage.create_document_download_url("tenant/case/file")
