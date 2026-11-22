# Relief Claim Copilot

> ⚠️ **PROTOTYPE ONLY.** Built for Coder's Cup '26 AI Hackathon (*The Last Mile: AI on Public Rails*).  
> **Not an official service.** All identity, payment, and data services are mocked. No real personal data anywhere.

---

## 1. Project Overview

**Relief Claim Copilot** assists vulnerable citizens—such as a widow assisted by a community helper—to claim relief benefits even when facing low literacy, poor mobile connectivity, and discrepant name spellings across civic records.

The platform provides an end-to-end multi-tenant system featuring:
- **Decides, Explains, and Protects:** Deterministic, rule-driven decisions with clear Urdu/English explanations.
- **Fail-Safe & Human-in-the-Loop:** Whenever confidence is low or an anomaly is detected, the AI routes cases to human review instead of rejecting or auto-approving blindly.
- **Auditable & Sovereign:** Cryptographic hash-chained audit logs, fine-grained consent management with instant revocation, and versioned rules.
- **Scam Detection:** A backend ML checker that classifies alleged relief SMS messages and gives cautious advice.
- **Low-Connectivity & Low-Literacy Support:** Voice-first interaction (Urdu/English), icon-driven UI, and offline-ready PWA caching with idempotent sync.

---

## 2. Real vs. Simulated Components

In accordance with hackathon guidelines, all public rails and sensitive registries are simulated safely while core business, AI, and security logic remain fully implemented.

| Component | Status | Description / Implementation Details |
|---|---|---|
| **Identity Registry (NADRA-like)** | 🟡 **Simulated** | Mock database table (`mock_identity_records`) seeded with test personas and deliberate edge cases (name variations, typos, missing CNIC, deceased records). No real citizen PII is used. |
| **Identity Matching Engine** | 🟢 **Real** | Implemented using token sort ratio fuzzy matching (`rapidfuzz`), Double Metaphone (`doublemetaphone`), and Pakistani name variant normalization dictionaries. |
| **Disbursement / Payment Gateway** | 🟡 **Simulated** | Mock payments engine (`mock_payments`) simulating queuing, reference generation, and processing status for relief disbursements. |
| **Government Portal / Complaints** | 🟡 **Simulated** | Mock endpoints generating ticket references without connecting to actual state infrastructure. |
| **Decision & Rules Engine** | 🟢 **Real** | Dynamic versioned rules evaluated against structured form data and policy constraints. Reads thresholds directly from active database rule records. |
| **Digital Twin Simulator** | 🟢 **Real** | Replays past historical cases in-memory against candidate rule versions to assess impact and error-cost trade-offs before rule activation. |
| **Scam Classification** | 🟢 **Real** | Classical ML (scikit-learn TF-IDF + Logistic Regression) trained on bilingual dataset, combined with heuristic checks (e.g. non-`.gov.pk` domains, OTP/PIN probes). |
| **Audit Logging & Verification** | 🟢 **Real** | Append-only, SHA-256 hash-chained log (`audit_logs`) with PostgreSQL trigger blocking updates/deletes and an auditor verification endpoint. |
| **Consent & Access Control** | 🟢 **Real** | Server-side role-based access control (RBAC) and scoped consent check decorator (`@require_consent`) with immediate withdrawal enforcement. |
| **Document Processing & RAG** | 🟢 **Real** | Policy document chunking, embeddings (`pgvector`), and retrieval-augmented QA for citizen inquiries. |
| **Offline Sync & Idempotency** | 🟢 **Real** | IndexedDB offline operation queue synchronized via idempotent batch submissions (`POST /sync/batch`). |

---

## 3. Repository Structure

```
/
├── PROPOSAL.md                  # Project proposal & single source of truth contract
├── README.md                    # Project overview, prototype disclaimer, real vs simulated
├── .env.example                 # Environment variable templates
├── db/
│   ├── migrations/              # Numbered SQL migrations (001_init.sql, ...)
│   └── seed/                    # Database seed scripts and mock datasets
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Application factory (create_app)
│   │   ├── config.py            # Environment configuration
│   │   ├── extensions.py        # Database, rate limiter, API doc specs
│   │   ├── auth/                # JWT utilities, @require_role, @require_consent
│   │   ├── api/                 # Flask Blueprints (auth, cases, rules, audit, ai, etc.)
│   │   ├── services/            # Business logic (decision engine, identity match, audit, etc.)
│   │   ├── ai/                  # LLM client, form extractor, scam classifier, RAG
│   │   ├── models/              # SQLAlchemy ORM models matching DB schema
│   │   └── schemas/             # Pydantic validation & serialization models
│   └── tests/                   # Pytest test suite (RBAC, consent, rules, decisions)
└── frontend/
    └── src/
        ├── pages/               # Views for citizen, helper, officer, admin, auditor
        ├── api/                 # Strongly-typed API client
        ├── i18n/                # Localization (en.json, ur.json)
        └── offline/             # IndexedDB storage and background sync
```

---

## 4. Tech Stack

- **Backend:** Python 3.11, Flask (Application Factory & Blueprints)
- **API Documentation & Validation:** SpecTree, Pydantic v2
- **Database:** Supabase Postgres + `pgvector`
- **Security & RBAC:** Supabase Auth issues sessions; Flask verifies access JWTs (PyJWT) and enforces database roles and consent
- **AI / LLMs:** Groq (primary) / Gemini API (fallback), pgvector RAG, scikit-learn
- **Frontend:** React, Vite, Tailwind CSS, PWA (`vite-plugin-pwa`), Web Speech API

## 5. Backend setup for frontend development

The backend exposes the API contract in Swagger at `/apidocs` and OpenAPI JSON at `/apidocs/openapi.json`.

1. Copy the root `.env.example` to `.env` and configure `DATABASE_URL`, Supabase JWT verification, and any optional AI provider keys.
2. From the repository root, apply the migrations in order:

   ```bash
   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f db/migrations/001_init.sql
   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f db/migrations/002_extras.sql
   ```

3. Seed the demo profiles, cases, and 200 mock identity records with `backend/venv/bin/python db/seed/seed.py`. The script also seeds policy chunks; use `--skip-policies` to omit that step.
4. Install backend dependencies and start Flask:

   ```bash
   cd backend
   python -m venv venv
   venv/bin/pip install -r requirements.txt
   venv/bin/flask --app 'app:create_app' run --debug --port 5000
   ```

The frontend uses Supabase Auth for signup, passkey/password sign-in, and session refresh. It sends the Supabase access token to Flask as a bearer token; application data must go through the Flask API. Check `PROPOSAL.md` for the authoritative routes, roles, response envelopes, and screen requirements.

To add a classifier evaluation snapshot to the evaluation dashboard, run `backend/venv/bin/python backend/app/ai/evaluate_scam_classifier.py` from the repository root after configuring the database. It evaluates the fixed held-out split and stores only aggregate metrics in `eval_runs`.
