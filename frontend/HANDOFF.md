# Frontend Handoff

## Stack
React 18 + Vite + react-router + @supabase/supabase-js. Plain CSS only. Colors: `#09392B` (green), `#F9F5EA` (cream). No Tailwind, no PWA plugin.
Run: `cp .env.example .env` (fill 3 vars) -> `npm install` -> `npm run dev`. Build verified OK.

## Done
- `src/api/client.js`: Supabase auth client + `api/get/post/patch` helpers (Bearer token, unwraps `{data,error}`).
- `src/auth.jsx`: login/signup/logout, loads user from `/auth/me`, calls `/auth/session` after login.
- `src/i18n/`: en + ur (same keys), RTL toggle, default Urdu.
- `src/ui.jsx`: speaker button (speechSynthesis TTS only), error box, icon progress bar, online/offline badge (auto-flushes offline queue), `useLoad` hook, JSON viewer.
- `src/offline/queue.js`: localStorage queue with `client_op_id`, flushes via `POST /sync/batch`.
- Role-based nav in `App.jsx`; "Prototype" banner always shown.
- Citizen: claim wizard (one question per screen, saves each step via PATCH, CNIC photo upload, submit, bilingual decision), cases status, scam check, consent center (grant/withdraw), data export.
- Helper: linked people list, switch person (with confirm), add person, same wizard.
- Officer: review queue, case detail (raw JSON), approve/reject/needs proof/escalate with required note, eval summary.
- Admin: rules list/create draft/activate, Digital Twin simulate, API keys (create/revoke), audit log, eval.
- Auditor: audit table with action filter + pagination, verify chain button, eval.
- NOT included by request: speech-to-text (user adds own; hook it into `Wizard.jsx` text input and `Scam.jsx` textarea).

## Session 2 update
Added: `checkConnection()` + `ConnBadge` (shows Supabase/API reachability on Login and as warning in app; missing-.env warning), wizard validation (CNIC 13 digits, phone 03xxxxxxxxx, numbers), citizen-id recovery from `GET /cases`, citizen/helper Ask page (`POST /ai/ask`, tolerant of answer field names), officer readable trace summary (guessed field names, raw JSON kept in `<details>`), audit filters (entity_type, actor_id, date_from/date_to). Build OK.
IMPORTANT: the zip contained only the frontend. The database is reached via Supabase (auth) + backend API (`VITE_API_BASE_URL`, default http://localhost:5000/api/v1, expects `/health` or root to respond). Frontend cannot be proven connected until backend + Supabase keys are set in `.env`; open Login page and check the badge shows ✓ ✓.
Remaining from list below: 1, 2 (helper consent UI), 3 (profile step/PATCH citizen), 5, 6, 8, plus 7 polling. Items 4, 7(ask), 9, 10 are done (10 param names `date_from`/`date_to` unverified).

## To do next (priority order)
1. Test against running backend + real Supabase. Response shapes were guessed in places (see risks).
2. Helper flow: `GET /helper/citizens` item field names (`citizen_id` vs `id`, `full_name`) unverified. Helper must also grant/confirm consent via the citizen; there is no helper UI for that.
3. Citizen id is stored in `localStorage.citizen_id` because the API has no "get my citizen" endpoint. Wizard creates the profile with only `full_name`; consider a profile step and a `PATCH /citizens/{id}` for the other fields.
4. Officer detail: replace raw JSON with a readable trace summary (identity match, rule, confidence).
5. Admin rule editor is raw JSON; proposal wants a form view + cost-of-error numbers. Admin "users" and "analytics" pages missing.
6. Auditor: consent records view and AI decisions with full trace are missing.
7. Citizen: ask-a-question page (`POST /ai/ask`) missing; case status could poll `/cases`.
8. Offline: only `patch_form` queues when a case already exists; `create_case` offline and IndexedDB (proposal) not done; no service worker/PWA manifest.
9. Field validation in wizard (CNIC 13 digits, phone `03xxxxxxxxx`); backend errors are shown as-is.
10. Audit table: add other filters (entity_type, dates, actor_id).

## Risks / unverified
- `/cases` list item fields (`route`, `priority`, `confidence`, `decisions`) assumed from the proposal.
- Consent `scope` values `claim_data` and `identity` come from the proposal; check the backend enum.
- No automated tests written.


## Session 3 update (build NOT verified: sandbox had no network, `npm install` impossible; run `npm install && npm run build` first and fix any typo)
Added:
- `src/pages/Browse.jsx`: generic tolerant list viewer (expandable rows + raw JSON).
- Auditor nav: Consents (`GET /consents`), AI decisions (`GET /ai/decisions`) via Browse. Endpoint paths GUESSED.
- Admin nav: Users (`GET /admin/users`), Analytics (`GET /analytics`) via Browse. Paths GUESSED.
- Citizen `Status.jsx` polls `/cases` every 15s.
- Helper `People.jsx`: shows Consent panel (grant/withdraw) for the active person above the wizard. Helper-side confirm flow still unverified against backend.
- i18n keys: decisions, users, analytics (en+ur).

## Remaining TODO (for next Claude)
1. `npm install && npm run build`; fix errors.
2. Test with real backend + Supabase; correct guessed endpoints/field names (Browse paths above, `/helper/citizens` fields, `/cases` fields, consent scope enum, audit `date_from/date_to`).
3. Wizard profile step + `PATCH /citizens/{id}` for cnic/phone/etc (currently only `full_name` is created).
4. Admin rule editor: form view + cost-of-error numbers (still raw JSON).
5. Offline: `create_case` offline, IndexedDB, service worker + PWA manifest (none yet).
6. Auditor: richer AI-decision trace view (Browse shows raw JSON only).
7. Speech-to-text intentionally NOT included (hook into `Wizard.jsx` input and `Scam.jsx` textarea).
8. No automated tests.
