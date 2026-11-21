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

-- Reference data needed by the signup trigger (fixed ids, re-runnable)
insert into tenants (id,name,slug) values
 ('a0000000-0000-0000-0000-000000000001','Relief Dept','relief'),
 ('a0000000-0000-0000-0000-000000000002','Complaints Dept','complaints') on conflict do nothing;

-- RLS: enable on every public table, NO policies
do $$ declare r record; begin
  for r in select tablename from pg_tables where schemaname='public' loop
    execute format('alter table public.%I enable row level security', r.tablename);
  end loop;
end $$;

-- anon key is public now (Supabase Auth in frontend): remove direct API access to our tables
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;