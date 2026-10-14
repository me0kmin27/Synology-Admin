# authentik OIDC — optional authentication, local authorization

## Decision and implementation boundary

The user's authentik decision supersedes the proposed Synology SSO integration.
Use authentik at `sso.keiminem.com` for identity, **not** DSM passwords or NAS API
credentials. Existing portal accounts, passwords, emergency administrators,
Membership approvals, tenant roles, session revocation, local OTP and password
reauthentication remain unchanged. Historical evidence describes its original
revision; it is not evidence of this feature's deployment.

This change implements the client only. No authentik application was created,
no client secret was obtained, no production DB was migrated, and no deployment
was performed. The feature is OFF by default and local `/login/` always remains.

## Provider configuration to create later

Create a **separate** confidential OAuth2/OpenID Connect provider/application;
do not edit providers used by other applications.

| Setting | Required value |
|---|---|
| Application slug | `synology-admin` (proposed; verify availability) |
| Issuer mode | Each provider has a different issuer, based on application slug |
| Expected issuer | `https://sso.keiminem.com/application/o/synology-admin/` |
| Discovery | `https://sso.keiminem.com/application/o/synology-admin/.well-known/openid-configuration` |
| Strict authorization redirect URI | `https://test.keiminem.com/auth/oidc/callback/` |
| Client type / token endpoint authentication | Confidential / `client_secret_basic` |
| Flow | Authorization code + S256 PKCE |
| Signing key | RSA, RS256; no encryption key |
| Subject mode | Stable hashed user ID (do not use email or username) |
| Scopes | `openid profile email`; no `offline_access` |

The issuer above is an activation contract, **not a verified live provider**.
Read discovery after creating the application and verify its exact issuer,
endpoints and signing key before setting `OIDC_ENABLED=1`. The implementation
requires discovery/token/JWKS URLs on the same HTTPS authority as the issuer,
rejects HTTP redirects for backend requests, and allows only RS256 ID tokens.
Global issuer mode is intentionally not supported by this discovery convention.

Runtime environment (private secret store / owner-only environment file):

```dotenv
OIDC_ENABLED=0
OIDC_ISSUER=https://sso.keiminem.com/application/o/synology-admin/
OIDC_CLIENT_ID=<provider client ID>
OIDC_CLIENT_SECRET=<private provider client secret>
OIDC_REDIRECT_URI=https://test.keiminem.com/auth/oidc/callback/
```

`compose.internal.json` explicitly passes these variables, defaulting to off.
Use the existing HTTPS proxy overlay; do not enable with `DJANGO_LOCAL_HTTP=1`.
Insecure session/CSRF cookie settings disable SSO while keeping local login
available. Keep the canonical lowercase portal host, exact trusted proxy peer,
CSRF origin and secure cookies configured as described in `reverse-proxy.md`.
Never print interpolated Compose config or commit runtime environment files.

## Flow and security invariants

- Login page offers a separate CSRF-protected **POST** to `/auth/oidc/login/` only
  when the feature is configured. GET initiation is rejected. Rate limiting is
  per trusted transport-derived IP, without a shared empty-username bucket.
- Authlib constructs code/S256 requests and redeems codes with confidential
  client authentication and PKCE. Random state and nonce bind each transaction.
- `OIDCLoginAttempt` keeps PKCE/nonce/tenant selection server-side for five
  minutes. Only hashes of state and the random browser binding are stored.
  Configuration is also bound, so issuer/client/redirect/secret changes invalidate
  pending attempts. A conditional DB UPDATE atomically consumes state **before**
  remote I/O; failed exchanges cannot retry it. Consumed rows clear verifier and
  nonce. Expired rows are deleted during subsequent starts. Operators can purge
  expired rows periodically if login traffic stops; no tokens are stored there.
- Authlib verifies JWT signature with the issuer's JWKS and validates required
  issuer, subject, audience, expiration, issuance time, nonce and authorized party.
  Access/ID/refresh tokens are not persisted in DB or browser sessions. The portal
  does not request offline access or call userinfo with provider credentials.
- The immutable `(issuer, subject)` mapping has a DB uniqueness constraint and
  one local user. Email/username never links an existing account. Group, role,
  staff and superuser claims never grant local permissions.
- First login creates an active login identity with an **unusable password**,
  nonstaff/nonsuperuser, pending member. Tenant selection is optional and limited
  to signup-enabled tenants; selection is stored at initiation and rechecked on
  creation. Callback parameters cannot select a tenant. No selection means global
  administrator assignment is required before approval. Existing identities never
  move tenants because of a new selection or changed claims.
- Pending users can view their account but not protected services. Approved users
  retain existing local tenant authorization; suspended/inactive users are denied.
  Identity creation and login/session stamping use the existing PostgreSQL policy
  lock. Production callbacks require PostgreSQL; unsafe SQLite is test-only.
- Login uses Django's existing signal to stamp membership/session scope and clear
  old MFA verification. IdP MFA/group claims do not satisfy portal-local OTP.
  Existing local emergency admin login, bootstrap password change, OTP and
  password reauthentication are preserved; they do not depend on IdP availability.
- This phase does **not** add account linking, password provisioning for SSO-only
  administrators, SSO-based privileged reauthentication, IdP logout, back-channel
  logout or provider-side deprovisioning sync. Do not promote SSO-only users to
  operational administrator roles: unchanged password reauthentication cannot be
  satisfied by an unusable password. Use existing local administrator accounts.
  Portal logout clears the local session, not the authentik browser session.
- Keep proxy access logs from recording callback query strings (authorization
  code/state). Never enable HTTP transport debug logging. Application error bodies
  are generic; local variables in authentication views are marked sensitive.

## Validation and rollout gate

Local `scripts/verify.py` runs the full Django suite, security settings checks,
migrations/drift and loopback HTTP smoke. `tests/test_oidc.py` uses real RSA-signed
ID tokens and mocks HTTP transport only—not token validation. It covers principal
creation/reuse, email nonlinking, group non-elevation, pending/suspended access,
PKCE, CSRF, state/browser/configuration/expiry binding, replay, invalid signature,
issuer/audience/nonce/time, disabled feature, outage, tenant closure/injection,
malformed discovery, cookies and throttling. Red/green logs are in
`docs/evidence/authentik-*.txt`.

`concurrency.oidc_races.OIDCRaces` is added to the existing PostgreSQL CI job. It
forces both callback readers to observe unconsumed state before either update,
then verifies only one token redemption request occurs and secrets are cleared.
It refuses to run against SQLite (no skipped race acceptance).

Before activation: independent review of the final head, all CI checks including
PostgreSQL race/browser jobs, DB backup/migration, provider discovery verification,
and real authentik browser login/approval/retirement/local-admin-fallback checks.
Do not treat mock-transport tests as live provider interoperability evidence.
Rollback activation with `OIDC_ENABLED=0`; do not delete identities or change local
passwords. Existing authenticated sessions retain their ordinary local lifecycle.

## Official references checked for the client design

- authentik OAuth2 provider: `https://docs.goauthentik.io/add-secure-apps/providers/oauth2`
  — OIDC/PKCE, per-provider issuer and discovery conventions.
- authentik Matrix integration: `https://docs.goauthentik.io/integrations/services/matrix-synapse`
  — strict redirect, RSA signing key, no encryption, openid/profile/email.
- Authlib OAuth2Session: `https://docs.authlib.org/en/v1.6.10/client/oauth2.html`
  — S256 `code_verifier` on authorization and token requests, nonce and ID-token
  validation. The installed pinned Authlib 1.6.11 API was also inspected/exercised.

The generic provider docs establish configuration semantics, not the existence or
readiness of the proposed live application.
