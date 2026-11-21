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
