"""Private Supabase Storage operations for uploaded case documents."""

from __future__ import annotations

from functools import lru_cache
from uuid import uuid4

from flask import current_app
from supabase import create_client


class DocumentStorageError(Exception):
    pass


@lru_cache(maxsize=4)
def _storage_client(url: str, service_key: str):
    return create_client(url, service_key)


def upload_case_document(
    *,
    tenant_id: str,
    case_id: str,
    content: bytes,
    content_type: str,
) -> str:
    url = current_app.config.get("SUPABASE_URL")
    service_key = current_app.config.get("SUPABASE_SERVICE_KEY")
    bucket = current_app.config.get("SUPABASE_BUCKET", "documents")
    if not url or not service_key:
        raise DocumentStorageError("Private document storage is not configured")

    path = f"{tenant_id}/{case_id}/{uuid4().hex}"
    try:
        _storage_client(url, service_key).storage.from_(bucket).upload(
            path,
            content,
            {"content-type": content_type or "application/octet-stream", "upsert": "false"},
        )
    except Exception as exc:
        raise DocumentStorageError("Document upload failed") from exc
    return path


def create_document_download_url(storage_path: str, *, expires_in: int = 300) -> str:
    """Create a short-lived signed URL for a citizen's own exported document."""
    url = current_app.config.get("SUPABASE_URL")
    service_key = current_app.config.get("SUPABASE_SERVICE_KEY")
    bucket = current_app.config.get("SUPABASE_BUCKET", "documents")
    if not url or not service_key:
        raise DocumentStorageError("Private document storage is not configured")
    try:
        response = _storage_client(url, service_key).storage.from_(bucket).create_signed_url(
            storage_path, expires_in
        )
        signed_url = response.get("signedURL") or response.get("signedUrl")
        if not signed_url:
            raise DocumentStorageError("Storage did not return a signed URL")
        return signed_url
    except DocumentStorageError:
        raise
    except Exception as exc:
        raise DocumentStorageError("Document URL generation failed") from exc
