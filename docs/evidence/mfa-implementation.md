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
- This incremental commit is NOT a completed security slice. Central gate,
  bounded enrollment/session checks and expanded acceptance follow before PR.
