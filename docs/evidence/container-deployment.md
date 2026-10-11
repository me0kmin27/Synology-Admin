# Internal deployment evidence — 2026-10-12 KST

## Exact scope and identities

- Repository: `me0kmin27/Synology-Admin`; PR #13; branch `feat/loopback-docker`.
- Initial base: `801d3fe77f60efd079c6eae483fb2de72a7463de`.
- Integrated latest main/MFA merge: `1e60ca457ed858ec63dfaefd99a0355f47e68733`.
- **Deployed code SHA: `ed818d8abff546bdcc9ff3a7e79adf7bbc8643d3`**, not a main release.
- Server: `me0kmin27@192.168.1.14:22`, Debian 13, Docker 29.9.0,
  Compose 5.6.0. Preflight: no containers; only SSH listening; 3921 MiB RAM,
  88 GiB disk available. User-authorized separate deployment host only.
- Active release: `/home/me0kmin27/synology-admin-internal/releases/ed818d8abff546bdcc9ff3a7e79adf7bbc8643d3`.
- Image: `synology-admin-internal:ed818d8abff546bdcc9ff3a7e79adf7bbc8643d3`.
- Docker image ID: `sha256:220134dc32911fb5a22869b76dc8b29248cc0e6f2d929e0ba2956db1e0674060`.
- Containers: `synology-admin-internal-web-1`, `synology-admin-internal-db-1`.
- Named volume: `synology-admin-internal_postgres_data` (retained).

## Observed acceptance

`container-mfa-build.txt` and `container-mfa-runtime.txt` contain actual output:
Python 3.14.8, Gunicorn 26.2.0, pinned OTP/cryptography dependencies installed;
33 migrations applied, including `membership.0011_adminotpdevice`;
`migrate --check` passes. Users, tenants and OTP devices all remain zero.

- HTTP landing/login 200; health 200 with database ok and NAS not configured.
- Anonymous account/manage/MFA enrollment return 302; invalid Host returns 400.
- MFA middleware loaded; remote independent key encrypt/decrypt roundtrip passes.
  This does not claim a real administrator enrollment or recovery exercise.
- App UID/GID 10001; read-only root; no `.env` or `.mfa.env` in image.
- Only `127.0.0.1:18080` is published; database has no host port.
- A connection from the agent host to `192.168.1.14:18080` raised
  `ConnectionRefusedError` after the final deployment.
- Both containers healthy after restart. Migration records byte-identical before
  and after restart; existing Django/DB and independent MFA secret files unchanged.
- Remote `.env` and `.mfa.env` mode 0600, deployment root 0700. Actual secrets
  generated only on the remote host; no key, admin password, or account seeded.

`container-mfa-local.txt` is the real merged-main local foundation verification.
Container CI exercises image build, PostgreSQL migration, loopback HTTP and restart
persistence; final-head CI must be read from PR #13 rather than this document's
own future commit hash. Independent review is handed to the parent, not claimed.

## Earlier failures and fixes (preserved honestly)

The first image built and was internally healthy but its internal-only network
silently omitted the host port mapping: actual curl and CI failed with exit 7.
A normal frontend bridge now serves the loopback mapping; PostgreSQL stays on the
internal network. App egress is possible, so do not claim an egress firewall.
Gunicorn 26's default control socket attempted a read-only home write; disabling
that optional control socket removed the error. Contract failures were observed
before each fix and subsequently passed. Initial archive transfer had a local
HOME quoting error and wrote nothing; absolute remote paths resolved it.

`container-build.txt`, `container-runtime.txt`, `container-database-outage.txt`
refer to pre-MFA code `8127019dfa70cac9d92c393a78582b8eb2044f3c`, retained as
historical evidence, not final MFA acceptance. That database outage probe returned
503 while PostgreSQL was stopped and recovered to 200 after restarting it.

## Rollback and remaining gates

Old releases/images remain; no volume deletion/prune was performed. Initial
pre-MFA release is **not a security-approved rollback target** now that MFA has
been integrated. The safe bounded rollback is to stop web (or both containers),
retain database/secrets/images, then review schema and security compatibility
before selecting any older image. Off-host backup/restore is not verified.

Public/domain/TLS/proxy deployment remains prohibited. Real administrator setup,
MFA operational enrollment/recovery, separate least-privileged PostgreSQL roles
(the prototype uses its bootstrap owner), image digest pinning and backup drills
remain release gates. No NAS/RustDesk changes or access; canonical progress
untouched; roadmap stage 7 is not complete.
