# Internal-only Docker validation (not a production release)

Scope: the separately authorized Debian deployment server, never the NAS or
RustDesk host. HTTP is published **only** on `127.0.0.1:18080`. No database host
port, domain, TLS termination, public firewall rule, administrator seed, or NAS
credential is created. This branch does not include the independent MFA PR.

## Definitions and safety boundary

- Python 3.14 follows `.python-version`; Gunicorn 26.2.0 is pinned separately from
  base app dependencies. The app is UID/GID 10001, read-only root filesystem,
  dropped capabilities, no-new-privileges, bounded temporary storage.
- PostgreSQL 17 uses a persistent named volume, 768 MiB memory, 128 MiB shared
  buffers and 40 connections. Web gets 512 MiB; both have one CPU and 128 PIDs.
- A Docker `internal` bridge prevents normal external egress. It is not a host
  security boundary: host/docker administrators can access the containers and
  their environment. Secrets are not protected from Docker administrators.
- `DJANGO_LOCAL_HTTP=1` deliberately disables HTTPS redirect/secure cookies for
  loopback validation. **Do not use this compose file for production.**
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
# .env is now mode 0600; do not print, commit, or render compose config to logs.
cd releases/<SHA>
export SOURCE_REVISION=<SHA> COMPOSE_FILE=compose.internal.json
# All compose commands must select the same deployment-root secret file.
export COMPOSE_ENV_FILES=../../.env
docker compose config --quiet
docker compose build --pull
docker compose up -d --wait db
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose up -d --wait --wait-timeout 120 web
curl --fail http://127.0.0.1:18080/health/
```

No startup migration races: migration is an explicit single one-shot operation,
not a command run by each Gunicorn worker. `up` alone does not apply migrations.
No account is provisioned; never use default/admin passwords. Any future MFA key
must be independently generated and preserved when the MFA branch is integrated.

## Verification and rollback

Run container CI and the foundation suite. Confirm `migrate --check`, empty user
and tenant tables for first deploy, UID 10001, healthy states, exact image label
and ID, loopback socket, no DB published port, and inability to connect to the
server LAN address port 18080. Compare migration records before/after restart and
confirm the same named volume remains mounted. Do not use `down -v` or prune.

For this first deployment there is no older app release. Safe rollback is
`docker compose stop web` (or `stop` for both); retain secrets, release directory,
image and database volume. After subsequent deployments, select the retained
previous release/image **only if schema-compatible**; back up/restore PostgreSQL
under a separate reviewed migration plan otherwise. Never roll back by deleting
the volume. Preserve old image IDs and archives until rollback is no longer needed.

Production remains blocked on domain/TLS, proxy review, mandatory administrator
MFA integration, operator provisioning, off-host backup/restore, and independent
release review. A passing internal smoke does not complete roadmap stage 7.

## Primary references consulted

- https://docs.docker.com/engine/network/port-publishing/ — localhost bindings and
  the pre-28 localhost publishing caveat (server is 29.9.0).
- https://docs.docker.com/reference/compose-file/services/ — healthchecks,
  resource bounds, read-only roots, dependencies and logging.
- https://docs.docker.com/reference/compose-file/networks/ — internal networks.
- https://docs.gunicorn.org/en/stable/settings.html — forwarded header trust.
- https://pypi.org/project/gunicorn/26.2.0/ — pinned release (Python >=3.10).
- https://hub.docker.com/_/postgres — PostgreSQL 17 data volume location.
