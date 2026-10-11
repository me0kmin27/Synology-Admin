# Explicit LAN opt-in reconciliation — 2026-10-12 KST

The user explicitly approved LAN access after the original loopback review.
Repository `me0kmin27/Synology-Admin`, PR #13, now keeps loopback as its unset/empty
default and uses `INTERNAL_BIND_HOST` for one selected interface and the same
exact additional allowed Host. No wildcard is added by default. This trusted
operator variable is not a general-purpose address validator. LAN HTTP is not
production TLS: real administrator provisioning/login remains out of scope.

## Read-only live verification

- Current publication: **192.168.1.14:18080 -> web:8000**; not all interfaces.
- Allowed Hosts: `localhost,127.0.0.1,192.168.1.14`.
- Image revision remains `ed818d8abff546bdcc9ff3a7e79adf7bbc8643d3`.
- Image ID remains `sha256:220134dc32911fb5a22869b76dc8b29248cc0e6f2d929e0ba2956db1e0674060`.
- Both containers healthy; PostgreSQL `5432/tcp` has no host publication.
- From the separate agent host: health/landing 200, invalid Host 400,
  anonymous `/manage/` and `/mfa/enroll/` 302 to login.
- `.env` and `.mfa.env` remain mode 0600; no secrets printed or rewritten.
- NAS/RustDesk, accounts, router/NAT and TLS configuration were not changed
  by this reconciliation. Runtime LAN was preserved, not reverted or redeployed.

Raw evidence: `container-lan-runtime.txt`, `container-lan-http.json`,
`container-lan-local.txt`. Original loopback logs remain historical evidence.

## Exact current operator invocation and drift

The running release has a persisted literal Compose patch, with original
`compose.internal.json.before-lan` backup. Read-only JSON comparison verifies
that only web ports and `DJANGO_ALLOWED_HOSTS` differ from that backup.
It does NOT yet contain this PR's interpolation contract. The image is old code,
not the final PR head. No application code changed in this reconciliation.

To operate that current release without relabeling/rebuilding the older image:

```sh
cd /home/me0kmin27/synology-admin-internal/releases/ed818d8abff546bdcc9ff3a7e79adf7bbc8643d3
export SOURCE_REVISION=ed818d8abff546bdcc9ff3a7e79adf7bbc8643d3
export COMPOSE_FILE=compose.internal.json
export COMPOSE_ENV_FILES=../../.env,../../.mfa.env
# Current literal file already persists LAN selection. For a future parameterized
# release use the same approved selection on EVERY Compose invocation:
export INTERNAL_BIND_HOST=192.168.1.14
docker compose config --quiet
# Only if an explicitly authorized recreation is needed (not run in this review):
docker compose up -d --no-build --no-deps --wait --wait-timeout 120 web
```

Do not restore `.before-lan` automatically; that would revoke approved LAN access.
Do not build a new image, migrate, rotate secrets, or use `down -v` merely to
reconcile documentation. Future release deployment is a separate operation.

## Test and CI scope

Strict test-first contract change: the updated test initially failed because
`127.0.0.1:18080:8000` lacked the opt-in expression. After the two Compose changes,
all four container contract tests passed. Full local verification is recorded in
`container-lan-local.txt`. CI retains default loopback build/migration/restart
smoke, adds empty-variable fallback validation without logging rendered secrets,
and recreates web on the CI runner's private interface to check explicit bind,
health/landing 200, invalid Host 400 and anonymous management 302.

Final CI head and merge state must be read back from GitHub, not inferred from
this document's future commit hash. Public deployment, real operator MFA
recovery, least-privileged DB roles and backup/restore remain separate gates;
roadmap stage 7 and canonical progress are untouched.
