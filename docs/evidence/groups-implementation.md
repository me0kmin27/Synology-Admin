# Group policy implementation and verification

## Scope and verdict

Application head verified: `d60e3a7ac97008d3bc9a53bc51504a911592ec1c`, branch `feat/stage-3-membership`, Draft PR #3. No merge, deployment, production database or NAS calls were performed. Only `me0kmin27/Synology-Admin` changed; Rustdesk-Quicksupport and the parent's canonical progress file were untouched.

The requested **portal** group hierarchy, limits, quota reservations and safe retirement are implemented. Parent independent review of the exact final HEAD remains required before merge. MFA/secret custody/recovery and actual NAS enforcement remain separate deployment/stage-completion gates; they are not silently credited by this PR. The independent historical review is not an approval of these changes.

## Vertical RED → GREEN evidence

Each behavior slice was tested and its expected failure inspected before implementation; subsequent regression expansion tested existing behavior without pretending every additional assertion was a separate RED. Prefixes below refer to files in this directory.

| Slice | Observed RED | GREEN |
|---|---|---|
| Required selected-group signup; privilege fields ignored | `groups-signup-red.txt`: 302 instead of form error | `groups-signup-green.txt` |
| Hidden-group rejection | `groups-hidden-red.txt`: 302 instead of form error | `groups-hidden-green.txt` |
| Global-only bounded integer group limits and audit | `groups-limits-red.txt`: route 404 | `groups-limits-green.txt` |
| Active approved account count, admin included; reduction rejected | `groups-count-red.txt`: second admission 302 instead of 409 | `groups-count-green.txt` |
| Safe retirement and idempotence | `groups-retire-red.txt`: User stayed active | `groups-retire-green-corrected.txt` (restored-session regression fixed) |
| Self/last active manager protection | `groups-last-admin-red.txt`: last manager retired | `groups-last-admin-green.txt` |
| Global role appointment/replacement | `groups-role-red.txt`: route 404 | `groups-role-green.txt` |
| Group-scoped portal quota reservations / cap / reduction | `groups-quota-red.txt`: route 404 | `groups-quota-green.txt` |
| Scoped management forms and visible read-only manager limits | `groups-ui-red.txt`, `groups-manager-limits-red.txt`: absent controls/limits | corresponding `*-green.txt` |
| Actor revocation during already-authorized write (real PostgreSQL) | `groups-actor-race-red.txt`, run 38140431858 at `32b02bed605abbac26646a39ccd07ce02bacf650`: revoker committed while actor write paused | real lock contention verified in `groups-policy-races-green.txt`; final `groups-epoch-postgresql-green.txt` |
| SQLite management fails closed without explicit dev opt-in | `groups-sqlite-red.txt`: 302 instead of 503 | `groups-lock-local-green-corrected.txt` |
| Group manager cannot retire a superuser with Membership | `groups-root-protection-red.txt`: 302 instead of 403 | `groups-lock-local-green-corrected.txt` |
| Retire pending/legacy suspended identities | `groups-pending-retire-red.txt`: 409 instead of 302 | `groups-migration-green.txt` |
| Existing active capacity survives migration, without account deletion | `groups-migration-red.txt`: zero instead of two | `groups-migration-green.txt` |
| Concurrent successful password check cannot publish a retired session (real PostgreSQL) | `groups-login-race-red.txt`, run 38141128011 at `e3a7869997c1b5a7a7162dddbe76710e95d26794`: authenticated session reappeared | `groups-login-race-green.txt`; final `groups-epoch-postgresql-green.txt` |
| An already-inactive historical admin is not the last active admin | `groups-inactive-admin-red.txt`: 409 instead of 302 | `groups-final-local.txt` |
| In-flight obsolete session epoch cannot mutate | `groups-session-epoch-red.txt`: 302 instead of 403 | `groups-session-epoch-green.txt` |

Failed attempted GREEN runs are retained, not relabeled as passes: `groups-retire-green.txt` and `groups-lock-local-green.txt`. The latter exposed a direct-view test expecting a forbidden response rather than an uncaught PermissionDenied; the centralized guard now returns 403. Intermediate draft commits intentionally exposed failing PostgreSQL regressions before their fixes.

## Final executed checks

- Local `.venv/bin/python scripts/verify.py`: **47 tests passed**, 25 applied migrations, no migration drift, deploy check clean, real loopback landing 200 / health 200 / invalid Host 400. Real HTTP cookie/CSRF form flow also passed. `groups-session-epoch-green.txt`.
- PostgreSQL 17 disposable CI service: **same 47 tests passed + 7 dedicated race tests passed**; 25 migrations and the same real HTTP smoke passed. `groups-epoch-postgresql-green.txt`. The 47 tests are repeated across backends, not 94 distinct tests.
- Race suite covers actor revocation, last admission slot, mutual manager retirement, concurrent manager demotion, concurrent quota allocation, limit reduction versus admission, and concurrent login versus retirement. Independent connections + Events + `pg_blocking_pids` verify actual overlap. PostgreSQL-only suite fails on another backend; no skip/expectedFailure counts as acceptance. Mock hooks pause real authentication/authorization rather than supply fabricated outcomes.
- Rollback regression injects an audit-write failure and proves membership status/count rollback before a successful retry. CSRF/method and exception-report redaction coverage includes new management routes.
- Exact application HEAD CI: push 38142000602 and PR 38142003598, all four checks SUCCESS; metadata `groups-epoch-ci.json`. A later documentation-only HEAD must still have its own CI read back in the handoff.
- `pip check`: no broken requirements. `git diff --check`: clean. Static added-line self scan: no shell/eval, unsafe deserialization or interpolated SQL patterns; `groups-static-review.json`. This is **not independent reviewer approval**.

One CI run hit an existing fixed-window throttle test at the real 13:00 UTC boundary. The same 200/429 mismatch was reproduced deterministically with a controlled window rollover (`groups-throttle-clock-reproduction.txt`). The within-window test now freezes time; throttle production policy was not changed. Original failure is preserved in `groups-ci-sqlite-failure.txt`.

## Policy and deployment boundaries

`../membership-group-acceptance.md` defines active account count, replacement order and reservation semantics. PostgreSQL READ COMMITTED + DB sessions and a shared transaction advisory lock are required. Guarded writes refresh actor activity/password/session epoch and then scope permissions after acquiring the lock. Role/status/quota/limit/legacy assignment/link writes share this contract. Session publication rechecks active state and persists under the same lock; retirement can therefore delete published sessions and cannot be bypassed by an earlier password check. All other DB writers/CLI must honor the same contract; arbitrary direct SQL is not covered.

Global serialization intentionally trades throughput for a simple consistent order. Operational load, lock-timeout/failure recovery, pagination, session-scan cost, backup recovery and tamper-proof audit retention remain unverified. New groups start at zero limits; migration 0010 preserves existing active approved capacity. Retired quota reservations and NAS bindings remain retained. No NAS quota/usage/deletion success is claimed.

## Official references inspected

- Django 5.2 QuerySet `select_for_update`: SQLite does not provide this lock; real locking tests should use TransactionTestCase. https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update
- PostgreSQL explicit locking/advisory locks: transaction-level advisory locks release at transaction end and can be inspected through lock views. https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS

Existing DSM evidence and official sources were preserved; no NAS model or MFA secret policy was invented.
