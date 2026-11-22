"""Environment-backed Flask configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPOSITORY_ROOT / ".env", override=False)
BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_backend_n8n_url = dotenv_values(BACKEND_ENV).get("N8N_WEBHOOK_URL")
if not os.getenv("N8N_WEBHOOK_URL") and _backend_n8n_url:
    os.environ["N8N_WEBHOOK_URL"] = _backend_n8n_url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "documents")
    CORS_ORIGINS = list(dict.fromkeys(
        origin.strip()
        for origin in [
            *os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
            "https://hagrid-s-hackathon.vercel.app",
        ]
        if origin.strip()
    ))
    RATE_LIMIT_PUBLIC_COUNT = int(os.getenv("RATE_LIMIT_PUBLIC_COUNT", "60"))
    RATE_LIMIT_PUBLIC_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_PUBLIC_WINDOW_SECONDS", "60"))
    RATE_LIMIT_AI_COUNT = int(os.getenv("RATE_LIMIT_AI_COUNT", "30"))
    RATE_LIMIT_AI_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_AI_WINDOW_SECONDS", "60"))
    RATE_LIMIT_AUTH_SESSION_COUNT = int(os.getenv("RATE_LIMIT_AUTH_SESSION_COUNT", "10"))
    RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "120 per minute")
    RATELIMIT_DEFAULT = []
    RATELIMIT_APPLICATION = RATE_LIMIT_DEFAULT
    RATELIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
