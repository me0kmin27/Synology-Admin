# Chat MVP implementation evidence

- Base: main `aedad7bb7f8d7c1c8e9af85868c978ec6a4e0844` (refreshed clean main).
- Implemented code: `42b582f1443c69387c0ddd19fa84b9c2fc85fa34`.
- PR: `https://github.com/me0kmin27/Synology-Admin/pull/7`, draft, intentionally unmerged pending independent review.
- Code-head CI: pull_request run `38146299717`, push run `38146269056`;
  verify and postgres-races passed in each. `chat-ci.json` records the code head;
  `chat-ci-excerpt.txt` retains actual PostgreSQL/Chromium acceptance lines.
  Subsequent evidence-only head must be checked independently through `gh pr checks`.

## Vertical TDD

Each production slice followed an observed failure and then passing execution;
files with matching `chat-*-red.txt` / `chat-*-green.txt` preserve output.

| Slice | Observed RED | GREEN |
|---|---|---|
| Own conversation | 404 instead of 302 | Separate conversation, server-derived owner/tenant, repeat start |
| Message/event cursor | 404 instead of 201 | Plain text persisted and bounded chronological resume |
| Validation/retry | Empty body accepted (201 vs 400) | Size/nonce/cursor/uploads and idempotency conflict handling |
| Rate budget | 201 instead of 429 | DB read/write windows and retry headers |
| Browser vertical | No start button / UI | Two real cookie contexts receive automatically and reconnect |
| Privacy/link | Missing no-store on CSRF failure | Middleware-level no-store and account link |
| Missing object budget | 404 instead of 429 after budget exhausted | 404 returned without rolling back counter |
| Start upload | 302 instead of 400 | Attachment rejection before conversation creation |

Existing security behavior (fresh actor, tenant isolation, PostgreSQL policy locking)
was reused and regression-tested rather than intentionally weakened to make tests
red. PostgreSQL-only race acceptance was added and actually executed in CI, not
credited through SQLite skips. Final local suite: **79 tests passed**, deploy check,
30 disposable migrations, migration-drift check, real loopback HTTP smoke passed.
Real Chromium test passed locally and in CI with PostgreSQL. Browser harness's
async-ORM mistake and corrected run are retained; no async-safety bypass was used.

## PostgreSQL and browser assertions actually executed

CI executed **16 concurrency tests**, including **6 chat races**:
1. Concurrent duplicate nonce and last rate slot.
2. Reader/later sender cannot skip an uncommitted lower message ID.
3. Queued read refreshes actor after retirement.
4. Retirement waits for authorized read serialization.
5. Retirement waits for authorized send.
6. Queued send refreshes actor after retirement.

The dedicated Chromium test demonstrated automatic receiving without reload,
offline reconnect with no duplicates, reload replay, XSS payload rendered as text,
actual server-committed POST with deliberately dropped acknowledgement and safe
retry, and clearing/disabling the client after account invalidation. Response data
was never fabricated; all server state was disposable test data, not production.

## Review/rollout status

Self-review: no shell execution, eval/exec, unsafe deserialization, unsafe HTML sink,
raw SQL interpolation or hardcoded runtime secrets introduced. Fixture passwords
are local test-only identities. `git diff --check` and dependency check passed.
Independent approval is **not** claimed. No `[verified]` commit prefix, merge,
auto-merge, production deployment, NAS/RustDesk action or parent progress update.

Working near-real-time MVP is demonstrated; full live-chat stage and deployment
remain incomplete. See `docs/chat-mvp.md` for rate/retention/transport semantics,
shared-lock throughput limitation, browser history/outbox limits and production
gates. Retention and real deployment load acceptance remain open deliberately.
