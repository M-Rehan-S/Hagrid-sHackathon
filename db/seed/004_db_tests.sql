-- Run AFTER 001, 002, seed_test. Everything runs in one script; read the final table. All rows should be pass = true.
create temp table t (name text, pass boolean, detail text);

-- helper pattern: expect-error tests (inner changes auto-roll back on error)
do $$ begin begin
  insert into rules (tenant_id,rule_key,version,status,definition) values ('a0000000-0000-0000-0000-000000000001','relief_eligibility',99,'active','{}');
  insert into t values ('only one active rule per key',false,'no error');
exception when unique_violation then insert into t values ('only one active rule per key',true,sqlerrm); end; end $$;

do $$ begin begin
  insert into rules (tenant_id,rule_key,version,definition) values ('a0000000-0000-0000-0000-000000000001','relief_eligibility',1,'{}');
  insert into t values ('duplicate rule version rejected',false,'no error');
exception when unique_violation then insert into t values ('duplicate rule version rejected',true,sqlerrm); end; end $$;

do $$ begin begin
  insert into consents (citizen_id,grantee_user_id,grantee_role,scope) values ('c0000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000003','officer','identity');
  insert into t values ('consent needs user XOR role',false,'no error');
exception when check_violation then insert into t values ('consent needs user XOR role',true,sqlerrm); end; end $$;

do $$ begin begin
  insert into audit_logs (action,actor_type,prev_hash,hash) values ('test','system',repeat('0',64),'h1');
  update audit_logs set action='tampered' where hash='h1';
  insert into t values ('audit_logs UPDATE blocked',false,'no error');
exception when others then insert into t values ('audit_logs UPDATE blocked',sqlerrm like '%append-only%',sqlerrm); end; end $$;

do $$ begin begin
  insert into audit_logs (action,actor_type,prev_hash,hash) values ('test','system',repeat('0',64),'h2');
  delete from audit_logs where hash='h2';
  insert into t values ('audit_logs DELETE blocked',false,'no error');
exception when others then insert into t values ('audit_logs DELETE blocked',sqlerrm like '%append-only%',sqlerrm); end; end $$;

do $$ begin begin
  insert into cases (tenant_id,case_type,citizen_id,created_by) values ('a0000000-0000-0000-0000-000000000001','relief_claim',gen_random_uuid(),'b0000000-0000-0000-0000-000000000001');
  insert into t values ('case needs valid citizen (FK)',false,'no error');
exception when foreign_key_violation then insert into t values ('case needs valid citizen (FK)',true,sqlerrm); end; end $$;

do $$ begin begin
  update cases set status='banana' where id='10000000-0000-0000-0000-000000000001';
  insert into t values ('invalid enum rejected',false,'no error');
exception when invalid_text_representation then insert into t values ('invalid enum rejected',true,sqlerrm); end; end $$;

do $$ begin begin
  insert into users (id,tenant_id,email,full_name,role) values (gen_random_uuid(),'a0000000-0000-0000-0000-000000000001','ghost@demo.pk','Ghost','citizen');
  insert into t values ('profile needs a Supabase auth user (FK)',false,'no error');
exception when foreign_key_violation then insert into t values ('profile needs a Supabase auth user (FK)',true,sqlerrm); end; end $$;

-- Signup trigger: creates profile and IGNORES role sent in user metadata
do $$ declare r user_role; begin begin
  insert into auth.users (id,instance_id,aud,role,email,raw_user_meta_data,created_at,updated_at)
  values ('99999999-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000000','authenticated','authenticated','trigger_test@demo.pk','{"full_name":"T","role":"admin"}',now(),now());
  select role into r from users where id='99999999-0000-0000-0000-000000000001';
  raise exception 'ROLE_%', r;
exception when others then insert into t values ('signup trigger forces role=citizen',sqlerrm='ROLE_citizen',sqlerrm); end; end $$;

do $$ begin begin
  insert into policy_chunks (doc_name,chunk_index,content,embedding) values ('bad',0,'x','[1,2,3]');
  insert into t values ('embedding dim must be 768',false,'no error');
exception when others then insert into t values ('embedding dim must be 768',true,sqlerrm); end; end $$;

-- Rule activation swap is atomic and leaves exactly one active (rolled back afterwards)
do $$ declare n int; begin begin
  update rules set status='archived' where id='e0000000-0000-0000-0000-000000000001';
  update rules set status='active', activated_at=now() where id='e0000000-0000-0000-0000-000000000002';
  select count(*) into n from rules where rule_key='relief_eligibility' and status='active';
  raise exception 'ROLLBACK_%', n;
exception when others then insert into t values ('rule v2 activation leaves 1 active', sqlerrm='ROLLBACK_1', sqlerrm); end; end $$;

-- Decisions immutable (needs 002)
do $$ begin begin
  insert into decisions (id,case_id,actor_type,outcome,reason_en,reason_ur,trace) values ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','ai','approved','ok','ٹھیک','{}');
  update decisions set outcome='rejected' where id='20000000-0000-0000-0000-000000000001';
  insert into t values ('decisions UPDATE blocked (002)',false,'no error');
exception when others then insert into t values ('decisions UPDATE blocked (002)',sqlerrm like '%append-only%',sqlerrm); end; end $$;

-- State/data checks
insert into t select 'RLS enabled on all public tables', count(*)=0, coalesce(string_agg(tablename,','),'') from pg_tables where schemaname='public' and not rowsecurity;
insert into t select 'one active rule v1 for relief', count(*)=1, '' from rules where status='active' and version=1;
insert into t select 'officer consent OK for citizen1 (claim_data)', exists(select 1 from consents where citizen_id='c0000000-0000-0000-0000-000000000001' and grantee_role='officer' and scope='claim_data' and status='granted'),'';
insert into t select 'officer consent WITHDRAWN for citizen4', not exists(select 1 from consents where citizen_id='c0000000-0000-0000-0000-000000000004' and grantee_role='officer' and scope='claim_data' and status='granted'),'';
insert into t select 'duplicate open claim detectable (persona 5)', count(*)>=2, count(*)::text from cases where form_data->>'cnic'='4210155555555' and status not in ('closed','rejected');
insert into t select 'ambiguous pair exists (persona 2)', count(*)=2, '' from mock_identity_records where name_normalized='muhammad aslam';
insert into t select 'deceased record exists', count(*)=1, '' from mock_identity_records where is_deceased;
insert into t select 'demo password hash valid in auth.users', encrypted_password = crypt('Demo@1234',encrypted_password), '' from auth.users where email='officer@demo.pk';
insert into t select '5 demo profiles with correct roles', count(*)=5, count(*)::text from users where (email,role) in (('citizen@demo.pk','citizen'),('helper@demo.pk','helper'),('officer@demo.pk','officer'),('admin@demo.pk','admin'),('auditor@demo.pk','auditor'));
insert into t select 'anon/authenticated have no table privileges', count(*)=0, coalesce(string_agg(distinct table_name,','),'') from information_schema.role_table_grants where table_schema='public' and grantee in ('anon','authenticated');
insert into t select 'helper linked to 4 seeded citizens', count(*)=4, count(*)::text from helper_citizen_links where helper_user_id='b0000000-0000-0000-0000-000000000002';
insert into t select 'audit_logs untouched by tests', count(*)=0, '' from audit_logs where hash in ('h1','h2');

select * from t order by pass, name;   -- failures on top