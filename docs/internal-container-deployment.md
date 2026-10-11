# Internal-only Docker validation (not a production release)

Scope: the separately authorized Debian deployment server, never the NAS or
RustDesk host. HTTP defaults to `127.0.0.1:18080`; explicit operator opt-in may
bind one approved private LAN IPv4 address. No database host
port, domain, TLS termination, public firewall rule, administrator seed, or NAS
credential is created. Main merge `1e60ca457ed858ec63dfaefd99a0355f47e68733`
(PR #12 administrator MFA) is integrated; no gate is disabled.

## Definitions and safety boundary

- Python 3.14 follows `.python-version`; Gunicorn 26.2.0 is pinned separately from
  base app dependencies. The app is UID/GID 10001, read-only root filesystem,
  dropped capabilities, no-new-privileges, bounded temporary storage.
- PostgreSQL 17 uses a persistent named volume, 768 MiB memory, 128 MiB shared
  buffers and 40 connections. Web gets 512 MiB; both have one CPU and 128 PIDs.
- PostgreSQL has only a Docker `internal` bridge. The app additionally needs a
  normal frontend bridge for Docker to create its loopback publication; an
  internal-only endpoint silently omitted that mapping in the first real smoke.
  This permits app egress: it is not an egress firewall. No NAS integration or
  credential is configured. Host/docker administrators can access containers and
  environment; secrets are not protected from Docker administrators.
- `DJANGO_LOCAL_HTTP=1` deliberately disables HTTPS redirect/secure cookies for
  loopback or explicitly approved trusted-LAN validation. LAN HTTP is unencrypted;
  never enter real operator credentials over it. **Do not use this compose file for production.**
- No proxy is trusted: Gunicorn `forwarded_allow_ips=''` and
  `secure_scheme_headers={}`; Django's existing settings do not trust forwarded
  HTTPS headers. A real TLS proxy requires a separately reviewed trust boundary.
- `/health/` checks the database and returns 503 on database failure. Existing
  NAS status stays `not_configured`; health is not NAS integration evidence.
- Application access logs are disabled to avoid query-string credential capture;
  bounded Docker error logs remain. Base image tags move: deployed image ID and
  source SHA must be recorded. Pin digests before a repeatable production release.

## First installation (deployment-host shell)

Preflight `docker ps -a`, `ss -lnt`, available disk/RAM, and existing target paths.
Use an owner-only deployment directory. Transfer a reviewed `git archive` of an
exact commit into a new `releases/<SHA>` directory (never copy a developer `.env`).
Run from that release, with a stable secret file one directory above `releases`:

```sh
# Deployment root: run once. Refuses to overwrite an existing file.
python3 releases/<SHA>/deploy/init-secrets.py
python3 releases/<SHA>/deploy/init-mfa-key.py
# .env is now mode 0600; do not print, commit, or render compose config to logs.
cd releases/<SHA>
export SOURCE_REVISION=<SHA> COMPOSE_FILE=compose.internal.json
# All compose commands must select the same deployment-root secret file.
export COMPOSE_ENV_FILES=../../.env,../../.mfa.env
docker compose config --quiet
docker compose build --pull
docker compose up -d --wait db
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose up -d --wait --wait-timeout 120 web
curl --fail http://127.0.0.1:18080/health/
```

No startup migration races: migration is an explicit single one-shot operation,
not a command run by each Gunicorn worker. `up` alone does not apply migrations.
No account is provisioned; never use default/admin passwords. `.mfa.env` contains
an independently random Fernet key, generated exclusively on the target host,
separate from database and Django secrets. Never rerun/replace an existing key.
Its backup/restore and operator recovery procedures are NOT verified.

## Explicit trusted-LAN opt-in

`INTERNAL_BIND_HOST` selects the published interface and adds that exact address
to `DJANGO_ALLOWED_HOSTS`; localhost remains allowed for container healthchecks.
Unset or empty means loopback. Select only a specific private IPv4 address owned
by this host (authorized deployment: `192.168.1.14`); do not use `0.0.0.0`, `::`,
wildcards, hostnames or a comma-separated list. This is an operator-controlled
Compose input, not an application input validator or firewall. No wildcard host
is added automatically. Do not add router forwarding, public firewall openings,
or publish PostgreSQL. LAN mode replaces rather than adds the loopback host port.

For a newly reviewed release using this parameterized definition, retain the
same explicit selection for **every** Compose invocation (including restart):

```sh
export INTERNAL_BIND_HOST=192.168.1.14
export SOURCE_REVISION=<exact-built-source-SHA>
export COMPOSE_FILE=compose.internal.json
export COMPOSE_ENV_FILES=../../.env,../../.mfa.env
docker compose config --quiet
docker compose up -d --no-build --no-deps --wait --wait-timeout 120 web
curl --fail http://192.168.1.14:18080/health/
```

Do not substitute the PR head as `SOURCE_REVISION` unless that image has actually
been built. The current server retains the older image and a literal LAN patch
in its release Compose file; exact repeatable invocation and drift are recorded
in `evidence/container-lan.md`. Repository reconciliation does not redeploy it.
Retain the existing secret files unchanged; do not print interpolated config.

## Verification and rollback

Run container CI and the foundation suite. Confirm `migrate --check`, empty user
and tenant tables for first deploy, UID 10001, healthy states, exact image label
and ID, no DB published port, and the selected publication. Default mode must
reject LAN connections. Approved LAN mode must bind only the selected address,
serve landing/health 200 from another host, reject invalid Host with 400, and
redirect anonymous `/manage/` and `/mfa/enroll/` to login (302). Compare migration records before/after restart and
confirm the same named volume remains mounted. Do not use `down -v` or prune.

For this first deployment there is no older app release. Safe rollback is
`docker compose stop web` (or `stop` for both); retain secrets, release directory,
image and database volume. After subsequent deployments, select the retained
previous release/image **only if schema-compatible**; back up/restore PostgreSQL
under a separate reviewed migration plan otherwise. Never roll back by deleting
the volume. Preserve old image IDs and archives until rollback is no longer needed.

Production remains blocked on domain/TLS, proxy review, mandatory administrator
MFA operational enrollment/recovery, operator provisioning, separate least-privileged PostgreSQL
application/migration roles (the internal prototype currently uses its bootstrap
owner), off-host backup/restore, and independent
release review. A passing internal smoke does not complete roadmap stage 7.

## Primary references consulted

- https://docs.docker.com/engine/network/port-publishing/ — localhost bindings and
  the pre-28 localhost publishing caveat (server is 29.9.0).
- https://docs.docker.com/reference/compose-file/services/ — healthchecks,
  resource bounds, read-only roots, dependencies and logging.
- https://docs.docker.com/reference/compose-file/networks/ — internal networks.
- https://github.com/benoitc/gunicorn/blob/26.2.0/gunicorn/config.py — forwarded
  header trust and `control_socket_disable` (the older settings URL returned 404).
- https://pypi.org/project/gunicorn/26.2.0/ — pinned release (Python >=3.10).
- https://hub.docker.com/_/postgres — PostgreSQL 17 data volume location.
