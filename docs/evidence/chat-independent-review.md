# PR #7 independent scoped review

Reviewed repository: `me0kmin27/Synology-Admin`.
Reviewed head: `cbdc2f302d28a9550f941162165c337ace910ecf`.
Implementation commit: `42b582f1443c69387c0ddd19fa84b9c2fc85fa34`.

## Verdict

**PASS for the scoped near-real-time short-polling MVP; no blocking security or
correctness defect found.** This is an independent reviewer execution, not the
implementation agent's self-review. No production code correction was necessary.
No claim of WebSocket delivery, production readiness, or whole-roadmap completion.
The final evidence-only commit still requires its own green CI and head-guarded
merge; this document does not claim a future merge has already happened.

## Reviewed boundaries

- Read all chat views, forms, models/migrations, templates, browser/race tests,
  authorization/session/policy-lock dependencies and changed configuration.
- All chat data reads and sends rehydrate actor, membership status, session epoch,
  role and tenant under the PostgreSQL policy transaction lock. Query parameters
  cannot widen tenant/owner scope. Staff alone has no privilege; the existing
  active global-superuser exception remains explicit. Denials do not serialize
  conversation contents. Policy mutation and chat locking share the same key.
- Missing/out-of-scope IDs, malformed messages/cursors and nonce conflicts return
  responses inside the transaction rather than raising a rollback-causing 404.
  Read/write counters persist on these paths; one row per user bounds limiter
  metadata. Authentication failures and infrastructure/transaction failures are
  not represented as successfully charged requests. Edge protection is separate.
- The shared lock orders supported message allocation/commit, preventing the
  receive cursor from skipping a later-visible lower ID. ID strings/BigInt avoid
  JavaScript number precision loss; lookahead does not advance the returned cursor.
  The nonce uniqueness boundary includes conversation and author. Same-payload
  retries return the original ID; conflicts do not silently overwrite a message.
- CSRF middleware protects POST. Plain text uses template escaping/textContent;
  no unsafe HTML sink, shell execution, eval/exec, interpolated SQL or hardcoded
  runtime secret found in added application/configuration lines. Test passwords
  are disposable fixture identities. Chat middleware sets no-store on failures.
- Browser polling is non-overlapping, has timeout/backoff, and does not advance
  reception after a send. Authorization denial clears received text and disables
  sending; stopped-state checks prevent a late poll from repopulating the UI.
  Lost-ack draft/nonce are only in memory, as documented, not durable offline state.

## Independently executed evidence

- `.venv/bin/python scripts/verify.py`: **79 tests passed**, deployment checks,
  **30 applied disposable migrations**, no migration drift, real loopback smoke
  (landing/health 200; invalid Host 400). `chat-independent-local.txt`.
- Real Chromium `manage.py test browser_tests.chat -v 2`: **1 test passed** with
  two independent authenticated contexts. Automatic receipt, offline resume,
  reload replay, XSS rendered as text, actual committed POST with its response
  dropped, idempotent retry, no duplicate messages, invalidated-account UI clearing.
  `chat-independent-browser.txt`. This local run uses disposable SQLite and is
  explicitly not PostgreSQL race evidence.
- Independently fetched and inspected GitHub run `38146634248` on the reviewed
  head: PostgreSQL job actually executed 79 tests, **16 race tests including all
  6 chat races**, and the real Chromium test. `chat-independent-ci-excerpt.txt`.
  Both verify and postgres-races were successful in each of runs `38146634248`
  and `38146631121`; these are four check instances, not four different suites.
- `git diff --check` and `.venv/bin/python -m pip check` passed.

## Separate deployment gates, not hidden merge requirements

The global advisory lock serializes every poll, including other policy operations.
Per-user rate limits do not establish aggregate capacity, lock-wait/pool bounds or
load SLOs. Fresh history replay is bounded per request, not constant-time catch-up.
Retention is not bounded and no purge is enabled. Approved retention/privacy,
backup/restore, TLS/proxy/body limits, deployment topology and real capacity/SLO
acceptance remain required before production. Out-of-band database writes must
honor the shared lock contract. Previously delivered/offline content cannot be
clawed back. These limits are disclosed in `docs/chat-mvp.md` and are not a promise
of production scale. No production, NAS or RustDesk access/change was performed;
parent canonical progress files remain untouched.

The earlier implementation evidence's pending-review status is historical and is
superseded by this independent scoped verdict. Final-head CI and merged-state
readback are recorded remotely, separately from this document's reviewed-code SHA.
