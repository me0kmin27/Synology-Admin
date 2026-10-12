# Reverse proxy configuration and activation gate

Prepared target (operator supplied, spelling preserved): **Test.keiminem.com**,
HTTPS origin **https://Test.keiminem.com**, proxy **192.168.1.142**, backend
**192.168.1.14:18080**. These are example runtime values, not application constants.
DNS hostname comparison is case-insensitive; parsed hosts/origins are lowercased.
This document is **not evidence that the external proxy is operational**.

## Trust model

- Without `DJANGO_TRUSTED_PROXY_IPS`, **no peer** is trusted (including loopback).
  Set comma-separated literal IPs or canonical CIDRs. Invalid entries, hostnames,
  wildcard, empty entries and `/0` fail startup. Prefer the single current IP;
  never add the whole Docker/LAN subnet to make a failing request work.
- `DJANGO_ALLOWED_HOSTS` accepts exact hostnames/IPs, not wildcard, leading-dot
  subdomain patterns, schemes or ports. Defaults only to localhost/127.0.0.1;
  an empty list does not enable arbitrary hosts. Domain changes require a config
  edit and **web process/container recreation**, not a build or code edit.
- `DJANGO_CSRF_TRUSTED_ORIGINS` defaults empty. It accepts exact HTTPS origins
  (optional explicit port) whose hosts are in the allowed list. No paths,
  credentials or wildcard. Cookies and CSRF verification remain enabled.
- Proxy middleware runs before SecurityMiddleware, sessions, CSRF and throttling.
  Only the original socket `REMOTE_ADDR` is used to establish trust, including
  IPv4-mapped IPv6 normalization. Missing/malformed peers are untrusted.
- A trusted peer may supply exactly one `X-Forwarded-Proto: http|https` and one
  literal `X-Forwarded-For` address. Duplicate/chain/malformed values are rejected
  with 400. No header means retain the transport scheme/peer. An untrusted peer's
  values are ignored. Forwarding headers are removed before downstream code.
- **Host must be preserved by the proxy**. `Forwarded`, `X-Forwarded-Host`,
  `X-Forwarded-Port`, SSL/protocol aliases are not authority. `SECURE_PROXY_SSL_HEADER`
  stays None. Gunicorn scheme interpretation and PROXY protocol are disabled;
  `forwarded_allow_ips=''`, `secure_scheme_headers={}`, `forwarder_headers=''`.
  Do not override these via `GUNICORN_CMD_ARGS`, CLI or an alternate config.
- Gunicorn 26.2.0 preserves the raw hyphenated X-Forwarded-* WSGI headers even
  with its trust list empty. Real TCP tests prove this instead of assuming that
  an application-only RequestFactory test models server parsing. Header names
  with underscores are dropped by the server; duplicate scheme values reach
  middleware as a list and are rejected.
- The proxy must **overwrite**, not append to, inbound X-Forwarded-Proto and
  X-Forwarded-For. For nginx: `proxy_set_header Host $http_host;`
  `proxy_set_header X-Forwarded-Proto $scheme;`
  `proxy_set_header X-Forwarded-For $remote_addr;`. Configure only the intended
  virtual host. This is a single-hop contract, not a multi-proxy chain resolver.
  If no client-IP header is supplied, all clients share the proxy IP rate bucket.
  A compromised trusted proxy can assert any scheme/client IP; this is inherent.

## HTTP versus HTTPS modes

`compose.internal.json` is unchanged: explicitly insecure internal HTTP mode
remains available. Adding `compose.proxy.json` opts into environment-driven proxy
configuration and **defaults to secure mode** (`DJANGO_LOCAL_HTTP=0`). This enables
HTTPS redirects, Secure session/CSRF cookies and existing HSTS defaults. Only
`/health/` is exempt from redirects for the existing database healthcheck; host
validation still applies and it never authenticates a user.

Do not promise both secure production cookies and authenticated direct LAN HTTP
on the same instance: they conflict. `DJANGO_LOCAL_HTTP=1` is explicit insecure
LAN/development mode, not an acceptable production HTTPS rollout. Keep the old
internal deployment until TLS and source peer are verified; activate secure mode
only at the reviewed cutover. No active environment is modified by this PR.

## Operator update (after independent review)

Keep existing `.env` and `.mfa.env` secret files untouched. Copy the **non-secret**
`deploy/proxy.env.example` to a private `.proxy.env.next`, edit the exact hosts,
HTTPS origins and peer IP. Include `localhost,127.0.0.1` in hosts for healthchecks.
Use the exact already-built reviewed `SOURCE_REVISION` when changing config only.
Do not print expanded Compose config or inspect full container environments.

```sh
chmod 600 .proxy.env.next
# Check the candidate without exposing values or changing the running web service.
docker compose --env-file .env --env-file .mfa.env --env-file .proxy.env.next \
  -f compose.internal.json -f compose.proxy.json config --quiet
docker compose --env-file .env --env-file .mfa.env --env-file .proxy.env.next \
  -f compose.internal.json -f compose.proxy.json run --rm --no-deps web \
  python manage.py check --deploy --fail-level WARNING
# Save the previous .proxy.env privately if one exists, then atomically replace it.
mv .proxy.env.next .proxy.env
# Container recreation is required; restart alone does NOT reload Compose env.
docker compose --env-file .env --env-file .mfa.env --env-file .proxy.env \
  -f compose.internal.json -f compose.proxy.json up -d --no-build --no-deps \
  --wait --wait-timeout 120 web
```

Use the same file set for subsequent operations. If health or the external checks
fail, restore the previous private configuration and recreate web with its prior
file set/image. No DB reset, admin reset or MFA bypass is part of rollback.

## Required deployment evidence (still operator work)

1. Confirm the external proxy routes only the intended virtual host to
   `192.168.1.14:18080`. Capture the **actual backend TCP peer** safely (connection
   metadata only, not request bodies/cookies/passwords). It must be `192.168.1.142`.
   Docker published-port DNAT can preserve source IP, but userland proxies,
   hairpin NAT and different hosts may rewrite it. CI validates its own Docker
   topology, not this live host. If peer becomes a shared bridge gateway, **stop**;
   do not trust that gateway. Fix source preservation or isolate a dedicated
   authenticated ingress first.
2. Verify proxy overwrites both forwarding headers, including inbound malicious
   values, and preserves the intended Host. Direct backend requests with forged
   X-Forwarded-Proto must not bypass HTTPS redirects in secure mode. Check unknown
   Host=400 even with forged X-Forwarded-Host.
3. Validate certificate verification (no `-k`), redirect behavior and login on
   **each** published DNS A/AAAA route. Parent observed two A records; DNS/TLS
   reachability is not proof they serve this backend or share configuration.
4. Exercise CSRF-enforced login, mandatory initial password change where pending,
   real OTP, Secure cookies and logout through the actual HTTPS origin. Never
   reset/disable the existing admin/MFA merely for verification.
5. Record source/image revision, persisted non-secret settings, both DNS routes,
   exact peer and health. Never claim the published backend port is firewall-
   restricted unless independently verified; this change does not add a firewall.

## References and local/CI evidence

Primary references consulted: Django 5.2 settings `SECURE_PROXY_SSL_HEADER`,
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` at
https://docs.djangoproject.com/en/5.2/ref/settings/ ; Gunicorn settings at
https://gunicorn.org/reference/settings/ (`forwarded_allow_ips`,
`secure_scheme_headers`, `forwarder_headers`, `proxy_protocol`). The older
`docs.gunicorn.org/en/stable/settings.html` redirected to a 404 during research;
installed pinned 26.2.0 parser/WSGI source and TCP tests were also inspected.

Install `requirements-container.txt`, then run `python scripts/verify.py`.
Tests include strict config validation, trust/IPv4-mapped peers, malformed and
multiple headers, host+port, CSRF origins, real login/enrollment/OTP, Secure cookies,
redirects and real Gunicorn TCP parsing. Container CI additionally runs
`scripts/verify-proxy-container.py` against its disposable published port with a
probe's discovered exact source IP, then verifies the same source loses trust on
configuration recreation. Neither test substitutes for external TLS evidence.
