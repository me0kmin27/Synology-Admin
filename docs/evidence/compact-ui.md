# Compact portal navigation and detail dialogs

## Scope

- Primary navigation: anonymous users see home/login/signup; pending users see their account; approved users see account/support/messages; administrators additionally see management. Storage is an account detail rather than a top-level destination. Visibility does not grant permission: existing view, session, MFA and mutation authorization remain authoritative.
- Removed inaccessible management links from ordinary/anonymous landing pages, member-only support creation and storage links from unassigned global administrators, and service links from pending accounts. Global administrators without a Membership now have a correct account identity/role display.
- Membership management now renders compact group/member rows. Authorized `GET /manage/?member=<id>` and `?group=<id>` provide standalone detail/edit forms and progressive modal destinations. Scoped querysets reject out-of-group/invalid IDs. Existing POST actions and CSRF/reauthentication contracts are retained.
- Native dialogs provide member/group details, account settings, storage details, support creation/detail, and OTP policy. Keyboard focus wraps, Escape/Close restore the opener, server validation errors remain in the dialog, and links retain real standalone URLs. Authentication/OTP enrollment and the live message conversation remain dedicated pages to preserve their existing security/polling lifecycle.
- During POST, Close/Escape/link navigation and repeated submissions are blocked. Supported browsers warn before departure. The lock persists through redirect navigation. Uncertain network/5xx outcomes warn against retry and block another dialog submission. This is **not server-side exactly-once processing**: browser force-close and existing backend idempotency limitations remain.
- Existing conversation ownership/group authorization, history and polling endpoints are unchanged. No SSO, NAS API, RustDesk web or attachment functionality is claimed. Their absence is an unsupported integration, not a broken portal link. The separate Rustdesk-Quicksupport repository is untouched.

## Verification artifacts

- `compact-nav-red.txt`, `compact-manage-red.txt`, `compact-modal-red.txt`, `compact-mutation-red.txt`, `compact-departure-red.txt`, `compact-identity-red.txt`: actual failing TDD runs before the relevant changes.
- `compact-final-tests.txt`: security checks, full Django suite, real disposable migrations, drift check and HTTP smoke.
- `compact-final-browser.txt`: actual Chromium/HTTP form, focus, Escape, validation, no-JavaScript fallback, deferred POST/redirect and responsive tests, plus existing portal/storage/MFA/QR regressions.
- `compact-route-matrix.json`: all registered URL patterns exercised as anonymous, user, group administrator and unassigned global administrator; all rendered local links on successful HTML pages followed. This is GET/method/authorization coverage, not permission to execute production mutations. Existing full suite covers CSRF, write authorization, cross-tenant denial and 1:1 isolation.
- `.runtime/compact-ui/member-dialog-{390,1440}.png` and `.runtime/ui-screenshots/`: disposable-fixture screenshots. Mobile modal reviewed visually for wrapping/scrolling/Close visibility. No production credentials/screenshots are collected.

## Review and rollout gates

Independent Codex CLI review found POST-close ambiguity and redirect/departure lifecycle gaps. They were reproduced with failing tests and addressed; final verdict is stored separately. Existing broad `page.locator('button')` browser selectors were scoped to `main` because a hidden shared dialog legitimately adds a Close button. Management form-scope tests now visit their standalone detail URLs. Existing chat JavaScript is unchanged.

CI, reviewed head, merge SHA and exact live image revision are separate external evidence. Do not infer deployed status from this document or a successful local test. No migrations, secret-file replacement, owner credential changes, or reporting cron changes are part of this patch.
