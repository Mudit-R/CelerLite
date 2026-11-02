# Private workspace sign-in

CelerLite authenticates approved accounts through Supabase Auth using email/password;
Google OAuth is supported after its provider is configured in Supabase. Its CRM and
task records currently form one shared workspace: every approved user can access
all of those records. This is not a per-user or multi-tenant authorization model.
Public self-service signup is intentionally not enabled.

Configure `CELERLITE_SUPABASE_URL`, `CELERLITE_SUPABASE_PUBLISHABLE_KEY`,
`CELERLITE_AUTH_ALLOWED_USER_IDS` (comma-separated Supabase user UUIDs), and the
exact `CELERLITE_AUTH_PUBLIC_ORIGIN` in the server's environment. Use an HTTPS
origin and `CELERLITE_AUTH_COOKIE_SECURE=true` for public deployments. Local HTTP
is accepted only for localhost/127.0.0.1/::1 with the secure-cookie flag false.
Never use a Supabase secret or service-role key. Configuration failure denies
workspace access; the health check and sign-in page remain available.

For Google sign-in, configure a Google Cloud OAuth web client and enable the
Google provider in Supabase Auth. Set the Google client's authorized redirect URI
to `https://<project-ref>.supabase.co/auth/v1/callback`. Add the application's
exact `/auth/google/callback` URL to Supabase's redirect allowlist, for example
`http://127.0.0.1:18009/auth/google/callback` during local development and the
HTTPS production callback for deployment. Follow the [Supabase Google setup
guide](https://supabase.com/docs/guides/auth/social-sign-in/auth-google).
If Google's consent screen is in testing mode, add each approved account as a
test user. After that account first completes Google sign-in, look up its
Supabase user ID and add it to `CELERLITE_AUTH_ALLOWED_USER_IDS`; the first
attempt is denied until the ID has been approved. Never put the Google client
secret in CelerLite's source code or environment; configure it in Supabase.
The OAuth code is exchanged server-side using PKCE and an HttpOnly verifier
cookie. Ensure hosting access logs do not retain callback query strings.

The server verifies every API request against Supabase Auth and checks the
returned ID against the allowlist. Mutating requests and WebSocket connections
also require the configured origin. The browser receives an HttpOnly, SameSite
Strict access-token cookie lasting at most one hour; expired sessions require
sign-in again. Sign-out clears this browser's cookie. It does not revoke a copied
access token or terminate an already-open WebSocket; those remain valid until
token expiry or the connection closes. MFA, session refresh, login rate limiting,
audit logs, and per-user data isolation are not implemented in this version.

For tests only, `CELERLITE_AUTH_REQUIRED=false` enables the legacy open demo.
Never use that setting on a publicly accessible deployment. Existing test suites
explicitly disable auth only in isolated fixtures.

## Recruiter preview

The public Render launcher keeps authentication enabled and exposes a separate
**View demo** session. `POST /auth/demo` requires the exact application Origin and
sets a two-hour HttpOnly cookie. Demo API reads are routed to
`CELERLITE_DEMO_DATABASE_URL`, which must be a separate database containing only
synthetic data. The demo cookie is stored in process memory; a service restart
invalidates active demo sessions. Demo sessions can read CRM endpoints from
that database; task, worker, metrics, and dead-letter endpoints are unavailable
because they use the private process broker. All demo writes are denied. Demo
sessions cannot open the private task WebSocket. Do not point the demo database
at the private database.

The Render launcher defaults the preview database to
`sqlite+aiosqlite:////tmp/celerlite_recruiter_demo.db` and sets
`CELERLITE_DEMO_READ_ONLY=true`. Override the URL only with another database that
contains synthetic records and is not the private database.

Authentication and persistence are separate concerns. Supabase Auth verifies
approved identities; the CRM database stores workspace records. If
`CELERLITE_DATABASE_URL`/`DATABASE_URL` is not configured, the service falls back
to local SQLite. Free Render instances do not provide a persistent disk, so CRM
records may be lost when the instance is replaced or restarted. Use a separately
configured durable database for records that must survive restarts; keep its URL
in Render environment variables, never in source control. Standard `postgres://`
and `postgresql://` URLs are normalized to the installed asyncpg driver.

Before deploying, configure and test an approved account and the environment on
the hosting provider. If Supabase settings are missing, private login fails
closed while the isolated synthetic demo remains available when its separate
database is initialized.
