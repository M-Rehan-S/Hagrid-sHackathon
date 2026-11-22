"""RAG policy Q&A service (PROPOSAL.md §7.5, §8.8).

Public API::

    result = answer_policy_question(question="...", lang="ur")
    # Returns:
    # {
    #   "answer": "<text>" | None,
    #   "sources": [{"doc_name": "...", "chunk_index": 0, "snippet": "..."}],
    #   "confidence": 0.87,
    #   "handoff": False
    # }

Honest Handoff Rule (§7.5 / §8.8):
  - Empty table OR top similarity < threshold  → handoff=True, answer=None, never calls LLM.
  - LLM returns NO_ANSWER sentinel / fails / times out  → handoff=True, answer=None, never raises 500.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.extensions import db


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a helpful policy assistant for a government relief program in Pakistan.
You answer citizens' questions using ONLY the retrieved policy excerpts provided below.

Rules you MUST follow:
1. Answer ONLY using facts explicitly stated in the retrieved policy chunks. Do not invent, infer, or add information not present in those chunks.
2. If the retrieved chunks do not actually answer the user's specific question, respond with the single token: NO_ANSWER
3. If lang is "ur", write your entire answer in clear, natural Urdu script (اردو). Do not mix English words unless they are proper nouns or technical terms that have no Urdu equivalent.
4. If lang is "en", write your entire answer in clear, simple English.
5. Be concise but complete. Use numbered lists when listing multiple items.
6. Never mention the word "chunks" or "retrieved documents" in your answer.
"""

_NO_ANSWER_SENTINEL = "NO_ANSWER"


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def answer_policy_question(question: str, lang: str = "ur") -> dict[str, Any]:
    """Answer a policy question using RAG over ``policy_chunks``.

    Returns the standard result dict; never raises – errors become handoffs.
    """
    from app.ai.embeddings import embed, get_similarity_threshold  # local import to avoid circular deps at module load

    # 1. Check whether the table has any rows at all
    try:
        row_count = db.session.execute(
            text("SELECT COUNT(*) FROM policy_chunks")
        ).scalar_one()
    except Exception:
        return _handoff(0.0)

    if row_count == 0:
        return _handoff(0.0)

    # 2. Embed the question
    try:
        q_vec = embed(question)
    except Exception:
        return _handoff(0.0)

    threshold = get_similarity_threshold()

    # 3. Retrieve top-3 chunks by cosine similarity
    try:
        vec_literal = "[" + ",".join(str(v) for v in q_vec) + "]"
        rows = db.session.execute(
            text(
                """
                SELECT doc_name,
                       chunk_index,
                       content,
                       1 - (embedding <=> CAST(:vec AS vector)) AS score
                FROM policy_chunks
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT 3
                """
            ),
            {"vec": vec_literal},
        ).fetchall()
    except Exception:
        return _handoff(0.0)

    if not rows:
        return _handoff(0.0)

    top_score: float = float(rows[0][3])

    # 4. Honest handoff: not enough similarity
    if top_score < threshold:
        return _handoff(round(max(top_score, 0.0), 3))

    # 5. Build context for the LLM
    context_parts = []
    for i, row in enumerate(rows, start=1):
        context_parts.append(f"[Chunk {i} – {row[0]}, index {row[1]}]\n{row[2]}")
    context = "\n\n---\n\n".join(context_parts)

    user_prompt = (
        f"Retrieved policy excerpts:\n\n{context}\n\n"
        f"---\n\nUser question (lang={lang}): {question}\n\n"
        f"Answer in {'Urdu (اردو script)' if lang == 'ur' else 'English'}."
    )

    # 6. Call LLM
    from app.ai.llm_client import chat

    try:
        answer_text = chat(_SYSTEM_PROMPT, user_prompt)
    except Exception:
        answer_text = None

    # 7. Handle NO_ANSWER / failure
    if not answer_text or answer_text.strip() == _NO_ANSWER_SENTINEL:
        return _handoff(0.0)

    # 8. Build sources list
    sources = [
        {
            "doc_name": row[0],
            "chunk_index": int(row[1]),
            "snippet": row[2][:200],
        }
        for row in rows
    ]

    return {
        "answer": answer_text.strip(),
        "sources": sources,
        "confidence": round(top_score, 3),
        "handoff": False,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handoff(confidence: float) -> dict[str, Any]:
    return {
        "answer": None,
        "sources": [],
        "confidence": round(confidence, 3),
        "handoff": True,
    }
