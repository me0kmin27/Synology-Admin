# Chat MVP — working near-real-time vertical slice, not full production chat

## Decision and official sources

Reviewed official primary documentation on 2026-10-11:

- Django 5.2 `StreamingHttpResponse`: `https://docs.djangoproject.com/en/5.2/ref/request-response/#django.http.StreamingHttpResponse`
- Django 5.2 async stack/transactions: `https://docs.djangoproject.com/en/5.2/topics/async/`
- MDN recursive polling guidance: `https://developer.mozilla.org/en-US/docs/Web/API/Window/setInterval#ensure_that_execution_duration_is_shorter_than_interval_frequency`

Django documents that WSGI streaming occupies a worker for the response lifetime;
ASGI can serve long-lived SSE, but synchronous middleware removes the fully async
stack's advantages and transactional work must remain synchronous. This repository
has only `config/wsgi.py`, synchronous custom auth/throttle middleware and a shared
transactional policy lock. No approved ASGI server, proxy buffering/timeouts, async
middleware conversion or connection budget exists. Consequently this small first
slice uses **short polling, explicitly labelled 준실시간 / near-real-time**, not SSE,
WebSocket or ticket replies renamed as chat. SSE is a possible later transport once
those deployment assumptions have been verified; it is not silently provisioned.
MDN recommends recursive `setTimeout` rather than overlapping interval requests.
The actual browser uses that pattern; this decision is an engineering inference
from the current stack, not a claim that Django cannot implement SSE.

## Implemented contract

- Distinct `chat.Conversation`, `chat.Message`, and bounded `chat.RateWindow` tables.
  No ticket dependency or copied ticket content. One conversation per owner/tenant;
  creation derives both from the authenticated approved membership. An administrator
  replies to an existing customer conversation, not on behalf of another owner.
- `/chat/`: GET lists 25 scoped conversations per ID-keyset page (`before`; see
  `support-pagination.md`); POST starts/reuses the
  caller's conversation. `/chat/<id>/`: GET browser UI.
  `/chat/<id>/events/`: GET cursor page; POST plain-text message.
- Approved member: own conversations within current tenant only. Approved group
  admin: current tenant's conversations. Active global superuser: all conversations
  (same existing support policy, including the no-membership superuser exception).
  Staff alone grants no access. Superusers without membership cannot start their
  own customer conversation. IDs/query-string fields never widen scope.
- Every application read/write obtains the existing PostgreSQL policy transaction
  lock and reloads user/status/session epoch before serializing data or writing.
  Retirement serializes with chat operations; an operation already authorized and
  serialized before retirement may finish delivering over the network afterwards.
  Requests queued behind retirement recheck and fail. Already delivered content
  cannot be clawed back. Online UI clears on its next auth-denied poll; an offline
  browser can retain previously delivered text until it reconnects.
- CSRF-protected POST; 1–2000-character stripped nonblank text; UUID send nonce;
  attachments rejected on both creation and send. No HTML/Markdown rendering,
  editing/deletion endpoints, presence, typing, read receipts or fabricated status.
  User data uses template autoescaping or DOM `textContent`. Chat responses,
  including middleware errors/redirects, carry `Cache-Control: no-store`.
- POST returns 201 + string message ID; exact same `(conversation, author, nonce)`
  retry returns 200 and the same ID; conflicting body returns 409. Lost HTTP ack
  leaves the browser draft read-only and preserves the nonce for manual retry.
  Reloading before retry loses that in-memory draft/nonce: there is no durable
  offline outbox and no cross-reload exactly-once claim.
- GET `after` is an unsigned ASCII integer string within signed bigint range,
  default `0`; response has `messages`, string `cursor`, and `has_more`. At most
  50 chronological ID-ordered messages, selected with a `(conversation,id)` index
  and a 51-row lookahead. Cursor advances only through the returned page. Empty
  page retains cursor; IDs are strings to avoid JS numeric precision loss.
- All supported message writes share the policy lock, so sequence allocation and
  commit visibility are ordered. Direct database message writes/imports must use
  this same lock (including any future background jobs); otherwise cursor no-loss
  semantics are not guaranteed. No timestamp-only cursor and no offset pagination
  for messages. Rolled-back sequence gaps are harmless. No delete API is exposed.
- Browser starts at cursor 0, fetches automatically, and resumes the last applied
  cursor after network failure without reloading. A successful send does not advance
  the receive cursor. BigInt high-water deduplication avoids duplicate DOM entries.
  UI retains only the last 500 received entries; historical messages remain in DB.
  A fresh page replays from the start in 50-message batches, so large histories take
  time to catch up. No history export/search/older-page navigation in this MVP.

## Load bounds and operation gates

- One outstanding poll per page; normally next request 3 seconds after completion,
  including backlog pages. 10-second fetch timeout; failures back off 6–60 seconds;
  429 respects at least the server retry delay. No immediate catch-up loops.
- Per authenticated user across sessions/conversations: 60 read requests and 20
  write attempts per fixed 60-second window. Reads include list/detail. Invalid
  message/cursor and missing/out-of-scope conversation attempts consume the budget.
  Creation and idempotent retries also consume write attempts. Separate read/write
  lanes prevent sends from using the receive budget. Fixed windows permit boundary
  bursts; this is not a sliding-window or global DDoS limiter.
- One rate row per user (no attempt-row growth), serialized across PostgreSQL
  workers by the policy lock. Application traffic is bounded per user, not globally:
  auth failures and unsupported HTTP methods still need edge/proxy protection.
- Each API response is bounded by 50 messages of at most 2000 characters. Message
  storage is **not retention-bounded**: no automatic deletion is enabled. All history
  is retained until an approved retention/privacy/legal-hold design and purge/backup
  procedure exists. Operational retention acceptance remains OPEN.
- PostgreSQL READ COMMITTED is required. SQLite fails closed (503) unless the
  explicit unsafe development opt-in is set. SQLite browser success does not
  establish race safety. Global policy-lock contention and DB work per poll mean
  this is a low-volume MVP, not a scale claim. Before production, test real tenant
  counts, proxy/TLS/body limits, DB pool/lock-wait budgets, multiple tabs and slow
  clients; establish p95 latency/concurrency targets and metrics. No production
  throughput or SLO has been measured.
- Remaining gates: independent review, PostgreSQL CI race/browser acceptance,
  approved retention policy, backup/restore, deployment topology and capacity/load
  acceptance. This PR does not complete the roadmap's full live-chat stage.
  No production deployment, NAS/RustDesk changes, purchases or data seeding.

## Reproducible verification

```sh
.venv/bin/python scripts/verify.py
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
# Set a disposable DJANGO_SECRET_KEY first; never point tests at production.
.venv/bin/python manage.py test browser_tests.chat -v 2
# With disposable PostgreSQL settings (see CI):
.venv/bin/python manage.py test concurrency.chat_races.ChatRaces -v 2
```

`browser_tests.chat` uses a real loopback Django HTTP server and two independent
Chromium cookie contexts, actual login/CSRF, automatic reception without reload,
offline reconnect, full reload replay, XSS-as-text, a real server-committed send
whose HTTP response is deliberately dropped, idempotent retry, and UI clearing on
account invalidation. It neither synthesizes API responses nor skips absent browser
executables. CI installs Chromium and executes it against PostgreSQL explicitly.

Incremental RED/GREEN records and final local output live under
`docs/evidence/chat-*`. Initial browser harness extension hit Django's async-safety
guard because Playwright's sync context owns an event loop; moving only the test's
ORM verification to a worker fixed this without `DJANGO_ALLOW_ASYNC_UNSAFE`.
The original failure is retained as `chat-browser-harness-error.txt`.

Review/CI are verified against the final PR head separately; this document does
not embed its own impossible-to-know final commit hash. `docs/progress.json` and
parent canonical progress were deliberately left unchanged.
