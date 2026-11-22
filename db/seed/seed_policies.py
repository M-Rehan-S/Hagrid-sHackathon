#!/usr/bin/env python3
"""Idempotent policy chunk seeder for the RAG pipeline.

Usage (from repo root):
    python db/seed/seed_policies.py

Reads all .txt files from db/seed/policies/, splits each into paragraph
chunks, generates 768-dim L2-normalised embeddings, and upserts into
policy_chunks (doc_name, chunk_index, content, embedding) using
ON CONFLICT (doc_name, chunk_index) DO UPDATE.

Safe to re-run: existing rows are updated in-place if content changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup – make sure we can import app.* from the backend directory
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=False)

# ---------------------------------------------------------------------------
# Import embedding module (after dotenv so API keys are loaded)
# ---------------------------------------------------------------------------

from app.ai.embeddings import embed  # noqa: E402

# ---------------------------------------------------------------------------
# Database connection (direct psycopg – no Flask app context needed)
# ---------------------------------------------------------------------------

import psycopg  # psycopg3, already in requirements.txt (psycopg[binary])


def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to .env before running this script."
        )
    # Normalise postgres:// → postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


# ---------------------------------------------------------------------------
# Chunking helper
# ---------------------------------------------------------------------------

def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; drop empty / whitespace-only paragraphs."""
    paragraphs = [p.strip() for p in text.split("\n\n")]
    return [p for p in paragraphs if p]


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

POLICIES_DIR = Path(__file__).resolve().parent / "policies"


def seed_policies() -> int:
    """Seed all policy .txt files into policy_chunks.

    Returns the total number of rows upserted.
    """
    if not POLICIES_DIR.exists():
        raise FileNotFoundError(f"Policies directory not found: {POLICIES_DIR}")

    txt_files = sorted(POLICIES_DIR.glob("*.txt"))
    if not txt_files:
        print(f"[seed_policies] No .txt files found in {POLICIES_DIR}")
        return 0

    db_url = _get_db_url()
    total_upserted = 0

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for txt_path in txt_files:
                doc_name = txt_path.name  # e.g. "01_eligibility_rules.txt"
                content = txt_path.read_text(encoding="utf-8")
                chunks = _split_paragraphs(content)

                print(
                    f"[seed_policies] {doc_name}: {len(chunks)} chunk(s) → embedding…",
                    flush=True,
                )

                for chunk_index, chunk_text in enumerate(chunks):
                    vec = embed(chunk_text)
                    vec_literal = "[" + ",".join(str(v) for v in vec) + "]"

                    cur.execute(
                        """
                        INSERT INTO policy_chunks (doc_name, chunk_index, content, embedding)
                        VALUES (%s, %s, %s, %s::vector)
                        ON CONFLICT (doc_name, chunk_index)
                        DO UPDATE SET content   = EXCLUDED.content,
                                      embedding = EXCLUDED.embedding
                        """,
                        (doc_name, chunk_index, chunk_text, vec_literal),
                    )
                    total_upserted += 1
                    print(
                        f"  chunk {chunk_index}: {len(chunk_text)} chars — OK",
                        flush=True,
                    )

            conn.commit()

    print(
        f"\n[seed_policies] Done. {total_upserted} row(s) upserted across {len(txt_files)} file(s)."
    )
    return total_upserted


# ---------------------------------------------------------------------------
# Verify row count
# ---------------------------------------------------------------------------

def verify_row_count() -> int:
    """Return the current row count in policy_chunks."""
    db_url = _get_db_url()
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM policy_chunks")
            (count,) = cur.fetchone()
    return count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    upserted = seed_policies()
    count = verify_row_count()
    print(f"[seed_policies] Verification: policy_chunks now has {count} row(s).")
    if count == 0:
        print("[seed_policies] WARNING: row count is 0 – check DATABASE_URL and pgvector setup.")
        sys.exit(1)
    sys.exit(0)
