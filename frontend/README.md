# Frontend passkey sign-in

This initial frontend slice demonstrates passkey sign-in through Supabase Auth. It does not collect or upload biometric samples. After Supabase returns a session, the app calls the existing Flask `/api/v1/auth/session` endpoint; Flask continues to verify the Supabase JWT and load the user's role from the database.

## Run locally

```bash
npm ci
cp .env.example .env
npm run dev
```

Fill in `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and `VITE_API_BASE_URL` in `frontend/.env`.

## Run the automated checks

From `frontend/`, run:

```bash
npm test
npm run build
```

The frontend tests mock Supabase and the Flask API, so they do not need a real account, network access, or biometric device. They cover passkey sign-in and backend session verification, failed sign-in, password sign-in followed by passkey enrollment, backend JWT rejection, and the Urdu/English direction toggle. From the repository root, run the backend CORS and regression tests with:

```bash
cd backend
venv/bin/python -m pytest -q
```

## Enable passkeys in Supabase

Passkeys are experimental in the current Supabase JavaScript SDK and must be enabled in the Supabase Dashboard under **Authentication → Passkeys**. Set a stable relying-party ID and allowed origins before users enroll. For local development, use the local frontend origin `http://localhost:5173`; production requires the deployed HTTPS origin. Changing the relying-party ID later invalidates existing passkeys.

Supabase requires an existing, confirmed account to register a passkey. Create the account, confirm it if email confirmation is enabled, sign in once with the account password, then choose **Add a passkey to this device**. Returning users can then use **Sign in with passkey** without entering an email or password. Keep the password sign-in for account setup and recovery.
