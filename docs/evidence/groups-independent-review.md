# Independent PR #3 security/correctness review

Reviewed application/documentation input: `7b8beb4eefef42c67ceafe92a73aa67222aa12d4`, `me0kmin27/Synology-Admin`, branch `feat/stage-3-membership`. Base refreshed from origin/main (`702e163`). This is the delegated independent review, not the implementer's self-review.

## Verdict

No merge-blocking defect found in the bounded portal-policy scope. **Code review passed; merge-ready after the documentation-only review commit's exact remote HEAD CI is green.** Final SHA/run identities are returned directly to the parent after push and read-back. Parent alone may merge; this review does not merge or make the draft ready automatically. The old PR body predates the group implementation and must not be mistaken for current acceptance evidence.

Stage 3 remains in progress. Administrator MFA, secret custody/registration/recovery, email verification/password recovery, actual NAS enforcement and operational deployment validation are NOT approved or credited. These are deployment/stage-completion blockers, not defects that prevent this incremental portal PR from merging.

## Independently exercised evidence

- Ran `.venv/bin/python scripts/verify.py` against a disposable local SQLite database: **47 tests passed**, including the migration upgrade fixture, real loopback cookie/CSRF forms and security boundaries; 25 migrations applied, no migration drift, deploy checks clean, HTTP landing/health 200 and invalid Host 400. Raw output: `groups-independent-local.txt`.
- `.venv/bin/python -m pip check`: no broken requirements. `git diff --check`: clean.
- Independently fetched exact-head CI checks: push `38142288296` and PR `38142292185`, four successful jobs. Downloaded and inspected push PostgreSQL job `114478441408`: **47 tests + 7 PostgreSQL race tests**, 25 migrations and HTTP smoke passed. This is remote execution evidence, not a claim of local PostgreSQL execution. No postgres/initdb/docker executable was found on PATH; the review documentation push will exercise both backends again in isolated CI, with its final checks read back before handoff.
- Inspected all new production policy modules, changed views/middleware/throttle/forms/models/routes/templates, migrations 0007–0010 and their upgrade test, 7 race tests, privacy/CSRF/cross-tenant/rollback regressions and acceptance documents. Added-Python-line scan found no shell/eval/pickle execution, interpolated execute SQL, private-key/GitHub/AWS token patterns. Reviewed credential-looking fixtures as disposable test values, not production credentials. This limited scan does not establish absence of all conceivable secrets.

## Security/correctness findings

- **Authorization/locking:** all seven management writers enter the common advisory transaction lock before refreshing the acting User, checking active state, password and session epoch, and evaluating permissions. Actor revoke, role changes and subject operations share the lock order. SQLite management fails closed unless explicitly opted into disposable development. Out-of-band SQL/CLI must honor the documented contract.
- **Real overlap:** independent worker connections and PostgreSQL blocking-PID checks establish contention, not merely sequential successful requests. Cases cover actor revocation, last admission slot, mutual retirement, manager demotion, competing quota assignments and limit reduction/admission. The login race pauses after a real successful password check, retires the user, and confirms no authenticated session publication.
- **Session retirement:** publication takes the policy lock, rechecks active state and persists the DB session under that lock. Retirement disables login, increments epoch and deletes DB sessions transactionally. Restored and in-flight obsolete session tests passed. No guarantee is made to retract already-sent read responses.
- **Limits:** account count includes active approved managers/members, not pending/retired users. Quotas aggregate all reservations, retaining retired allocations by explicit policy. Reductions below count/reservations and unsigned integer overflow/negative/invalid input fail. Audit failure rolls back state. These are portal reservations, not NAS quotas.
- **Protection/isolation:** scoped querysets, global-only roles/limits, explicit self/root retirement protection and last-active-manager guard are consistent with acceptance; tenant forgery does not move a membership. CSRF and POST-only tests cover every write. Quota self-allocation is permitted within the group cap, not a privilege escalation.
- **Upgrade compatibility:** new schema uses additive fields/tables and historical-model data migration. Existing active approved capacity is preserved; pending/inactive rows remain. Migration test exercises upgrade with existing rows; production-sized/online migrations and downgrade operations remain unverified.
- **Privacy:** custom sensitive POST markers and allowlisted audit data are tested. No new external NAS calls, destructive file deletion or embedded operational credentials found. APM/proxy/local-variable logging, immutable audit retention, global-lock throughput, pagination and session-scan scale remain explicit operational work, not silently certified.

## Changes and boundaries

Review artifacts and repository-local progress only; no production-code correction was necessary, so no fabricated RED/GREEN fix cycle is claimed. No NAS, RustDesk, deployment, merge, public review/comment, or parent canonical progress-file modification performed. Final documentation commit CI must pass before the parent's merge decision.
