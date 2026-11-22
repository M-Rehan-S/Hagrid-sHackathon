# Relief Claim Copilot frontend

Responsive React app for the API contract in `../PROPOSAL.md`. Citizen pages start in Urdu and use a one-question-at-a-time application flow, large controls, voice input/output when the browser supports it, and a numbered mobile navigation. Staff pages use a desktop-oriented workspace and are available to the role returned by the backend. English/Urdu text, RTL layout, offline draft storage, a retryable sync queue, and an installable PWA shell are included.

The frontend uses Supabase for authentication only. All user, case, rules, audit, consent, AI and mock-service data is requested from Flask at `/api/v1`.

## Run locally

```sh
npm ci
cp .env.example .env
npm run dev
```

Set `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, and `VITE_SUPABASE_ANON_KEY` in `frontend/.env`. These are public client configuration values; never put a service-role key or other server secret in a `VITE_` variable. Start the Flask API separately and configure Supabase Auth to allow the local frontend origin.

Supabase passkeys must be enabled in the Supabase dashboard with the deployment's WebAuthn relying-party ID and allowed origins. Password sign-in, signup, recovery, and passkey enrollment are available. The backend still determines the user's role and permissions.

## Checks

```sh
npm test
npm run build
```

The tests cover auth/session handling, API envelopes and errors, English/Urdu dictionary parity, and the citizen profile/application save/submit journey. They mock Supabase and Flask and do not need a live account or backend.

## Backend capabilities that constrain the UI

The frontend follows `PROPOSAL.md` when it differs from `prompt.md`. The API currently describes one `relief_claim` program and has no user-administration or public scheme-list endpoint. Rule editing accepts the proposal's JSON rule definition; it cannot ingest PDFs. Identity checks are a mock service and helper linking awaits citizen consent. Device passkeys are handled by Supabase; the app never collects palm or fingerprint images. The helper receives a citizen ID to request a link because the proposal's identity lookup returns mock identity candidates rather than a citizen record ID.
