# Initial owner and self-service credentials

This feature prepares a safe path; it does not create any remote account at merge
or application startup. Parent/operator approval and a deployed reviewed SHA are
required before running these commands. The default identifier is `admin`, not a
shared password; `--username` can select another identifier. Existing identities
are never reset, promoted, or overwritten. The browser can change both identifier
and password later at `/account/settings/`.

## Two-phase bootstrap

1. `python manage.py bootstrap_admin` reserves a superuser with `is_active=False`
   and an unusable password. Repeating it leaves that same identity unchanged.
   A collision with any unrelated identity or an existing superuser fails closed.
2. `python manage.py activate_bootstrap_admin` prompts twice on the owner's trusted
   SSH/local TTY (no echo, no stdin/argv password). It validates Django password
   rules and refuses to activate any already active/usable identity.
   Alternatively `--password-file /absolute/private/path` generates a random
   password once and writes **only** to a new mode-0600 file; never to stdout.
   Its directory must be owned by the command's UID and have no group/other access.
   Existing files and symlinks are refused. There is no reset option.
3. Login through TLS or an SSH tunnel, enroll and confirm mandatory administrator
   OTP, then change the initial password at `/account/settings/`. No privileged
   route is available until this change. The identifier may change at the same
   time; privileges, membership, NAS mapping and the encrypted OTP device do not.

No setup bearer token is generated or sent over HTTP. Password-file mode is for
a one-time remote owner handoff; interactive mode avoids a password file entirely.
Never put passwords/OTP seeds in chat, command arguments, logs, screenshots,
version control or environment files. The existing external MFA encryption key
must be preserved, not generated anew by this feature.

## Reviewed Docker deployment: operator-only instructions

Run from the deployed release with the **same** `SOURCE_REVISION`, `COMPOSE_FILE`,
`COMPOSE_ENV_FILES` and `INTERNAL_BIND_HOST` used by that deployment. Do not print
interpolated Compose configuration. Apply migrations 0012 and 0013 first. The
following commands are documentation, not authorization to execute remotely.

```sh
# Existing release/compose environment must already be selected correctly.
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose run --rm --no-deps web python manage.py bootstrap_admin

# Pick a new private directory OUTSIDE the release tree, owned by container UID.
# Replace this example absolute directory with the approved deployment root.
PRIVATE_DIR=/absolute/deployment-root/bootstrap-private
sudo install -d -o 10001 -g 10001 -m 0700 "$PRIVATE_DIR"
docker compose run --rm --no-deps -v "$PRIVATE_DIR:/run/bootstrap" web   python manage.py activate_bootstrap_admin   --password-file /run/bootstrap/admin-initial-password
```

The application container's normal read-only root and Compose definition remain
unchanged; only this one-shot process receives the private mount. Record only
account state and file mode, never file content, in deployment evidence. If a
write/commit fails after file creation, an orphan file can remain: do not overwrite
it, do not assume activation succeeded, and inspect account state without printing
its hash. A retry against a fresh explicitly chosen private filename is permitted
only while the account is still inactive and unusable.

**Owner only, in their own SSH terminal (not an assistant tool/logged session):**
`sudo less /absolute/deployment-root/bootstrap-private/admin-initial-password`
reads the secret. Do not paste it into chat. After confirmed password change and
successful new login, remove that one file from the owner terminal. Preserve the
external MFA key and PostgreSQL volume.

For interactive activation instead, use `docker compose run --rm --no-deps web
python manage.py activate_bootstrap_admin` directly in the owner's terminal; do
not use `-T` or pipe a password.

## Transport requirement

The internal deployment's LAN HTTP endpoint is **not safe for real passwords or
OTP enrollment**. Before entering any secret, open an SSH tunnel on the owner's
computer. For the currently documented host-local LAN binding:

```sh
ssh -N -o ExitOnForwardFailure=yes   -L 127.0.0.1:18081:192.168.1.14:18080 me0kmin27@192.168.1.14
```

Open `http://127.0.0.1:18081/login/` locally. The remote destination is that SSH
host's own bound address, not a different LAN machine. If deployment is bound to
remote loopback instead, use destination `127.0.0.1:18080`. Do not open the LAN URL,
forward the local tunnel on `0.0.0.0`, or alter proxy/TLS settings ad hoc. A separately
reviewed real TLS deployment remains necessary for general use.

## Credential change contract

- Authenticated self only; CSRF-protected POST, current-password reauthentication,
  shared account/IP throttle, and current confirmed MFA for all admin types.
- Django UsernameField NFKC normalization plus auth_user unique constraint and a
  serialized policy lock; duplicate claims cannot partially change a password.
- Django password validators run against the proposed identifier; mismatch,
  weak password and reusing the current password fail without mutation.
- Current session is rotated and its auth hash/scope refreshed; other database
  sessions are deleted and membership version advances. Queued stale requests
  recheck database-session existence and the fresh password hash under policy lock.
- CredentialAudit contains only actor ID, change booleans and timestamp, never
  identifiers, password hashes, submitted passwords or OTP secrets. All database
  writes, audit, session updates and bootstrap completion share one transaction.
- No role/status/tenant editing or last-administrator demotion is introduced.
  Existing last-admin protections remain in force. This is a portal identity,
  not a DSM account creation/password-reset feature.

## References verified during implementation

- https://docs.djangoproject.com/en/5.2/topics/auth/default/ — session hash refresh
  and `update_session_auth_hash()` session rotation.
- https://docs.djangoproject.com/en/5.2/topics/auth/passwords/ — explicit
  `validate_password()` for custom password-setting flows; unusable passwords.

## Verification and remaining release gates

TDD execution observed missing route (404), unchanged password hash, missing
bootstrap command, missing activation/file option, missing first-change gate,
missing throttle/redaction/audit, and stale-session acceptance before fixes.
Unit/HTTP regression suite and PostgreSQL lock-contention CI are required at the
final PR head. The parent must independently review, merge, deploy, and approve
remote provisioning; none of those is implied by a green local test.
