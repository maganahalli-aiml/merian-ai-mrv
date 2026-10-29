# Priority 0 Security Setup

Phase 1 uses Firebase Authentication with Google sign-in and one shared document collection. All approved users can run procurement audits, ask questions, and list the shared documents. Only document managers can upload PDFs or trigger GCS ingestion. Tenant isolation is intentionally out of scope.

## Firebase project setup

1. Use the same Google Cloud project as the Cloud Run deployment. The deployment workflow verifies that the Firebase Web app project ID matches this project.
2. Add a Firebase Web app in Firebase project settings and copy its `apiKey`, `authDomain`, `projectId`, and `appId`.
3. In Firebase Console, enable **Authentication → Sign-in method → Google**.
4. Add the deployed Cloud Run hostname under **Authentication → Settings → Authorized domains**. For local development, add `localhost`.
5. Restrict the web API key by HTTP referrer to the app's approved hostnames and by API to the Firebase Authentication / Identity Toolkit APIs. The web key is public client configuration, not a Gemini key or service-account credential.

The deployment workflow enables `identitytoolkit.googleapis.com`. It also grants the Cloud Run runtime identity `roles/firebaseauth.viewer`, used by Firebase Admin token-revocation checks.

## GitHub deployment configuration

Add these repository **Actions secrets** before running the deployment workflow:

| Secret | Value |
|---|---|
| `FIREBASE_WEB_API_KEY` | Firebase Web app API key |
| `FIREBASE_AUTH_DOMAIN` | Firebase Web app auth domain |
| `FIREBASE_WEB_PROJECT_ID` | Firebase Web app project ID |
| `FIREBASE_WEB_APP_ID` | Firebase Web app ID |
| `ALLOWED_USER_EMAILS` | Comma-separated exact email addresses approved to sign in |
| `DOCUMENT_MANAGER_EMAILS` | Comma-separated exact email addresses permitted to upload and ingest |

Every document manager must also appear in `ALLOWED_USER_EMAILS`. The backend validates this relationship and fails closed if the access lists are missing or inconsistent. Email matching is case-insensitive.

If the frontend is hosted on a different origin from the API, add a repository **Actions variable** named `CORS_ALLOWED_ORIGINS` containing only exact origins, comma-separated, for example `https://app.example.com`. Do not include URL paths. For the current same-origin Cloud Run frontend/API, leave it empty.

The frontend Firebase values are embedded in the built client bundle and are therefore public. Never put Gemini keys, service-account credentials, or other server secrets in these frontend settings.

To add or remove users or document managers, update the corresponding GitHub secrets and rerun the deployment workflow. The new Cloud Run revision receives the updated lists.

## Local development

Set these backend variables in the repository-root `.env` file. Local verification checks the Firebase token signature, project, expiry, and verified email using Firebase's public certificates; revocation checks default to off, so local Google ADC is not required:

```dotenv
FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_CHECK_REVOKED=false
ALLOWED_USER_EMAILS=reader@example.com,manager@example.com
DOCUMENT_MANAGER_EMAILS=manager@example.com
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

Set the four `VITE_FIREBASE_*` values from the Firebase Web app configuration in `frontend/.env.local`. The local backend must have Google Application Default Credentials available for Firebase Admin token checks. There is no authentication bypass for local mode.

## Runtime behavior

- The sign-in page offers **Continue with Google**. Firebase keeps the browser sign-in session using local browser persistence; the app never asks for a Google password.
- The frontend sends Firebase ID tokens in the `Authorization: Bearer` header. The backend verifies signature, project, expiry, and verified email using Firebase Admin. Token revocation checking is controlled by `FIREBASE_CHECK_REVOKED`; it is off locally by default and on in Cloud Run, where Firebase Admin uses the runtime service identity.
- `/api/health` remains a minimal public liveness check. The frontend shell and static assets remain publicly reachable so users can reach the sign-in screen. Every other API route, including status and stored-document listing, requires an approved ID token.
- Audit and document-query operations are available to all approved users. Upload and GCS re-ingestion are checked server-side and require a document-manager email. Hiding the upload tab for readers is only a usability measure; the backend check is authoritative.
- All approved users share the same documents and vector index. This configuration does not provide per-user or per-organization document privacy.
- CORS is disabled unless exact origins are configured. CORS is not an authentication control.
- Unexpected server failures return safe messages. Responses include an `X-Request-ID` header; use it to correlate a support report with server logs.

## Upload limits

Cloud Run deployment configures these defaults:

| Limit | Default |
|---|---:|
| Individual PDF | 20 MiB |
| Entire multipart request | 25 MiB |
| Files per request | 5 |
| Pages per PDF | 500 |

The API enforces the request limit while receiving the request, copies each file to disk in bounded chunks, validates PDF content and page count before ingestion, and rejects oversized content with HTTP 413.

## Verification

Focused backend tests:

```bash
.venv/bin/python -m pytest backend/tests/test_api.py backend/tests/test_auth.py backend/tests/test_modes_and_middleware.py -q
```

Frontend checks:

```bash
npm --prefix frontend run lint
npm --prefix frontend run build
```

Before promoting a deployment, verify that an unapproved account receives 403, an approved reader can query but receives 403 on upload, and an approved document manager can upload an acceptable PDF. Also verify the Cloud Run response for an unauthenticated API request is rejected and that a disallowed origin receives no CORS allow-origin header.
