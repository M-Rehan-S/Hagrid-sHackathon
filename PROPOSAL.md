# Relief Claim Copilot: Project Proposal and Integration Contract

> **PROTOTYPE ONLY.** Built for Coder's Cup '26 AI Hackathon ("The Last Mile: AI on Public Rails"). Not an official service. All identity, payment, and data services are mocked. No real personal data anywhere.

---

## 0. How to use this file (read first)

This file is the **single source of truth** for what we build. Paste it (or the relevant sections) into your AI coding assistant at the start of every session and say:

> "Follow PROPOSAL.md exactly. Do not rename tables, columns, endpoints, enums, or JSON fields. If something is missing or ambiguous, ask me instead of inventing it."

**Integration rules (these prevent backend/schema/frontend conflicts):**

1. **Names are frozen.** Table names, column names, enum values, endpoint paths, and JSON keys in this file are the contract. Do not rename them or add "better" alternatives.
2. **Changes go through this file.** If you need a new column, endpoint, or field, edit this file first, post the diff in the team chat, then code it. Never change the schema silently.
3. **Conventions are fixed:** JSON keys and DB columns are `snake_case`; IDs are UUIDs (strings); timestamps are ISO 8601 UTC; enum values are lowercase strings exactly as listed.
4. **One response envelope** for every endpoint (Section 7.1).
5. **Every state-changing action writes to the audit log** through the single function `audit.log(...)` (Section 8.6). Never insert into `audit_logs` directly.
6. **Every decision stores** `rule_version_id`, `model_version`, `confidence`, and a `trace` (Section 9).
7. **The AI never fails silently.** If an AI/LLM call fails, times out, or returns invalid JSON, the case goes to `human_review`. It never auto-approves on failure.
8. **Server-side enforcement only.** The frontend hides buttons for UX, but the backend checks role and consent on every request.

---

## 0.1 Change log: Supabase Auth instead of custom JWT <!-- CHANGED: SB-AUTH -->

Every place changed for this decision is tagged `<!-- CHANGED: SB-AUTH -->`. Summary:

|Section|Change|
|---|---|
|2 Tech stack|Auth row; Frontend row (supabase-js for auth only)|
|3 Repo|`auth/` comment|
|4 Roles|Note: role is read from `users.role`, never from the JWT|
|5 Schema|`users.password_hash` removed; `users.id` references `auth.users(id)`; new trigger `handle_new_user`; grants revoked from `anon`/`authenticated`|
|7.2 Auth|`POST /auth/register` and `POST /auth/login` removed; `POST /auth/session` added; JWT verification rules rewritten|
|8.6 Audit|`auth.login_failed` removed (Supabase keeps failed logins in its own Auth logs)|
|8.8 Rate limit|`/auth/login` limit becomes `/auth/session`|
|10 Frontend|"never calls Supabase" now has one exception: Supabase Auth|
|11 Seed|Demo users are created in `auth.users`; profiles come from the trigger|
|12 Env|`JWT_SECRET`, `JWT_EXPIRES_MIN` removed; `SUPABASE_ANON_KEY`, `SUPABASE_JWKS_URL`, `SUPABASE_JWT_SECRET` added|
|17 Do not|Secrets rule clarified (anon key is public by design)|

---

## 1. One-paragraph pitch

> We help a **widow (assisted by a community helper)** claim a **mock relief payment** even though **she cannot read forms, has a weak phone signal, and her name is spelled differently across records**.

The platform is a multi-user SaaS with users, roles, cases, versioned rules, consent, and an audit trail. It **decides, explains, and protects**, and it says "I am not sure" and hands the case to a human when confidence is low. A fake "relief payment" SMS checker is a side feature of the same flow (a citizen can ask "is this message real?").

**Scope discipline:** one task done end to end beats many half-done. Do not add features that are not in this file.

---

## 2. Tech stack (decided)

|Layer|Choice|Notes|
|---|---|---|
|Backend|**Python 3.11 + Flask** (app factory, Blueprints)|REST API under `/api/v1`|
|API docs|**SpecTree** (Pydantic + Flask)|Auto-serves Swagger UI at `/apidocs`|
|Validation / structured output|**Pydantic v2**|Same models used for request validation and AI structured output|
|Database|**Supabase Postgres** (+ `pgvector` extension)|Used as plain Postgres. Backend connects with the DB connection string via SQLAlchemy/psycopg|
|Migrations|Plain SQL files in `db/migrations/` (Supabase CLI or `psql`)|Numbered, applied in order. No auto-generated schema drift|
|Auth|**Supabase Auth** (email + password). Flask only **verifies** the Supabase JWT (PyJWT) and loads role/tenant from `users`|Supabase owns passwords, sessions, tokens. RBAC and tenancy still live in ONE place: the `users` table, enforced by Flask. <!-- CHANGED: SB-AUTH -->|
|File storage|Supabase Storage bucket `documents` (private)|Backend generates signed URLs|
|LLM / AI|Free-tier APIs behind **one wrapper** (`ai/llm_client.py`)|Groq (Llama + Whisper) as primary, Gemini free tier as fallback. Model names live in env vars, not code|
|Embeddings / RAG|`pgvector` table `policy_chunks`|Embedding model + dimension set in env (default dim 768)|
|Classical ML|scikit-learn (TF-IDF + logistic regression) for the scam classifier|Trained on a small mock dataset, model file committed|
|Name matching|`rapidfuzz` + `doublemetaphone` (Double Metaphone) + variant dictionary|`jellyfish` 1.0+ dropped `double_metaphone`; replaced with the dedicated `doublemetaphone` package — same algorithm, same output|
|OCR / CV (optional)|Tesseract + OpenCV (blur check)|Build only if ahead of schedule|
|Voice|Browser **Web Speech API** (STT `ur-PK`, TTS `speechSynthesis`) first; Groq Whisper as fallback endpoint||
|Frontend|**React + Vite + Tailwind**, PWA via `vite-plugin-pwa`, IndexedDB for offline queue. `@supabase/supabase-js` is used **for login/signup/session only** <!-- CHANGED: SB-AUTH -->|_Assumption: change this line if the team decides otherwise, before anyone writes UI code_|
|Deployment|Backend: Render or Railway (free tier). Frontend: Vercel or Netlify. DB: Supabase|Deploy an empty app in hour 1|
|Rate limiting|`Flask-Limiter`||
|Tests|`pytest`|At minimum: RBAC, consent withdrawal, rule versioning, decision thresholds|

---

## 3. Repository structure

```
/
├── PROPOSAL.md                  # this file
├── README.md                    # prototype label + real vs simulated list
├── .env.example
├── db/
│   ├── migrations/              # 001_init.sql, 002_..., applied in order
│   └── seed/                    # seed.py + data files (mock citizens, rules, policies)
├── backend/
│   ├── app/
│   │   ├── __init__.py          # create_app()
│   │   ├── config.py
│   │   ├── extensions.py        # db, limiter, spec
│   │   ├── auth/                # verify Supabase JWT, decorators: @require_role, @require_consent <!-- CHANGED: SB-AUTH -->
│   │   ├── api/                 # blueprints: auth, citizens, cases, rules, consents,
│   │   │                        #   audit, ai, mock_services, public, eval, sync, twin
│   │   ├── services/            # business logic: decision_engine, identity_match,
│   │   │                        #   consent_service, audit, rule_service, case_service
│   │   ├── ai/                  # llm_client, form_extractor, scam_classifier,
│   │   │                        #   rag, explain, ocr (optional)
│   │   ├── models/              # SQLAlchemy models (mirror Section 5 EXACTLY)
│   │   └── schemas/             # Pydantic models (mirror Section 6 and 7)
│   └── tests/
└── frontend/
    └── src/
        ├── pages/               # citizen/, helper/, officer/, admin/, auditor/
        ├── api/                 # one typed client, mirrors Section 7
        ├── i18n/                # en.json, ur.json (same keys in both)
        └── offline/             # IndexedDB queue + sync
```

**Ownership (to avoid merge conflicts):**

|Person|Owns|Does not touch|
|---|---|---|
|A (Backend 1)|`db/`, `models/`, `auth/`, `services/audit`, `services/consent_service`, `api/auth`, `api/consents`, `api/audit`|`ai/`, `frontend/`|
|B (Backend 2)|`services/decision_engine`, `services/identity_match`, `services/rule_service`, `services/case_service`, `api/cases`, `api/rules`, `api/twin`, `api/mock_services`, `api/sync`|`ai/`, `frontend/`|
|C (AI)|`ai/*`, `api/ai`, `api/public`, `api/eval`, seed data for scams and policies|`models/`, `frontend/`|
|D (Frontend)|`frontend/*`|`backend/*`|

If you must edit a file you do not own, tell the owner first.

---

## 4. Roles and permissions

Roles (enum `user_role`): `citizen`, `helper`, `officer`, `admin`, `auditor`.

| Action                           | citizen         | helper                              | officer                      | admin | auditor                                                     |
| -------------------------------- | --------------- | ----------------------------------- | ---------------------------- | ----- | ----------------------------------------------------------- |
| Log in, view own dashboard       | yes             | yes                                 | yes                          | yes   | yes                                                         |
| Create / edit own claim          | yes             | for linked citizens (needs consent) | no                           | no    | no                                                          |
| Upload documents, use voice/text | yes             | for linked citizens                 | no                           | no    | no                                                          |
| View a citizen's case data       | own only        | linked + consent                    | **only with active consent** | no    | read-only, logs only (no raw PII beyond what the log holds) |
| Approve / reject case            | no              | no                                  | yes                          | no    | no                                                          |
| Manage consent                   | own only        | no                                  | no                           | no    | read-only view                                              |
| Create / edit / activate rules   | no              | no                                  | no                           | yes   | read-only view                                              |
| Manage users and API keys        | no              | no                                  | no                           | yes   | no                                                          |
| Run Digital Twin simulation      | no              | no                                  | no                           | yes   | no                                                          |
| View audit log                   | own events only | no                                  | no                           | yes   | yes (full)                                                  |
| View evaluation dashboard        | no              | no                                  | yes                          | yes   | yes                                                         |

Notes:

- **Where role lives:** `users.role` is the only source of truth. Flask reads it from the DB on every request. Never trust `role` or `tenant_id` from JWT claims, `user_metadata` or anything the user can edit. <!-- CHANGED: SB-AUTH -->
- **Tenancy:** every row that belongs to a department carries `tenant_id`. Queries are always filtered by the caller's `tenant_id`. For the hackathon, seed 2 tenants (`Relief Dept`, `Complaints Dept`); the demo runs inside `Relief Dept`.
- **Helper mode:** a helper has many linked citizens through `helper_citizen_links`. The UI shows a "switch person" list; every request sends the active `citizen_id`; the backend checks the link and the consent.

---

## 5. Database schema (Postgres / Supabase)

This is the canonical schema. `db/migrations/001_init.sql` must match it exactly. Models and Pydantic schemas mirror it.

```sql
create extension if not exists "pgcrypto";
create extension if not exists vector;

-- ENUMS
create type user_role      as enum ('citizen','helper','officer','admin','auditor');
create type case_type      as enum ('relief_claim','scam_report');
create type case_status    as enum ('draft','needs_info','submitted','in_review','approved','rejected','closed');
create type route_type     as enum ('auto_approve','ask_more','human_review');
create type decision_actor as enum ('ai','officer');
create type decision_outcome as enum ('approved','rejected','needs_more_proof','human_review');
create type consent_status as enum ('granted','withdrawn');
create type consent_scope  as enum ('identity','documents','claim_data','contact');
create type rule_status    as enum ('draft','active','archived');
create type scam_label     as enum ('scam','legit','unsure');

-- TENANTS AND USERS  (users changed for SB-AUTH)
create table tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  plan text not null default 'free',
  created_at timestamptz not null default now()
);

create table users (                                  -- profile table; one row per Supabase Auth user
  id uuid primary key references auth.users(id) on delete cascade,  -- SAME id as auth.users (Supabase Auth)
  tenant_id uuid not null references tenants(id),
  email text not null unique,
  full_name text not null,
  role user_role not null,
  language text not null default 'ur',          -- 'ur' or 'en'
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);                                                -- password lives in auth.users, NOT here (SB-AUTH)

-- Every new Supabase signup gets a profile. Role is ALWAYS 'citizen', tenant is 'relief'.
-- Promote to officer/admin/etc only by UPDATE users SET role (admin or SQL), never from client metadata.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare t uuid;
begin
  select id into t from tenants where slug = 'relief';
  if t is null then raise exception 'tenant "relief" missing: run 001_init.sql fully'; end if;
  insert into users (id, tenant_id, email, full_name, role, language)
  values (new.id, t, new.email,
          coalesce(nullif(new.raw_user_meta_data->>'full_name',''), split_part(new.email,'@',1)),
          'citizen',
          case when new.raw_user_meta_data->>'language' in ('ur','en') then new.raw_user_meta_data->>'language' else 'ur' end)
  on conflict (id) do nothing;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

create table api_keys (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  label text not null,
  key_prefix text not null,                      -- first 8 chars, shown in UI
  key_hash text not null,                        -- sha256 of full key
  created_by uuid not null references users(id),
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);

-- CITIZENS (platform-side profile; may be created by a helper, so user_id is nullable)
create table citizens (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  user_id uuid references users(id),
  full_name text not null,
  father_name text,
  cnic text,                                     -- 13 digits, mock only
  dob date,
  district text,
  phone text,
  language text not null default 'ur',
  name_normalized text,                          -- output of normalize_name()
  name_phonetic text,                            -- double metaphone key
  created_by uuid references users(id),
  created_at timestamptz not null default now()
);
create index on citizens (cnic);
create index on citizens (name_phonetic);

create table helper_citizen_links (
  id uuid primary key default gen_random_uuid(),
  helper_user_id uuid not null references users(id),
  citizen_id uuid not null references citizens(id),
  status text not null default 'active',         -- 'active' | 'revoked'
  created_at timestamptz not null default now(),
  unique (helper_user_id, citizen_id)
);

-- MOCK IDENTITY REGISTRY (simulated NADRA-like source; separate from citizens)
create table mock_identity_records (
  id uuid primary key default gen_random_uuid(),
  cnic text,                                     -- may be NULL or wrong on purpose (bad data)
  full_name text not null,
  father_name text,
  dob date,
  district text,
  name_normalized text,
  name_phonetic text,
  is_deceased boolean not null default false
);
create index on mock_identity_records (cnic);
create index on mock_identity_records (name_phonetic);

-- RULES (versioned; never updated in place)
create table rules (
  id uuid primary key default gen_random_uuid(),     -- this is the rule_version_id
  tenant_id uuid not null references tenants(id),
  rule_key text not null,                            -- e.g. 'relief_eligibility'
  version int not null,
  status rule_status not null default 'draft',
  definition jsonb not null,                         -- see Section 8.4
  note text,
  created_by uuid references users(id),
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  unique (tenant_id, rule_key, version)
);
-- Only one active version per (tenant_id, rule_key):
create unique index one_active_rule on rules (tenant_id, rule_key) where status = 'active';

-- CASES
create table cases (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  case_type case_type not null,
  citizen_id uuid not null references citizens(id),
  created_by uuid not null references users(id),     -- citizen or helper
  assigned_to uuid references users(id),             -- officer
  status case_status not null default 'draft',
  route route_type,                                  -- latest AI route
  confidence numeric(4,3),                           -- latest AI confidence 0..1
  priority smallint not null default 2,              -- 1 high, 2 normal, 3 low
  form_data jsonb not null default '{}'::jsonb,      -- ClaimForm (Section 6.1)
  missing_fields text[] not null default '{}',
  rule_version_id uuid references rules(id),         -- rule used for latest decision
  last_step text,                                    -- for saved progress
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  closed_at timestamptz
);
create index on cases (tenant_id, status);
create index on cases (assigned_to);

create table case_events (                           -- human-readable timeline
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id),
  actor_id uuid references users(id),                -- null = system/AI
  event_type text not null,                          -- 'created','submitted','assigned','escalated','note','decision','closed','proof_requested'
  note text,
  created_at timestamptz not null default now()
);

create table documents (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id),
  kind text not null,                                -- 'cnic_photo' | 'supporting_doc'
  storage_path text not null,
  ocr_text text,
  quality_score numeric(4,3),                        -- 0..1 (blur/forgery check); null if not run
  uploaded_by uuid not null references users(id),
  created_at timestamptz not null default now()
);

-- DECISIONS (AI and officer decisions, never edited)
create table decisions (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id),
  actor_type decision_actor not null,
  actor_id uuid references users(id),                -- officer id; null for ai
  route route_type,                                  -- only for actor_type='ai'
  outcome decision_outcome not null,
  confidence numeric(4,3),
  rule_version_id uuid references rules(id),
  model_version text,                                -- e.g. 'engine-v1+llama-3.x'
  reason_en text not null,                           -- simple reason for the user
  reason_ur text not null,
  trace jsonb not null,                              -- full auditor trace, Section 9
  created_at timestamptz not null default now()
);
create index on decisions (case_id);

-- CONSENT
create table consents (
  id uuid primary key default gen_random_uuid(),
  citizen_id uuid not null references citizens(id),
  grantee_user_id uuid references users(id),         -- a specific helper/officer, OR
  grantee_role user_role,                            -- a whole role in the tenant (e.g. 'officer')
  scope consent_scope not null,
  status consent_status not null default 'granted',
  granted_at timestamptz not null default now(),
  withdrawn_at timestamptz,
  check ((grantee_user_id is not null) <> (grantee_role is not null))
);
create index on consents (citizen_id, status);

-- AUDIT LOG (append-only, hash-chained)
create table audit_logs (
  id bigserial primary key,
  ts timestamptz not null default now(),
  tenant_id uuid,
  actor_type text not null,                          -- 'user' | 'ai' | 'system' | 'api_key'
  actor_id text,                                     -- user id / api key id / null
  action text not null,                              -- see Section 8.6 action list
  entity_type text,                                  -- 'case','consent','rule','user',...
  entity_id text,
  payload jsonb not null default '{}'::jsonb,
  prev_hash text not null,
  hash text not null
);
create or replace function audit_logs_immutable() returns trigger as $$
begin raise exception 'audit_logs is append-only'; end; $$ language plpgsql;
create trigger audit_no_update before update or delete on audit_logs
  for each row execute function audit_logs_immutable();

-- SCAM MESSAGES (feeds the scam checker history and optional scam map)
create table scam_messages (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid references tenants(id),
  text text not null,
  label scam_label not null,
  confidence numeric(4,3) not null,
  category text,                                     -- 'fake_relief','phishing_link','impersonation','other'
  area text,                                         -- district, optional
  reported_by uuid references users(id),
  created_at timestamptz not null default now()
);

-- RAG
create table policy_chunks (
  id uuid primary key default gen_random_uuid(),
  doc_name text not null,
  chunk_index int not null,
  content text not null,
  embedding vector(768),                             -- must match EMBEDDING_DIM in .env
  unique (doc_name, chunk_index)
);

-- MOCK PAYMENTS
create table mock_payments (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id),
  amount numeric(12,2) not null,
  status text not null default 'queued',             -- 'queued' | 'paid' | 'failed'
  reference text not null,
  created_at timestamptz not null default now()
);

-- OFFLINE SYNC / IDEMPOTENCY
create table idempotency_keys (
  key text primary key,
  user_id uuid not null references users(id),
  response jsonb,
  created_at timestamptz not null default now()
);

-- EVALUATION RESULTS (written by eval scripts, read by dashboard)
create table eval_runs (
  id uuid primary key default gen_random_uuid(),
  name text not null,                                -- 'scam_classifier' | 'claim_router'
  metrics jsonb not null,                            -- confusion matrix, precision, recall, false_alarm_rate, avg_latency_ms
  created_at timestamptz not null default now()
);
```

**Row Level Security:** enable RLS on all tables with **no policies**, and `revoke all` on public tables from `anon` and `authenticated` (done in `001_init.sql`). The anon key is now in the frontend (Supabase Auth), so this is what stops anyone from reading tables directly through Supabase's auto API. Only the Flask backend, using the server connection string, reads or writes. Never expose the service role key or DB URL to the frontend. <!-- CHANGED: SB-AUTH -->

---

## 6. Core data shapes (Pydantic / JSON)

### 6.1 `ClaimForm` (stored in `cases.form_data`; also the AI structured output)

```json
{
  "full_name": "Fatima Bibi",
  "father_name": "Muhammad Aslam",
  "cnic": "4210112345671",
  "dob": "1978-04-12",
  "district": "Karachi East",
  "household_size": 5,
  "monthly_income": 18000,
  "is_widow": true,
  "phone": "03001234567"
}
```

Rules for the model:

- All fields are optional at parse time. Missing fields are listed in `missing_fields`.
- `cnic`: exactly 13 digits (strip dashes). `phone`: 11 digits starting `03`. `dob`: ISO date. `monthly_income`: finite number >= 0. `household_size` is a positive integer.
- `full_name` and `father_name` are text; `is_widow` is boolean. Unknown form keys are rejected.
- Required fields are derived from the active `relief_eligibility` rule's condition fields, plus `full_name`, and at least one identity corroborator (`cnic`, `dob`, or `father_name`). If no corroborator is present, `missing_fields` contains the virtual key `identity_corroborator`; clients should prompt for any one of those inputs. This key is not part of `ClaimForm`.
- Invalid values are retained in `form_data.invalid_fields` and included in `missing_fields`, so callers can correct them without losing the rest of the form. Phone format is checked when supplied but is not required by the service.

### 6.2 `IdentityMatch`

```json
{
  "status": "exact | probable | ambiguous | none",
  "score": 92.5,
  "confidence": 0.93,
  "matched_record_id": "uuid-or-null",
  "candidates": [{"record_id": "uuid", "name": "Mohammad Aslam", "score": 88.0}],
  "reasons": ["CNIC matches", "Name similarity 92.5 after normalization"]
}
```

### 6.3 `Decision` (API shape; mirrors `decisions` row)

```json
{
  "id": "uuid",
  "case_id": "uuid",
  "actor_type": "ai",
  "route": "human_review",
  "outcome": "human_review",
  "confidence": 0.62,
  "rule_version_id": "uuid",
  "rule_version": 3,
  "model_version": "engine-v1",
  "reason_en": "We are not sure this is the same person, so an officer will check it.",
  "reason_ur": "ہمیں یقین نہیں کہ یہ وہی شخص ہے، اس لیے ایک افسر اسے دیکھے گا۔",
  "trace": { }
}
```

### 6.4 `ScamCheckResult`

```json
{
  "label": "scam | legit | unsure",
  "confidence": 0.91,
  "category": "fake_relief",
  "reasons": ["Asks for CNIC and bank PIN", "Link is not a .gov.pk domain"],
  "advice_en": "Do not click the link. Do not share your PIN.",
  "advice_ur": "لنک پر کلک نہ کریں۔ اپنا پن شیئر نہ کریں۔"
}
```

---

## 7. REST API contract

Base path: `/api/v1`. Swagger UI at `/apidocs`. JSON only.

### 7.1 Envelope and errors

Success:

```json
{ "data": { }, "error": null }
```

Error:

```json
{ "data": null, "error": { "code": "CONSENT_WITHDRAWN", "message": "Citizen has withdrawn consent.", "details": {} } }
```

|HTTP|`error.code`|When|
|---|---|---|
|400|`VALIDATION_ERROR`|Bad input|
|401|`UNAUTHENTICATED`|Missing/invalid/expired JWT or API key|
|403|`FORBIDDEN_ROLE`|Role not allowed|
|403|`CONSENT_REQUIRED`|No consent for this scope|
|403|`CONSENT_WITHDRAWN`|Consent was withdrawn|
|404|`NOT_FOUND`|Missing (also used to hide other tenants' data)|
|409|`CONFLICT`|Duplicate / bad state transition|
|422|`LOW_CONFIDENCE`|Informational: AI refused to act alone (the case is handed off, not lost)|
|429|`RATE_LIMITED`|Limiter|
|502|`AI_UNAVAILABLE`|LLM provider down. The case still goes to `human_review`|
|500|`INTERNAL_ERROR`|Anything else (never leak stack traces)|

### 7.2 Auth <!-- CHANGED: SB-AUTH -->

Supabase Auth handles signup, login, password reset and token refresh. Flask never sees passwords and never issues tokens.

- Frontend: `supabase.auth.signUp({email,password,options:{data:{full_name,language}}})` and `signInWithPassword(...)`. The DB trigger `handle_new_user` creates the `users` profile as `citizen`.
- Every API call: `Authorization: Bearer <supabase access_token>`.
- **Flask verification rules (`auth/`):**
    1. Verify signature with PyJWT: preferred `SUPABASE_JWKS_URL` (asymmetric keys, `PyJWKClient`); legacy projects use `SUPABASE_JWT_SECRET` (HS256). Require `aud == "authenticated"` and valid `exp`/`sub`. A missing, malformed, expired, or invalid-signature token returns 401 `UNAUTHENTICATED`.
    2. `sub` = `users.id`. Load the row from `users` (`role`, `tenant_id`, `is_active`). No row or `is_active=false` returns 401 `UNAUTHENTICATED`. Database failures and JWKS/network/configuration failures return sanitized 500 `INTERNAL_ERROR`; they must not be misreported as invalid credentials.
    3. `role` and `tenant_id` come ONLY from that row, never from JWT claims.
- Public API uses header `X-API-Key: <key>` (only `/public/*` endpoints).
- Role changes (making someone officer/admin/auditor/helper) are done by an admin updating `users.role` (or SQL in the demo setup). The signup flow can never set a role.

|Method + Path|Role|Body / Notes|Returns|
|---|---|---|---|
|`POST /auth/session`|any (valid Supabase token)|No body. Call once right after login. Verifies token, writes `auth.login` to the audit log|`{user}`|
|`GET /auth/me`|any||`{user}`|

Removed: `POST /auth/register` and `POST /auth/login` (replaced by Supabase Auth).

### 7.3 Citizens and helper links

|Method + Path|Role|Notes|
|---|---|---|
|`POST /citizens`|citizen (self) / helper|Body: `full_name, father_name?, cnic?, dob?, district?, phone?`. Citizen-created profiles bind `user_id` to the authenticated citizen; helper-created profiles leave it null, auto-link to that helper, and **start with no consent**. Normalize/store name keys for identity matching. Writes `citizen.create`|
|`GET /citizens/{id}`|citizen self / helper (linked + consent) / officer (consent)|Consent-checked (scope `identity`); every allowed read writes `data.read_pii`|
|`PATCH /citizens/{id}`|citizen self|Partial correction of `full_name, father_name, cnic, dob, district, phone`; recalculates normalized and phonetic name keys when the name changes. Writes `citizen.update`|
|`GET /citizens/{id}/export`|citizen self|Returns profile, cases and form data, decisions and traces, case events, document metadata, mock payments, consent history, and helper-link history. Private documents include a signed download URL valid for five minutes; raw storage paths are omitted. Records are scoped to this citizen and tenant; the export is audited as `data.export`|
|`GET /helper/citizens`|helper|Lists own links for "switch person". Returns link metadata without profile fields while identity consent is missing; exposes the citizen name only after the normal link and consent check. Withdrawn-consent citizens are omitted|
|`POST /helper/citizens/{citizen_id}/link`|helper|Creates or reactivates a same-tenant link, pending the citizen's consent grant. Repeating an active link is safe and returns it. Writes `helper.link`|

### 7.4 Cases

|Method + Path|Role|Notes|
|---|---|---|
|`POST /cases`|citizen, helper|`{citizen_id, case_type}` returns case in `draft`. `scam_report` can be created as a case record, but this service currently supports form editing and decision submission only for `relief_claim`|
|`GET /cases`|citizen, helper, officer|Filters: `status, route, assigned_to`. Citizen: own. Helper: actively linked citizens. Officer: tenant queue, **sorted by** `route=human_review` first, then `priority asc`, then `confidence asc`. Excludes cases whose citizen withdrew consent for `claim_data`; every returned case passes the normal `claim_data` consent check and generates `data.read_pii` audit evidence. Admin and auditor cannot list case PII through this endpoint|
|`GET /cases/{id}`|scoped|Consent-checked for officer/helper. Includes `form_data, decisions[], events[]`|
|`PATCH /cases/{id}/form`|citizen, helper|`{form_data_partial, last_step}`: merges and re-validates; returns `missing_fields`. Saves progress after every step. Only `draft` and `needs_info` relief claims can be edited|
|`POST /cases/{id}/documents`|citizen, helper|multipart: `file`, `kind` (`cnic_photo` or `supporting_doc`). Allowed only in `draft` or `needs_info`; stores content in the private Supabase bucket configured by `SUPABASE_BUCKET` (default `documents`) at a tenant/case-scoped random path. API response exposes document metadata, never the storage path|
|`POST /cases/{id}/submit`|citizen, helper|Only relief claims in `draft` or `needs_info`. If required fields remain, saves `needs_info` and returns the missing list without deciding. Otherwise requires active officer `claim_data` consent, then runs the decision engine (Section 9) and returns `Decision` and new case status|
|`POST /cases/{id}/assign`|admin, officer|`{officer_id}`|
|`POST /cases/{id}/escalate`|officer|`{note}` (sets `priority=1`, event `escalated`)|
|`POST /cases/{id}/decision`|officer|`{outcome: "approved"\|"rejected"\|"needs_more_proof", note}` writes a `decisions` row with `actor_type='officer'`; sets status; if `approved`, creates a mock payment in the same transaction. The note is retained in `decisions.trace.note` and the case event; `reason_en`/`reason_ur` are deterministic bilingual outcome explanations, not copies of the officer note|
|`POST /cases/{id}/close`|officer, admin||

Status transitions allowed: `draft -> needs_info | submitted`, `needs_info -> submitted`, `submitted -> approved | in_review | needs_info`, `in_review -> approved | rejected | needs_info`, `approved|rejected -> closed`. Anything else returns 409 `CONFLICT`.

### 7.5 AI endpoints

|Method + Path|Role|Body|Returns|
|---|---|---|---|
|`POST /ai/transcribe`|citizen, helper|multipart audio, `lang`|`{text, confidence}` (fallback when browser STT is unavailable)|
|`POST /ai/extract-form`|citizen, helper|`{text, lang, existing_form?}`|`{form: ClaimForm, missing_fields[], confidence}`|
|`POST /ai/scam-check`|any logged-in|`{text}`|`ScamCheckResult` (also stored in `scam_messages`)|
|`POST /ai/ask`|any logged-in|`{question, lang}`|`{answer, sources:[{doc_name,chunk_index,snippet}], confidence}`. If no source supports the answer: `{answer: null, handoff: true}`|

### 7.6 Rules and Digital Twin

|Method + Path|Role|Notes|
|---|---|---|
|`GET /rules?rule_key=`|admin, auditor, officer|All versions with status|
|`POST /rules`|admin|`{rule_key, definition, note}` creates a **new draft version** (version = max + 1). Never edits an old version|
|`POST /rules/{id}/activate`|admin|Atomically archives the current active version and activates this one. **Takes effect on the next request, no redeploy**|
|`POST /twin/simulate`|admin|`{draft_rule_id, limit?}` replays this tenant's submitted `relief_claim` cases against a draft rule (in memory, writes nothing and emits no audit row). Optional `limit` must be positive and selects newest cases first; omitted means all submitted cases. Returns `{total, changed, results:[{case_id, old_outcome, new_outcome}], summary:{more_approvals, fewer_approvals, more_human_reviews, fewer_human_reviews}}`. Evaluation failures safely count as `human_review`; response contains case IDs and outcomes only, not form data|

### 7.7 Consent

|Method + Path|Role|Notes|
|---|---|---|
|`GET /consents?citizen_id=`|citizen self, auditor|Who has access to what, with status and dates|
|`POST /consents`|citizen self|`{citizen_id, grantee_user_id? \| grantee_role?, scope}`|
|`POST /consents/{id}/withdraw`|citizen self|Sets `status='withdrawn'`, `withdrawn_at=now()`. **Effective immediately**: the next read by the grantee returns 403 `CONSENT_WITHDRAWN`|
|`GET /citizens/{id}/export`|citizen self|Returns all data held about the citizen (correct/see data)|
|`PATCH /citizens/{id}`|citizen self|Correct own data|

### 7.8 Audit

|Method + Path|Role|Notes|
|---|---|---|
|`GET /audit-logs`|admin, auditor|Filters: `actor_id, action, entity_type, entity_id, from, to`; paginated (`page`, `page_size`)|
|`GET /audit-logs/verify`|auditor, admin|Recomputes the hash chain; returns `{valid: true\|false, broken_at?: id}`|
|`GET /audit-logs/mine`|citizen|Own events|

### 7.9 Mock services (separate blueprint, called internally and also exposed)

|Method + Path|Notes|
|---|---|
|`POST /mock/identity/lookup`|citizen, helper|`{cnic?, full_name?, father_name?, dob?}` returns the `IdentityMatch` candidate output; may return wrong/incomplete matches on purpose|
|`POST /mock/payments`|admin, officer|`{case_id, amount}` creates/returns a queued `mock_payments` row only for an approved case; amount must match the case's immutable rule version. A case has at most one payment; repeat calls return the existing row without another write or `mock.payment.create` audit event. New rows created here emit `mock.payment.create`; payments created atomically by an AI or officer approval are covered by `ai.decision` or `officer.decision` instead|
|`GET /mock/payments/{id}`|citizen, helper, officer with authorized case access|Returns payment status and reference; applies the case's normal ownership, link, and consent checks. Admin may create a payment but cannot read a citizen's payment status through this endpoint|
|`POST /mock/complaints`|citizen, helper|`{case_id, text}` validates case access and returns a fake complaint reference; complaint text is not persisted|

### 7.10 Public API (API key)

|Method + Path|Notes|
|---|---|
|`POST /public/scam-check`|`{text}` returns `ScamCheckResult`. Rate-limited per key|
|`GET /public/cases/{id}/status`|Returns only `{status, updated_at}`. No PII|

### 7.11 Offline sync

`POST /sync/batch` (citizen, helper). Body:

```json
{ "ops": [
  { "client_op_id": "uuid", "type": "patch_form", "case_id": "uuid", "payload": { "form_data_partial": {}, "last_step": "income" } },
  { "client_op_id": "uuid", "type": "create_case", "payload": { "citizen_id": "uuid", "case_type": "relief_claim" } }
]}
```

Response uses the standard envelope: `{ "data": { "results": [ { "client_op_id": "uuid", "status": "applied | duplicate | error", "result": {"case_id":"uuid", ...} | null, "error": null | {"code":"...","message":"..."} } ] }, "error": null }`. Supported operation types are `create_case` and `patch_form`; a batch has 1–100 operations and is processed in order. Each successful operation and its `idempotency_keys` record commit atomically in its own transaction, so a failed operation does not undo earlier successful operations. The key is globally unique and bound to the authenticated user; a replay by the same user returns `duplicate` and the original result, while another user reusing it gets a per-operation conflict. Failed operations are not cached and may be corrected and retried. Successful operations write `sync.batch` in the same transaction.

### 7.12 Evaluation and health

- `GET /eval/summary` (officer, admin, auditor): latest `eval_runs` per `name`, plus live counters (cases by route, auto-approved count, human handoffs, avg decision latency).
- `GET /health` (public): `{status:"ok", db:"ok"}`.

---

## 8. Core logic (everyone must implement this the same way)

### 8.1 Name normalization (`normalize_name`)

1. Lowercase, strip punctuation and honorifics (`mr`, `mrs`, `bibi`, `begum`, `sahib`, `syed` optional).
2. Collapse variants via dictionary, e.g.: `muhammad, mohammad, muhammed, mohammed, mohd, md, muhamad -> muhammad`; `ahmed/ahmad -> ahmad`; `hussain/hussein/husain -> hussain`.
3. Transliterate common Urdu-script names to the same Latin keys if the dictionary has them.
4. Store `name_normalized` and `name_phonetic` (Double Metaphone of each token, joined).

### 8.2 Identity matching (`match_identity(form) -> IdentityMatch`)

Compare the form against `mock_identity_records` using `rapidfuzz.fuzz.token_sort_ratio` on normalized names (score 0..100).

|Situation|`status`|`confidence`|
|---|---|---|
|CNIC equals AND name score >= 85|`exact`|`0.90 + 0.09 * (score-85)/15` (0.99 at 100)|
|CNIC equals AND name score < 85|`ambiguous`|0.50|
|CNIC missing/different AND name score >= 90 AND (dob equal OR father name score >= 85)|`probable`|0.75|
|Multiple candidates within 5 points of the best|`ambiguous`|0.50|
|Anything else|`none`|0.20|

**Hard rules:** never match on name alone; never auto-merge duplicate people; a near match means ask a human. `is_deceased=true` forces `human_review`.

### 8.3 Scam classifier

- scikit-learn TF-IDF + logistic regression trained on a small mock dataset (about 200 to 300 labeled messages: fake relief, phishing links, legit official-style notices; Urdu, Roman Urdu, English).
- Output `label` by probability `p_scam`: `p >= 0.85 -> scam`, `p <= 0.15 -> legit`, otherwise `unsure`.
- `unsure` is shown honestly ("We are not sure. Do not click. Ask your helper."), never silently labeled.
- Heuristic features added: non-`.gov.pk` links, requests for PIN/CNIC/OTP, urgency words.

### 8.4 Rule definition JSON (`rules.definition`)

```json
{
  "rule_key": "relief_eligibility",
  "match": "all",
  "conditions": [
    { "id": "c1", "field": "monthly_income", "op": "lte", "value": 30000,
      "reason_en": "Monthly income must be PKR 30,000 or less.",
      "reason_ur": "ماہانہ آمدنی 30,000 روپے یا اس سے کم ہونی چاہیے۔" },
    { "id": "c2", "field": "is_widow", "op": "eq", "value": true,
      "reason_en": "The claim is for widows.", "reason_ur": "یہ دعویٰ بیواؤں کے لیے ہے۔" },
    { "id": "c3", "field": "district", "op": "in", "value": ["Karachi East","Karachi West","Karachi South"],
      "reason_en": "Applicant must live in an eligible district.", "reason_ur": "درخواست گزار اہل ضلع میں رہتا ہو۔" }
  ],
  "required_documents": ["cnic_photo"],
  "amount": 25000,
  "thresholds": { "auto_approve": 0.98, "ask_more": 0.70 },
  "cost": { "wrong_approval": 50, "manual_review": 1 },
  "anomaly": {
    "duplicate_open_claim": { "enabled": true },
    "helper_burst": {
      "enabled": true,
      "max_per_window": 10,
      "window_minutes": 10,
      "max_per_day": 60
    },
    "deceased_match": { "enabled": true }
  }
}
```

- Allowed `op`: `eq, ne, lt, lte, gt, gte, in, not_in`.
- The engine **reads thresholds and conditions from the active rule version at request time** (cache for at most a few seconds, or not at all). No hard-coded numbers in Python.
- The engine also reads anomaly enablement and thresholds from the active rule version. Rule changes to anomaly behavior therefore take effect without a code change.
- Cost logic documented in the admin UI: auto-approve only if `(1 - confidence) * wrong_approval < manual_review`, i.e. `confidence > 1 - manual_review / wrong_approval` (0.98 for 50:1). The `thresholds.auto_approve` value must be at least this.

### 8.5 Decision engine (`decide(case) -> Decision`)

Executed on `POST /cases/{id}/submit`. Steps, in order:

1. **Validate form.** If `missing_fields` is non-empty: set case `needs_info`, return the list. Do not decide.
2. **Load active rule** for `(tenant_id, 'relief_eligibility')`. Record `rule_version_id`.
3. **Identity match** (8.2) gives `identity_conf`.
4. **Documents:** if a required document is missing, outcome is `needs_more_proof`. Else `doc_conf` = `quality_score` of the document if present, else `1.0`.
5. **Completeness:** `completeness_conf = 1.0` if no invalid fields, else `0.6`.
6. **Evaluate eligibility** conditions: `eligible` (bool) and `failed_conditions[]`.
7. **Anomaly flags:** evaluate each flag only when its `anomaly.<flag>.enabled` value in the active rule is `true`:
   - `duplicate_open_claim`: find another case of type `relief_claim` in the same tenant with the same CNIC, excluding the current case. Match through the citizen CNIC, not `citizen_id`, so duplicate citizen profiles do not hide a claim. A case is open when its status is not `rejected` or `closed` (that includes `draft`, `needs_info`, `submitted`, `in_review`, and `approved`). One or more matches sets the flag.
   - `helper_burst`: count submissions by the same helper. Set the flag when the count is greater than `max_per_window` within `window_minutes`, or greater than `max_per_day` within 24 hours. A submission is a `case_events` row with `event_type='submitted'` and that helper's `actor_id`. With the example values, the limits are more than 10 submissions in 10 minutes or more than 60 in 24 hours.
   - `deceased_match`: set the flag when the matched identity record has `is_deceased=true`.

   Store fired flag names exactly as `duplicate_open_claim`, `helper_burst`, and `deceased_match` in `trace.anomaly_flags`. Any fired flag forces `human_review`; the officer queue shows the flags and the user's reason explains the relevant issue (for example, “We found another claim with your ID, so an officer will check.”). These flags mean suspicious, not guilty; they never cause an AI rejection.
8. **Confidence** = `min(identity_conf, doc_conf, completeness_conf)`.
9. **Route:**
    - If any anomaly flag, or `eligible == false`, or an AI call failed: `route = human_review` (**the AI never auto-rejects**; wrong rejections also cost people).
    - Else if `confidence >= thresholds.auto_approve`: `route = auto_approve`, outcome `approved`.
    - Else if `confidence >= thresholds.ask_more`: `route = ask_more`, outcome `needs_more_proof` (the explanation says exactly which proof).
    - Else: `route = human_review`, outcome `human_review`, with case notes attached.
10. **Explain:** build `reason_en` / `reason_ur` from the rule's `reason_*` templates and the route (deterministic text; an LLM may only rephrase, never decide).
11. **Persist** a `decisions` row, update `cases` (`status, route, confidence, rule_version_id`), add a `case_events` row, call `audit.log('ai.decision', ...)`. If `auto_approve`, create a mock payment.

`human_review` cases get `status='in_review'` and appear in the officer queue with `trace` and notes attached.

### 8.6 Audit logging (`audit.log`)

Single function, single code path:

```python
audit.log(actor_type, actor_id, action, entity_type, entity_id, payload, tenant_id)
# hash = sha256(prev_hash + canonical_json({ts, tenant_id, actor_type, actor_id, action, entity_type, entity_id, payload}))
# prev_hash = hash of the last row (or 64 zeros for the first row). Use a DB advisory lock so concurrent writes keep the chain valid.
```

Required `action` values (use exactly these; failed logins are in Supabase Auth logs, not here <!-- CHANGED: SB-AUTH -->): `auth.login`, `user.create`, `user.update`, `citizen.create`, `citizen.update`, `helper.link`, `case.create`, `case.update_form`, `case.submit`, `case.assign`, `case.escalate`, `case.close`, `document.upload`, `mock.payment.create`, `ai.extract_form`, `ai.scam_check`, `ai.rag_answer`, `ai.decision`, `officer.decision`, `rule.create`, `rule.activate`, `consent.grant`, `consent.withdraw`, `consent.access_denied`, `data.read_pii`, `data.export`, `apikey.create`, `apikey.revoke`, `sync.batch`. The read-only Digital Twin is an explicit exception: it returns aggregate decision outcomes and case IDs but writes no audit or application data, so it does not emit `twin.simulate` or `data.read_pii` rows.

### 8.7 Consent enforcement (`@require_consent(scope)`)

For any read of citizen data by someone other than the citizen:

1. Citizen reading own data: allowed.
2. Helper: needs an active `helper_citizen_links` row **and** a `granted` consent for that helper (or role `helper`) with the scope.
3. Officer: needs a `granted` consent for `grantee_role='officer'` with the scope. The citizen grants officer consent (scope `claim_data`, `identity`, `documents`) when submitting a claim (shown clearly in the UI with a toggle).
4. If the latest matching consent is `withdrawn`: return 403 `CONSENT_WITHDRAWN` and log `consent.access_denied`. If none: 403 `CONSENT_REQUIRED`.
5. Log `data.read_pii` for every allowed read.

### 8.8 Rate limiting and failure handling

- Global default 120 requests/min per IP; stricter on `/auth/session` (10/min) <!-- CHANGED: SB-AUTH --> and `/ai/*` (30/min per user); per-key limits on `/public/*`.
- LLM calls: timeout 10 s, one retry, then fallback provider, then give up and go to `human_review` or return `AI_UNAVAILABLE`. Never return a guessed answer.

---

## 9. Decision trace format (`decisions.trace`)

This is the auditor view. The user only sees `reason_en` / `reason_ur`.

```json
{
  "input_snapshot": { "form_data": {}, "documents": ["cnic_photo"] },
  "rule": { "rule_key": "relief_eligibility", "rule_version_id": "uuid", "version": 3 },
  "identity_match": { "status": "ambiguous", "confidence": 0.5, "candidates": [] },
  "eligibility": { "eligible": true, "failed_conditions": [], "evaluated": [ { "id": "c1", "result": true } ] },
  "anomaly_flags": [],
  "confidences": { "identity": 0.5, "documents": 1.0, "completeness": 1.0, "final": 0.5 },
  "thresholds": { "auto_approve": 0.98, "ask_more": 0.70 },
  "route": "human_review",
  "outcome": "human_review",
  "model_version": "engine-v1",
  "llm_used": false,
  "latency_ms": 143,
  "created_at": "2026-11-21T10:00:00Z"
}
```

---

## 10. Frontend requirements

- **Low literacy:** big icon buttons, one question per screen, a speaker button on every screen that reads the text aloud (`speechSynthesis`, `ur-PK`), a mic button to answer by voice, progress bar made of icons, no long paragraphs.
- **Languages:** Urdu (default, RTL) and English. All text via `i18n/ur.json` and `i18n/en.json`, same keys in both.
- **Weak internet:** PWA with service worker; app shell cached; form progress saved to IndexedDB after every step; queued operations carry `client_op_id` and sync via `POST /sync/batch` when online; visible online/offline badge; small pages, no heavy images.
- **Pages by role:**
    - Citizen: claim wizard, case status, "is this message real?" scam check, consent center (who has my data, toggle, withdraw), my data export.
    - Helper: list of linked citizens, "switch person" with a confirmation, same wizard per citizen.
    - Officer: review queue (sorted as in 7.4), case detail with trace summary and notes, approve / reject / ask for proof.
    - Admin: rule editor (form view of Section 8.4 JSON, creates a new version, shows cost-of-error numbers), Digital Twin simulate, users and API keys, analytics.
    - Auditor: audit log table with filters, hash-chain verify button, consent records, AI decisions with full trace, evaluation dashboard.
- Always show a **"Prototype, not an official service"** banner.
- The frontend calls Supabase **only for Auth** (signUp, signIn, signOut, session refresh) with the public anon key. All data goes through `/api/v1`; never `supabase.from(...)` or Storage directly. <!-- CHANGED: SB-AUTH -->

---

## 11. Mock data (seed script `db/seed/seed.py`)

Must be deterministic and re-runnable.

- **Tenants:** `Relief Dept` (slug `relief`), `Complaints Dept` (slug `complaints`).
- **Demo users** (password for all: `Demo@1234`). Created in `auth.users` (seed SQL, or Dashboard > Authentication with Auto Confirm); the trigger creates profiles; the seed then sets each `users.role` <!-- CHANGED: SB-AUTH -->:
    - `citizen@demo.pk` (citizen), `helper@demo.pk` (helper, linked to 5 citizens), `officer@demo.pk`, `admin@demo.pk`, `auditor@demo.pk`
- **200 mock identity records** with deliberate bad data: missing CNICs, duplicated people, name variants (Muhammad / Mohammad / Muhammed), swapped given/father names, one deceased record.
- **Scripted demo personas** (fixed so the live demo is reliable):
    1. _Clear case:_ name, CNIC, district all match exactly, income under the limit. Result: `auto_approve`.
    2. _Ambiguous case:_ "Mohammad Aslam" vs two records "Muhammad Aslam" with similar details. Result: `human_review`.
    3. _Missing info:_ no income given. Result: `needs_info`.
    4. _Ineligible:_ income above the limit. Result: `human_review` with a recommendation (never auto-reject).
    5. _Duplicate claim:_ same CNIC as an open case. Result: `human_review` (anomaly flag).
- **Rules:** `relief_eligibility` v1 (income <= 30000) active with the Section 8.4 anomaly settings; a draft v2 (income <= 40000) prepared for the live rule-change demo.
- **Policy docs for RAG:** 3 to 4 short mock documents (eligibility rules, required documents, how to appeal, how to spot scams), chunked into `policy_chunks`.
- **Scam dataset:** 200 to 300 labeled messages for training and evaluation (keep a held-out test set for the evaluation dashboard).

---

## 12. Environment variables (`.env.example`)

```
FLASK_ENV=development
SECRET_KEY=change-me
SUPABASE_JWKS_URL=https://xxxx.supabase.co/auth/v1/.well-known/jwks.json   # preferred for JWT verification (SB-AUTH)
SUPABASE_JWT_SECRET=...                  # only if project still uses the legacy HS256 secret; server-side only (SB-AUTH)
DATABASE_URL=postgresql://...            # Supabase connection string (server-side only)
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=...                 # server-side only, never in frontend
SUPABASE_BUCKET=documents
GROQ_API_KEY=...
GROQ_LLM_MODEL=...                       # check current free model names
GROQ_WHISPER_MODEL=...
GEMINI_API_KEY=...
GEMINI_LLM_MODEL=...
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=...
EMBEDDING_DIM=768
CORS_ORIGINS=http://localhost:5173
RATE_LIMIT_DEFAULT=120/minute
```

Frontend `.env`: `VITE_API_BASE_URL=http://localhost:5000/api/v1`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (anon key is public by design; no other secrets) <!-- CHANGED: SB-AUTH -->.

---

## 13. Challenge-to-feature map (what judges will test)

|Brief challenge|Where it lives|
|---|---|
|Cost of being wrong|`rules.definition.cost` + thresholds, Section 8.4 and 8.5, chart on the admin page|
|Saying "I am not sure"|`route=human_review`, `unsure` scam label, RAG `handoff:true`|
|Bad data|8.1, 8.2, `needs_info`, never name-only match|
|Rules that change|`rules` versioning, `POST /rules/{id}/activate`, `decisions.rule_version_id`|
|Explain and audit|`reason_en/ur` + `trace`, audit hash chain and verify|
|Consent and take-back|`consents`, `@require_consent`, withdraw returns 403 immediately|
|Works for everyone|Voice, icons, PWA, `/sync/batch`, saved progress|
|Scams and fake documents|`/ai/scam-check`, honest evaluation page with false alarms|
|Bonus: Digital Twin|`POST /twin/simulate`|

---

## 14. Live demo script (5 minutes)

1. Citizen (or helper) speaks the claim in Urdu, the form fills, the system reads it back.
2. Persona 1 submits and is auto-approved with a simple reason.
3. Persona 2 submits, the system says "not sure", and the case appears in the officer queue with notes.
4. Admin activates rule v2; the next case follows it; an older case still shows rule v1.
5. Citizen withdraws officer consent; the officer's next read returns 403; the audit log shows `consent.withdraw` and `consent.access_denied`.
6. Scam checker flags a fake relief SMS as `scam`, shows a real notice as `legit`, and shows one `unsure` case honestly.
7. Go offline, complete a step, reconnect, and see it sync once with no duplicates.
8. Auditor opens the full trace for one decision and runs the hash-chain verify.

---

## 15. Milestones (24 hours)

|Hours|Goal|
|---|---|
|0 to 2|Agree on this file. Create repo, Supabase project, run `001_init.sql`, deploy empty backend and frontend, seed demo users|
|2 to 8|A: auth, RBAC, audit, consent. B: rule service, identity match, decision engine, cases API. C: LLM wrapper, form extractor, scam classifier, RAG ingest. D: login, citizen wizard skeleton, officer queue|
|8 to 14|Integrate the end-to-end flow (voice, form, match, rule decision, route, explanation, officer handoff)|
|14 to 18|Admin rule editor, consent center, user and auditor explanation views, PWA offline queue|
|18 to 21|Digital Twin, evaluation dashboard, rate limiting, tests|
|21 to 23|Bug bash against the demo script, README (list what is real vs simulated), record demo video|
|23 to 24|Freeze, deploy, rehearse twice. No new features|

---

## 16. Definition of done (per feature)

- Endpoint exists exactly as in Section 7 and appears in Swagger.
- Role and consent checks are enforced server-side and covered by at least one test.
- It writes the right `audit.log` action.
- The frontend uses the typed client and the response envelope.
- It works on the deployed environment, not only locally.

## 17. Do not

- Do not use real personal data (disqualification).
- Do not rename or add schema fields without updating this file.
- Do not let any AI path approve a case when it errors or is unsure.
- Do not put secrets in the frontend or the repo. Only the Supabase **anon** key may be in the frontend; never the service role key, DB URL or JWT secret. <!-- CHANGED: SB-AUTH -->
- Do not build features outside this file before the end-to-end flow works.
- 
