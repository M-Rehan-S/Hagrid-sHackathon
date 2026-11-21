-- Deterministic, re-runnable quick seed (fixed UUIDs). seed.py can replace later.
-- name_phonetic values below are hand-written approximations of Double Metaphone.
-- Tenants are created in 001. Demo users: auth.users -> trigger creates profiles (role=citizen) -> we set roles.
-- If the auth.users insert errors on your Supabase version: create the 5 users in Dashboard > Authentication
-- (Auto Confirm, password Demo@1234, then run the role UPDATE below; ids differ, so also see note at bottom of README).
insert into auth.users (instance_id,id,aud,role,email,encrypted_password,email_confirmed_at,raw_app_meta_data,raw_user_meta_data,
  created_at,updated_at,confirmation_token,recovery_token,email_change_token_new,email_change,email_change_token_current,phone_change,phone_change_token,reauthentication_token)
select '00000000-0000-0000-0000-000000000000',v.id::uuid,'authenticated','authenticated',v.email,crypt('Demo@1234',gen_salt('bf',10)),now(),
  '{"provider":"email","providers":["email"]}'::jsonb,jsonb_build_object('full_name',v.n,'language','ur'),now(),now(),'','','','','','','',''
from (values
 ('b0000000-0000-0000-0000-000000000001','citizen@demo.pk','Demo Citizen'),
 ('b0000000-0000-0000-0000-000000000002','helper@demo.pk','Demo Helper'),
 ('b0000000-0000-0000-0000-000000000003','officer@demo.pk','Demo Officer'),
 ('b0000000-0000-0000-0000-000000000004','admin@demo.pk','Demo Admin'),
 ('b0000000-0000-0000-0000-000000000005','auditor@demo.pk','Demo Auditor')) v(id,email,n)
where not exists (select 1 from auth.users u where u.email=v.email);

insert into auth.identities (id,user_id,provider_id,identity_data,provider,last_sign_in_at,created_at,updated_at)
select gen_random_uuid(),u.id,u.id::text,jsonb_build_object('sub',u.id::text,'email',u.email,'email_verified',true),'email',now(),now(),now()
from auth.users u where u.email like '%@demo.pk' and not exists (select 1 from auth.identities i where i.user_id=u.id);

-- Set roles (idempotent; works for dashboard-created users too, matched by email)
update users u set role=v.r::user_role from (values
 ('citizen@demo.pk','citizen'),('helper@demo.pk','helper'),('officer@demo.pk','officer'),
 ('admin@demo.pk','admin'),('auditor@demo.pk','auditor')) v(email,r) where u.email=v.email;

-- Personas (citizens c...01..05)
insert into citizens (id,tenant_id,user_id,full_name,father_name,cnic,dob,district,phone,name_normalized,name_phonetic,created_by) values
 ('c0000000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','Fatima Bibi','Muhammad Aslam','4210112345671','1978-04-12','Karachi East','03001234567','fatima','FTM','b0000000-0000-0000-0000-000000000001'),
 ('c0000000-0000-0000-0000-000000000002','a0000000-0000-0000-0000-000000000001',null,'Mohammad Aslam','Abdul Karim',null,'1980-01-01','Karachi West','03111111111','muhammad aslam','MHMT ASLM','b0000000-0000-0000-0000-000000000002'),
 ('c0000000-0000-0000-0000-000000000003','a0000000-0000-0000-0000-000000000001',null,'Ayesha Khatoon','Rashid Ali','4210133333333','1985-06-30','Karachi South','03222222222','ayesha khatoon','AX KTN','b0000000-0000-0000-0000-000000000002'),
 ('c0000000-0000-0000-0000-000000000004','a0000000-0000-0000-0000-000000000001',null,'Zainab Begum','Hussain Ali','4210144444444','1975-09-09','Karachi East','03333333333','zainab','SNP','b0000000-0000-0000-0000-000000000002'),
 ('c0000000-0000-0000-0000-000000000005','a0000000-0000-0000-0000-000000000001',null,'Nasreen Akhtar','Ghulam Nabi','4210155555555','1982-02-02','Karachi West','03444444444','nasreen akhtar','NSRN AKTR','b0000000-0000-0000-0000-000000000002')
on conflict do nothing;

insert into helper_citizen_links (helper_user_id,citizen_id)
select 'b0000000-0000-0000-0000-000000000002', id from citizens where id::text like 'c0000000%' and id <> 'c0000000-0000-0000-0000-000000000001'
on conflict do nothing;

-- Mock identity registry (deliberate bad data)
insert into mock_identity_records (id,cnic,full_name,father_name,dob,district,name_normalized,name_phonetic,is_deceased) values
 ('d0000000-0000-0000-0000-000000000001','4210112345671','Fatima Bibi','Muhammad Aslam','1978-04-12','Karachi East','fatima','FTM',false),   -- clear match
 ('d0000000-0000-0000-0000-000000000002','4210198765432','Muhammad Aslam','Abdul Karim','1980-01-01','Karachi West','muhammad aslam','MHMT ASLM',false), -- ambiguous pair
 ('d0000000-0000-0000-0000-000000000003','4210198765433','Muhammed Aslam','Abdul Karim','1980-01-02','Karachi West','muhammad aslam','MHMT ASLM',false),
 ('d0000000-0000-0000-0000-000000000004','4210133333333','Ayesha Khatoon','Rashid Ali','1985-06-30','Karachi South','ayesha khatoon','AX KTN',false),
 ('d0000000-0000-0000-0000-000000000005','4210144444444','Zainab Begum','Hussain Ali','1975-09-09','Karachi East','zainab','SNP',false),
 ('d0000000-0000-0000-0000-000000000006','4210155555555','Nasreen Akhtar','Ghulam Nabi','1982-02-02','Karachi West','nasreen akhtar','NSRN AKTR',false),
 ('d0000000-0000-0000-0000-000000000007',null,'Bashir Ahmad','Karim Bakhsh','1950-05-05','Karachi South','bashir ahmad','PXR AHMT',true)       -- deceased, no CNIC
on conflict do nothing;

-- Rules: v1 active, v2 draft
insert into rules (id,tenant_id,rule_key,version,status,definition,note,created_by,activated_at)
select v.id::uuid,'a0000000-0000-0000-0000-000000000001','relief_eligibility',v.ver,v.st::rule_status,
 jsonb_build_object('rule_key','relief_eligibility','match','all',
  'conditions', jsonb_build_array(
    jsonb_build_object('id','c1','field','monthly_income','op','lte','value',v.inc,'reason_en','Monthly income must be within the limit.','reason_ur','ماہانہ آمدنی حد کے اندر ہونی چاہیے۔'),
    jsonb_build_object('id','c2','field','is_widow','op','eq','value',true,'reason_en','The claim is for widows.','reason_ur','یہ دعویٰ بیواؤں کے لیے ہے۔'),
    jsonb_build_object('id','c3','field','district','op','in','value',jsonb_build_array('Karachi East','Karachi West','Karachi South'),'reason_en','Applicant must live in an eligible district.','reason_ur','درخواست گزار اہل ضلع میں رہتا ہو۔')),
  'required_documents', jsonb_build_array('cnic_photo'),'amount',25000,
  'thresholds', jsonb_build_object('auto_approve',0.98,'ask_more',0.70),
  'cost', jsonb_build_object('wrong_approval',50,'manual_review',1)),
 v.note,'b0000000-0000-0000-0000-000000000004', case when v.st='active' then now() end
from (values ('e0000000-0000-0000-0000-000000000001',1,'active',30000,'v1 income<=30000'),
             ('e0000000-0000-0000-0000-000000000002',2,'draft',40000,'v2 demo: income<=40000')) v(id,ver,st,inc,note)
on conflict do nothing;

-- Consents: citizen1 -> officer role (3 scopes) + helper; citizen4 withdrew officer consent
insert into consents (id,citizen_id,grantee_user_id,grantee_role,scope,status,withdrawn_at) values
 ('f0000000-0000-0000-0000-000000000001','c0000000-0000-0000-0000-000000000001',null,'officer','claim_data','granted',null),
 ('f0000000-0000-0000-0000-000000000002','c0000000-0000-0000-0000-000000000001',null,'officer','identity','granted',null),
 ('f0000000-0000-0000-0000-000000000003','c0000000-0000-0000-0000-000000000001',null,'officer','documents','granted',null),
 ('f0000000-0000-0000-0000-000000000004','c0000000-0000-0000-0000-000000000004',null,'officer','claim_data','withdrawn',now()),
 ('f0000000-0000-0000-0000-000000000005','c0000000-0000-0000-0000-000000000002','b0000000-0000-0000-0000-000000000002',null,'claim_data','granted',null)
on conflict do nothing;

-- Cases (one per persona + an earlier open case for persona 5's duplicate)
insert into cases (id,tenant_id,case_type,citizen_id,created_by,status,form_data,missing_fields,route,confidence) values
 ('10000000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001','relief_claim','c0000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','draft',
  '{"full_name":"Fatima Bibi","father_name":"Muhammad Aslam","cnic":"4210112345671","dob":"1978-04-12","district":"Karachi East","household_size":5,"monthly_income":18000,"is_widow":true,"phone":"03001234567"}','{}',null,null),
 ('10000000-0000-0000-0000-000000000002','a0000000-0000-0000-0000-000000000001','relief_claim','c0000000-0000-0000-0000-000000000002','b0000000-0000-0000-0000-000000000002','draft',
  '{"full_name":"Mohammad Aslam","father_name":"Abdul Karim","dob":"1980-01-01","district":"Karachi West","household_size":4,"monthly_income":20000,"is_widow":true,"phone":"03111111111"}','{}',null,null),
 ('10000000-0000-0000-0000-000000000003','a0000000-0000-0000-0000-000000000001','relief_claim','c0000000-0000-0000-0000-000000000003','b0000000-0000-0000-0000-000000000002','draft',
  '{"full_name":"Ayesha Khatoon","father_name":"Rashid Ali","cnic":"4210133333333","dob":"1985-06-30","district":"Karachi South","is_widow":true}','{monthly_income,household_size}',null,null),
 ('10000000-0000-0000-0000-000000000004','a0000000-0000-0000-0000-000000000001','relief_claim','c0000000-0000-0000-0000-000000000004','b0000000-0000-0000-0000-000000000002','draft',
  '{"full_name":"Zainab Begum","father_name":"Hussain Ali","cnic":"4210144444444","dob":"1975-09-09","district":"Karachi East","household_size":6,"monthly_income":45000,"is_widow":true,"phone":"03333333333"}','{}',null,null),
 ('10000000-0000-0000-0000-000000000005','a0000000-0000-0000-0000-000000000001','relief_claim','c0000000-0000-0000-0000-000000000005','b0000000-0000-0000-0000-000000000002','in_review',
  '{"full_name":"Nasreen Akhtar","cnic":"4210155555555","dob":"1982-02-02","district":"Karachi West","household_size":3,"monthly_income":15000,"is_widow":true,"phone":"03444444444"}','{}','human_review',0.5),
 ('10000000-0000-0000-0000-000000000006','a0000000-0000-0000-0000-000000000001','relief_claim','c0000000-0000-0000-0000-000000000005','b0000000-0000-0000-0000-000000000002','draft',
  '{"full_name":"Nasreen Akhtar","cnic":"4210155555555","dob":"1982-02-02","district":"Karachi West","household_size":3,"monthly_income":15000,"is_widow":true,"phone":"03444444444"}','{}',null,null)
on conflict do nothing;

-- Scam samples + one RAG chunk
insert into scam_messages (tenant_id,text,label,confidence,category) values
 ('a0000000-0000-0000-0000-000000000001','Mubarak! Relief Rs 25000 mil gaye. Click http://bit.ly/x aur CNIC/PIN bhejein','scam',0.97,'fake_relief'),
 ('a0000000-0000-0000-0000-000000000001','Your relief claim status was updated. Visit relief.gov.pk','legit',0.93,null),
 ('a0000000-0000-0000-0000-000000000001','Aap ka claim check karne ke liye call karein','unsure',0.55,'other');
insert into policy_chunks (doc_name,chunk_index,content,embedding)
values ('eligibility',0,'Widows with monthly income up to PKR 30,000 in eligible Karachi districts qualify.',array_fill(0.01::real,array[768])::vector)
on conflict do nothing;
