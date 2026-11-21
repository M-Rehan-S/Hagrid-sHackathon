-- OPTIONAL: needs team OK (add to PROPOSAL.md first). No tables/columns renamed or added.
create or replace function set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;
create trigger cases_updated_at before update on cases for each row execute function set_updated_at();

create or replace function decisions_immutable() returns trigger as $$
begin raise exception 'decisions is append-only'; end; $$ language plpgsql;
create trigger decisions_no_update before update or delete on decisions for each row execute function decisions_immutable();

alter table citizens add constraint citizens_cnic_chk  check (cnic  is null or cnic  ~ '^[0-9]{13}$');
alter table citizens add constraint citizens_phone_chk check (phone is null or phone ~ '^03[0-9]{9}$');

create index on cases ((form_data->>'cnic'));            -- duplicate-claim anomaly check
create index on cases (citizen_id);
create index on case_events (case_id);
create index on documents (case_id);
create index on consents (grantee_user_id);
create index on helper_citizen_links (citizen_id);
create index on audit_logs (entity_type, entity_id);
create index on audit_logs (action);

insert into storage.buckets (id, name, public) values ('documents','documents',false) on conflict do nothing;