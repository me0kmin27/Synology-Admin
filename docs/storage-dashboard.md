# Approved-user storage dashboard

`GET /service/` uses only the bundled `NotConfiguredReader`. There is no network
call, DSM endpoint, credential lookup, collector, quota write, or deployment.
The page reports **NAS 미연결**, three unknown NAS metrics, no observation time
and no source. Portal `quota_bytes` / `storage_limit_bytes` are deliberately not
shown as NAS measurements. Remaining capacity is never calculated from policy.

## Authorization and privacy

- Approved active members with a tenant see their own account only.
- A group admin, or approved global admin with a tenant, additionally sees only
  their own group. Unassigned global admins do not bypass approval here.
- Ordinary members do not see group usage. Wider/global selection remains a user
  decision; query parameters cannot select accounts, tenants or accounting scope.
- The PostgreSQL policy lock covers fresh User, membership and session-epoch
  checks, the no-I/O read, and rendering. This serializes with portal revocation.
  SQLite is not evidence of concurrent revocation safety.
- Existing `/service/` middleware supplies `Cache-Control: no-store`, including
  redirects, denials and method errors. GET only; no new mutation/CSRF surface.
- Subject IDs are portal membership/tenant IDs with `portal-unmapped` scope,
  **not DSM identifiers or a decided NAS accounting contract**. Returned subject
  mismatches and invalid presentation values fail closed with a generic 503.

## Observation presentation

Domain values are autoescaped. Unknown is not zero; unlimited is not physical
free space. Historical values are marked old, with provenance and original
observation time. Until a real collection policy is approved, the presentation
uses a conservative zero-age freshness window (anything older than the render
clock is historical), not a claimed collection SLA. The shipped reader never
produces observations. A future adapter needs explicit mapping, accounting and
freshness decisions and must not introduce network I/O inside the policy lock.

## Verification

Strict vertical RED/GREEN cycles observed:
1. New dashboard assertion failed on the previous service placeholder, then passed.
2. Group admin/global-admin own-group assertions failed, then passed.
3. Cached inactive actor/session-epoch and POST assertions returned 200 before
   the fix; after fresh locked authorization / GET-only they returned 403 / 405.
4. A mismatched reader subject returned 200 before the guard, then 503.

Additional domain-fixture rendering tests cover unknown, unlimited, stale and
escaped provenance. These are **synthetic test inputs only**, not live NAS data.
Local `scripts/verify.py`: 102 tests passed, 32 real migration records, no pending
model changes, security checks and loopback health/landing/invalid-host passed.
Local `browser_tests.storage`: real Chromium login and HTTP with the actual
unconfigured reader passed for ordinary member/admin, scope forgery, no-store,
unknown metrics and absence of portal quotas. Initial browser harness lacked
STATIC_URL/MEDIA_URL; explicitly setting them like the existing chat harness
fixed the test server, without changing application behavior.

CI runs the full suite on SQLite and PostgreSQL, existing explicit PostgreSQL
race regressions, and both chat and storage real-browser tests. Verify the exact
PR head checks before merging; this document does not assert a deployment.

DSM customer-folder scope, broader group visibility, RustDesk and MFA remain
undecided and unchanged. No production/NAS/RustDesk writes were performed.
