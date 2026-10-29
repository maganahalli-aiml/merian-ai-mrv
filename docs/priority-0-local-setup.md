# Priority 0: Local Firebase Setup

This guide walks through testing Priority 0 authentication locally before deploying. It uses Firebase Google sign-in and the backend's Firebase ID-token verification. For safer testing, use a separate Firebase project for development rather than production.

## 1. Configure Firebase

In the [Firebase Console](https://console.firebase.google.com/):

1. Create or select a development project.
2. Open **Project settings → General → Your apps**. Add a **Web app** and copy its `apiKey`, `authDomain`, `projectId`, and `appId`.
3. Open **Authentication → Sign-in method** and enable **Google**. Select a support email if prompted.
4. Open **Authentication → Settings → Authorized domains**. Ensure `localhost` is listed; add it if it is missing. Do not include a protocol or port.
5. In Google Cloud Console for the same project, ensure the **Identity Toolkit API** is enabled.

## 2. Configure local environment files

The backend reads settings from the repository-root `.env`. Add these values to the existing file; do not overwrite any other settings:

```dotenv
APP_MODE=local
FIREBASE_PROJECT_ID=your-development-project-id
ALLOWED_USER_EMAILS=your-google-email@example.com,reader@example.com
DOCUMENT_MANAGER_EMAILS=your-google-email@example.com
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

Use the exact email address you will use for Google sign-in. Every document manager must also appear in `ALLOWED_USER_EMAILS`. To test a reader account, include its email in `ALLOWED_USER_EMAILS` but not in `DOCUMENT_MANAGER_EMAILS`.

The frontend reads the Firebase Web app configuration from `frontend/.env.local`:

```dotenv
VITE_FIREBASE_API_KEY=your-web-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-development-project-id
VITE_FIREBASE_APP_ID=your-web-app-id
```

Before creating this file, verify whether Git already ignores it:

```bash
git check-ignore -v frontend/.env.local
```

If the command prints nothing, add `frontend/.env.local` to `.gitignore` before putting local configuration in it. The Firebase web configuration is public client configuration, but local environment files should not be committed. Never put Gemini API keys, service-account credentials, or other server secrets in the frontend configuration.

Restart the frontend development server after changing `.env.local`; Vite reads these values when it starts.

## 3. Backend token verification (no `gcloud` login needed)

The backend validates the Firebase ID token's signature, issuer, audience/project, and expiry using Google's public signing certificates. The default local setting has revocation checking disabled, so you do **not** need to run `gcloud auth application-default login` or provide a service-account key to test local sign-in.

For local development, leave `FIREBASE_CHECK_REVOKED` unset or set it to `false` in the repository-root `.env`. Do not disable signature or expiry verification.

Revocation checking is an optional additional check: it calls Firebase Authentication to determine whether a still-valid token was explicitly revoked or its user disabled. To test that behavior locally, set `FIREBASE_CHECK_REVOKED=true`, then configure Google ADC with `gcloud auth application-default login`. The ADC identity needs the **Firebase Authentication Viewer** role (`roles/firebaseauth.viewer`) on the Firebase project. Production Cloud Run enables revocation checking and uses its runtime service identity; it does not use a developer's personal credentials.

## 4. Start the app

From the repository root, open two terminals.

**Terminal 1 — backend:**

```bash
.venv/bin/python -m uvicorn api.main:app --app-dir backend --reload --port 8080
```

**Terminal 2 — frontend:**

```bash
npm --prefix frontend run dev
```

Open the Vite URL printed in the frontend terminal, normally `http://localhost:3000`. In development, Vite proxies `/api` requests to the backend at `http://127.0.0.1:8080` from inside the WSL environment. This avoids requiring the Windows browser to connect directly to the WSL backend port.

## 5. Verify sign-in and permissions

Before signing in, confirm the backend is available and that a protected route rejects anonymous access:

```bash
curl -i http://localhost:8080/api/health
curl -i http://localhost:3000/api/health
curl -i http://localhost:3000/api/rag/uploads
```

Expected results:

- `/api/health` returns `200`.
- `/api/health` through the Vite URL on port 3000 also returns `200`.
- `/api/rag/uploads` through the Vite URL returns `401` without an ID token.

Then open the frontend and select **Continue with Google**:

- An account listed in `ALLOWED_USER_EMAILS` should be admitted.
- A signed-in reader can use Q&A and audit but should not see the document upload tab. A direct upload request should still be rejected by the backend with `403`.
- A signed-in document manager should see the upload tab. Uploading and model-backed operations may also require local storage or model configuration; those are not necessary just to test sign-in and role enforcement.

You can test the reader restriction directly in the browser developer console while signed in as a reader:

```javascript
const token = await (await import("firebase/auth")).getAuth().currentUser.getIdToken();
await fetch("/api/rag/upload", {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` },
});
```

The request intentionally has no uploaded file; the manager permission check should reject it first with `403`.

## Troubleshooting

- **`auth/unauthorized-domain`:** Add `localhost` under Firebase Authentication's authorized domains.
- **Account not approved:** Confirm the email from the selected Google account is present in `ALLOWED_USER_EMAILS`; check spelling and that the backend `.env` was loaded.
- **Backend `503` during sign-in:** Confirm `FIREBASE_PROJECT_ID`, `ALLOWED_USER_EMAILS`, and `DOCUMENT_MANAGER_EMAILS` are set correctly, and that manager emails are also in the approved-user list. If `FIREBASE_CHECK_REVOKED=true`, also check that the backend has ADC credentials with `roles/firebaseauth.viewer`. With the local default (`false`), ADC is not required.
- **Frontend reports Firebase configuration is missing:** Confirm all four `VITE_FIREBASE_*` values are in `frontend/.env.local`, then restart Vite.
- **CORS error:** Confirm `CORS_ALLOWED_ORIGINS` exactly matches the frontend origin, including scheme and port, for example `http://localhost:3000`.

For the full Phase 1 implementation notes and deployment configuration, see [priority-0-security-setup.md](./priority-0-security-setup.md) and [priority-0-enhancement-summary.docx](./priority-0-enhancement-summary.docx).
