"""Embedding utilities for the RAG pipeline.

Supports three providers in priority order:
  1. Gemini  – if GEMINI_API_KEY is set (REST, no SDK dependency needed)
  2. OpenAI  – if OPENAI_API_KEY is set (truncated / projected to 768 dims)
  3. Sparse fallback – deterministic TF-IDF / character+word n-gram hashing
                       (scikit-learn + numpy, already in the repo stack)

All returned vectors are 768-dimensional and L2-normalised.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import List

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "768"))
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "").lower()

# Cosine-similarity thresholds for the handoff decision
DENSE_THRESHOLD: float = 0.45   # used when a real embedding API answered
SPARSE_THRESHOLD: float = 0.20  # used for the TF-IDF fallback


# ---------------------------------------------------------------------------
# L2 normalisation helper
# ---------------------------------------------------------------------------

def _l2_normalize(vec: List[float]) -> List[float]:
    arr = np.array(vec, dtype=np.float64)
    norm = np.linalg.norm(arr)
    if norm < 1e-10:
        # zero vector – return as-is; similarity queries will score 0
        return arr.tolist()
    return (arr / norm).tolist()


# ---------------------------------------------------------------------------
# Provider 1 – Gemini (REST, no SDK)
# ---------------------------------------------------------------------------

def _embed_gemini(text: str) -> List[float]:
    import requests  # already in requirements.txt

    api_key = os.getenv("GEMINI_API_KEY", "")
    model = EMBEDDING_MODEL or "gemini-embedding-001"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:embedContent?key={api_key}"
    )
    body = {
        "model": f"models/{model}",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": EMBEDDING_DIM,
    }
    resp = requests.post(url, json=body, timeout=15)
    resp.raise_for_status()
    values = resp.json()["embedding"]["values"]
    return _l2_normalize(values)


# ---------------------------------------------------------------------------
# Provider 2 – OpenAI
# ---------------------------------------------------------------------------

def _embed_openai(text: str) -> List[float]:
    import requests

    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    url = "https://api.openai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"input": text, "model": model}
    resp = requests.post(url, json=body, headers=headers, timeout=15)
    resp.raise_for_status()
    raw = resp.json()["data"][0]["embedding"]
    # Truncate / pad to EMBEDDING_DIM
    if len(raw) > EMBEDDING_DIM:
        raw = raw[:EMBEDDING_DIM]
    elif len(raw) < EMBEDDING_DIM:
        raw = raw + [0.0] * (EMBEDDING_DIM - len(raw))
    return _l2_normalize(raw)


# ---------------------------------------------------------------------------
# Provider 3 – Sparse / TF-IDF fallback (zero external dependencies)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _sparse_vectorizer():
    """Return a fitted HashingVectorizer (768-dim, character + word n-grams).

    The vectorizer is deterministic (fixed hash function, no random state) so
    the same text always produces the same vector across process restarts.
    We fit on a tiny corpus just to warm the tokeniser; the hashing trick
    makes the vocabulary implicit.
    """
    from sklearn.pipeline import Pipeline
    from sklearn.feature_extraction.text import HashingVectorizer
    from sklearn.preprocessing import Normalizer

    # Character n-grams (2-4) + word unigrams/bigrams → 768 features
    # alternate_sign=False keeps all values ≥ 0 (cosine similarity works fine)
    vec = Pipeline([
        (
            "hash",
            HashingVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 4),
                n_features=EMBEDDING_DIM,
                alternate_sign=False,
                norm="l2",
            ),
        ),
    ])
    return vec


def _embed_sparse(text: str) -> List[float]:
    """Deterministic 768-dim L2-normalised TF-IDF / n-gram hash vector."""
    vec = _sparse_vectorizer()
    # HashingVectorizer returns a sparse matrix; convert to dense 1-D array
    result = vec.transform([text])
    arr = np.asarray(result.todense()).flatten().astype(np.float64)
    # Already L2-normalised by the pipeline (norm="l2"), but re-normalise for safety
    return _l2_normalize(arr.tolist())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

#: Which provider is actually active.  Set after first successful call so
#: callers (rag.py) can read the correct threshold.
_active_provider: str = "sparse"


def embed(text: str) -> List[float]:
    """Return a 768-dim L2-normalised embedding for *text*.

    Provider priority: Gemini → OpenAI → sparse fallback.
    Sets module-level ``_active_provider`` so the threshold can be read by rag.py.
    """
    global _active_provider

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

    if gemini_key:
        try:
            vec = _embed_gemini(text)
            _active_provider = "gemini"
            return vec
        except Exception:
            pass  # fall through to next provider

    if openai_key:
        try:
            vec = _embed_openai(text)
            _active_provider = "openai"
            return vec
        except Exception:
            pass

    _active_provider = "sparse"
    return _embed_sparse(text)


def get_similarity_threshold() -> float:
    """Return the appropriate handoff threshold for the last-used provider."""
    if _active_provider in ("gemini", "openai"):
        return DENSE_THRESHOLD
    return SPARSE_THRESHOLD
