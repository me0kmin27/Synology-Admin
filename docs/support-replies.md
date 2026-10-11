# Ticket replies — first slice / independent review handoff

Base: merged PR #5, main `835d010c8be9fd5f5cf0767e559176f25c47fab1`.

## Scope
- Ticket detail renders chronological replies (`created_at`, then `pk`) and a CSRF POST form. `/support/<id>/replies/` is POST-only.
- Reuses ticket visibility: active approved owner in current company, approved company admin within own company, active global superuser. `is_staff` alone grants nothing. No company-wide member visibility or internal/private notes.
- Server selects the visible ticket and authenticated author; tenant is inherited solely through the ticket FK, not duplicated or accepted from input. Replies do not change the ticket author.
- Plain text, trimmed/nonempty, at most 10,000 characters, template autoescape; uploaded files explicitly rejected. No attachment storage, edit/delete, assignment, notification or state transitions.
- Reply and metadata-only `TicketAudit(action=replied)` commit atomically. PROTECT author/ticket FKs preserve application history. Audit remains ticket-level (no body or secret); no DB-owner tamper-resistance claim.
- Same PostgreSQL policy advisory lock as retirement, fresh User/membership/session epoch/scope inside lock. SQLite writes fail closed absent disposable development opt-in. Reads retain existing point-in-time authorization contract.
- Existing support privacy middleware covers replies including CSRF, errors and redirects (`no-store`). Body is marked sensitive for Django error reporting.

## TDD and evidence
- `replies-baseline.txt`: baseline verification succeeded.
- Vertical RED → GREEN evidence pairs: `replies-create-*` (404 → creation/audit), `replies-read-*` (missing reply/form → escaped chronological detail), `replies-validation-*` (empty accepted → form validation), `replies-upload-*` (302 → 400), `replies-sqlite-*` (302 → 503).
- Security matrix, rollback, stale in-flight actor/epoch, CSRF/method/no-store/history and HTTP tests are regression acceptance of the reused boundary, not falsely claimed new RED cycles.
- `replies-local.txt`: full verification, including real loopback HTTP cookies/login/CSRF ticket→reply→detail, migration consistency and deploy checks.
- `concurrency/reply_races.py`: explicit PostgreSQL-only CI acceptance. Two actual independent-connection schedules prove blocking with `pg_blocking_pids`: reply commits before waiting retirement; retirement commits before queued reply refreshes actor and returns 403 with no reply/audit. No sleeps-only evidence or SQLite skip credit.
- Independent parent review and exact-head remote CI verification remain merge gates. Implementer does not approve or merge own PR.

## Not complete
Ticket/livechat stage remains **incomplete**. Livechat, private notes, assignment, notifications, attachments, retention, rate/storage limits, MFA, email verification, NAS cap enforcement and production deployment remain separate gates. NAS, production, RustDesk and parent canonical progress are untouched.
