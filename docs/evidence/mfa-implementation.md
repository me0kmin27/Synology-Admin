# Administrator OTP implementation evidence

Base: 801d3fe77f60efd079c6eae483fb2de72a7463de. Isolated feat/admin-otp worktree.

- Enrollment RED: mfa-enroll-red.txt (HTTP 404 != 403).
- Enrollment GREEN: mfa-enroll-green.txt; regression: mfa-enroll-regression.txt.
- Confirmation/replay RED: mfa-confirm-red.txt (HTTP 404 != 302).
- Confirmation/replay GREEN: mfa-confirm-green.txt.
- Official sources read directly in browser on 2026-10-12: django-otp 1.7.4
  extend.html and _modules/django_otp/plugins/otp_totp/models.html on
  django-otp-official.readthedocs.io; cryptography.io/en/latest/fernet/ (50.0.2).
  The available web_extract backend rejected extraction (search-only); browser
  reading succeeded. No secondary technical source or invented crypto used.
- No production keys, NAS/RustDesk access, purchases, or deployment.
- Initial incremental commit fe156df captured the first two passing slices.
- Subsequent bounded-enrollment, central-route gate, session invalidation,
  account/IP throttle, pre-view privacy and inner mutation-gate RED/GREEN pairs
  are persisted as mfa-bound/gate/session/rate/privacy/inner-gate-*.txt.
- Exact code candidate 9097a5223ab16c7e78e4ec9b6383e597f385a313:
  local 113 tests + migrations/deploy checks/real HTTP smoke passed;
  Chromium MFA/chat/storage 3 tests passed. No local PostgreSQL binary found;
  PostgreSQL acceptance uses the real PostgreSQL 17 GitHub Actions service.
- First CI 38180765812: SQLite/full PostgreSQL regression passed; 19 race tests
  executed, including both MFA races passing. One legacy chat GET retirement
  assertion expected 403, but the new central boundary flushes stale sessions
  and redirects GET to login (302). Updated expectation and additionally asserts
  authentication removal, without relaxing POST denial or no-message assertions.
  Raw first failure: mfa-ci-first-failure.txt.
- Added queued device/global-role revocation race with pg_blocking_pids evidence.
  Final CI must be checked against the final head, not the earlier candidate.
- Independent reviewer/parent owns merge decision. Implementer never merges.
  Recovery and full authentication-stage completion are NOT claimed.
