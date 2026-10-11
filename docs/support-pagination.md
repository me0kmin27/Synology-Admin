# Support read pagination / independent-review handoff

Base: main `0688aa40e012b7b96fc91347ac03897a76fbaa6e` (chat PR #7).
This is one read-resource hardening PR, not completion of a roadmap stage.

## Findings and contract

- Ticket and conversation lists previously used `Paginator`: bounded output, but
  `COUNT(*)` and arbitrarily deep offsets, with page shifts when new records arrive.
  They now use **25-row, descending primary-key keyset pages**, `?before=<id>`.
  Only 26 rows are fetched (one lookahead); no total count or offset query.
  Ticket lists select only ID/title; conversation owners remain joined.
- This intentionally replaces numbered-list URLs. `page` on `/support/` or `/chat/`
  returns 400 with guidance rather than silently ignoring a bookmark. Navigation
  offers older records and an explicit latest-list link. Existing page-2 acceptance
  was updated to follow the returned cursor, not removed.
- Ticket detail previously loaded every reply and performed one author query per
  rendered reply. Both GET detail and invalid reply POST now fetch at most 26
  joined reply/author rows and render at most **25 replies**. `?after=<id>` proceeds
  in ascending primary-key/append order; timestamps are display metadata, not the
  cursor. This supersedes the old `created_at, pk` ordering description.
- Reply navigation links to the absolute local **detail** path, including when
  rendering form errors at the POST-only `/replies/` URL. The first-replies link
  resets the cursor; next advances only through displayed rows, never lookahead.
  Successful POST retains the existing redirect to first replies; on long threads,
  use next-reply navigation to reach the new reply. There is no live reply refresh.
- Cursors are unsigned ASCII decimal strings of 1–19 digits, bounded by signed
  bigint max. Malformed/empty/negative/non-ASCII/overflow values return 400, not
  500. Zero, gaps and beyond-end values are safe. Caller `limit` cannot enlarge
  pages. Cursor strings are not capabilities and do not carry tenant/user scope.
- Authorization is reapplied on **every** page: approved current-tenant owner,
  approved tenant admin, or active global superuser under the existing policy.
  Tenant moves, suspension, inactive users and stale session epochs still deny.
  `no-store`, template escaping and CSRF remain in force. Support reads retain
  point-in-time authorization; chat reads retain their policy lock and rate budget.
- New records cannot shift an already-returned cursor. Descending lists show new
  records on latest-list refresh, not while continuing older pages. Ascending reply
  traversal can include later committed arrivals; it is not a frozen snapshot.
  At the end, refresh the current page for later arrivals. Approved application
  writers serialize through the existing policy lock. Direct SQL/import writers
  that allocate IDs outside that contract are not covered by no-loss guarantees.
- Four reversible indexes align scope and cursor columns: ticket `(tenant,id)` and
  `(tenant,author,id)`, reply `(ticket,id)`, conversation `(tenant,id)`. Member
  conversation lookup already has a unique `(tenant,owner)` index; global lists
  use primary keys. These are normal AddIndex migrations, not an online migration
  claim; production-sized index lock/build cost needs deployment planning.

## Chat history inspection (no protocol change)

`/chat/<id>/events/` already uses ascending `after`, LIMIT 51 / 50 returned rows,
string IDs, and a `(conversation,id)` index, with no author hydration. No unbounded
history query or N+1 was found there. Added regression verifies query shape,
constant user reads, 107 existing messages plus an arrival between pages, complete
unique traversal and an empty stable terminal cursor. Browser still replays from
zero in bounded batches and retains its most recent 500 received DOM entries.
This PR does not add latest-first history, search/export or change polling rates.

## Strict TDD evidence

Each production change followed its own executed failing test:

| Evidence prefix under `docs/evidence/` | RED | GREEN |
| --- | --- | --- |
| `pagination-replies-*` | 53 replies rendered, expected 25 | bounded traversal, new arrival included once |
| `pagination-query-*` | GET 27 user reads vs 3; invalid POST renders 80 replies | one joined LIMIT 26 query for both paths |
| `pagination-cursor-*` | malformed cursor gives 500 or accepted 200 | strict 400 with no-store |
| `pagination-lists-*` | no deterministic next cursor on either list | no COUNT/OFFSET, stable pages after insert |
| `pagination-http-*` | form-error next link resolves to POST-only URL | real HTTP cookie/CSRF navigation + revoked-session denial |
| `pagination-index-*` | four scope/cursor indexes absent | real DB introspection finds all four |

Additional scope-matrix, empty/exact/gap/beyond-end and existing-chat tests are
regression acceptance, not falsely claimed as missing-feature RED cycles.
The HTTP test initially used nonexistent membership status `retired`; its CHECK
constraint error is preserved as `pagination-http-harness-error.txt`. The harness
was corrected to actual `suspended` + epoch invalidation and redirected-login
semantics; production authorization was not weakened to fit the test.

- `pagination-baseline.txt`: pre-change full local suite, 79 tests passed.
- `pagination-local.txt`: full local suite, **88 tests passed**, deploy checks,
  migration drift check, 32 applied migrations and actual loopback HTTP smoke.
  Includes real login/CSRF reply pagination, invalid-form navigation and revocation.
- `pagination-browser.txt`: real Chromium chat regression passed: two independent
  cookie contexts, automatic delivery, offline recovery, reload, XSS-as-text,
  server-committed/lost-ack idempotent retry and revoked-user UI clearing.
- `pagination-regression.txt`: focused pagination/HTTP acceptance passed.
- `pip check` and `git diff --check` passed locally. Local PostgreSQL/Docker binaries
  are unavailable; PostgreSQL verification must come from the existing CI job,
  which runs the full suite, explicit real multi-connection races and Chromium.
  Exact final head/check state is read back and handed to the parent separately.
- Implementer does not independently approve or merge this PR. Parent independent
  review and exact-head CI are required before its authorized merge decision.

## PostgreSQL / CI implementation-head readback

Implementation commit `7e32072fc6878a0ac3ef14472dc9f749497984a1`:
- Push run `38148285150` and PR run `38148319784`: both `verify` and
  `postgres-races` succeeded, with no skipped acceptance jobs.
- Both runs executed 88 tests on SQLite and 88 tests on PostgreSQL, then 16 real
  PostgreSQL race tests and one real Chromium/HTTP acceptance test on PostgreSQL.
- `pagination-ci-code.json` stores run/head/job readback; the matching
  `pagination-ci-<run>.txt` excerpts include the actual pagination, HTTP, database,
  race and browser results. No local PostgreSQL result is claimed.
- This following evidence-only commit has its own final head and CI. The parent
  receives that exact head after a fresh PR/check read; it is not self-embedded.
- Source scan found no shell/eval/unsafe-deserialization/SQL-formatting additions.
  Its only credential-literal match is the disposable HTTP test password. RED log
  trailing whitespace was normalized; actual assertions/results are preserved.

## Unchanged policy and remaining gates

**Retention is unresolved user policy.** No deletion, truncation, TTL, purge job,
auto-retention or storage-quota behavior was added. All stored ticket/reply/chat
history remains retained. A display/page cap is not a retention decision.

The query/result row bounds are not a global work, latency or traffic bound. Real
cardinality/query plans, index rollout time, lock contention, concurrency, slow
clients, proxy/request size limits and storage capacity remain production gates.
Support has no new per-user read limiter; chat retains its existing one. No NAS,
RustDesk, production deployment, user alerts, purchases or customer-data seeding.
`docs/progress.json`, stage totals and parent canonical progress are unchanged.
