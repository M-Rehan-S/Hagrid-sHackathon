"""Environment-backed Flask configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPOSITORY_ROOT / ".env", override=False)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "documents")
    RATE_LIMIT_PUBLIC_COUNT = int(os.getenv("RATE_LIMIT_PUBLIC_COUNT", "60"))
    RATE_LIMIT_PUBLIC_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_PUBLIC_WINDOW_SECONDS", "60"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
