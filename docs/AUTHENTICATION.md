# Private workspace sign-in

CelerLite requires Supabase email/password authentication by default. Its CRM and
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

The server verifies every API request against Supabase Auth and checks the
returned ID against the allowlist. Mutating requests and WebSocket connections
also require the configured origin. The browser receives an HttpOnly, SameSite
Strict access-token cookie lasting at most one hour; expired sessions require
sign-in again. Sign-out clears this browser's cookie. It does not revoke a copied
access token or terminate an already-open WebSocket; those remain valid until
token expiry or the connection closes. MFA, session refresh, audit logs, request
throttling, and per-user data isolation are not implemented in this version.

For tests only, `CELERLITE_AUTH_REQUIRED=false` enables the legacy open demo.
Never use that setting on a publicly accessible deployment. Existing test suites
explicitly disable auth only in their isolated fixtures. The authentication suite
checks fail-closed configuration, allowlisted and confirmed identities, origin
checks, HttpOnly cookies, protected API requests, and unauthenticated WebSockets.

Before deploying, configure and test an approved account and the environment on
the hosting provider. Deploying this code without configuration will lock the
workspace until the environment is corrected.
