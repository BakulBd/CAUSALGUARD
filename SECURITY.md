# Security

## Reporting

Report vulnerabilities privately to the maintainers (see repo metadata). Please
do not open public issues for security problems.

## Hardening posture (1.1)

| Control | Mechanism | Default |
|---|---|---|
| Container | multi-stage, non-root uid 1001 / nginx uid 101, `tini` PID 1, read-only-friendly | on |
| Transport | TLS termination at the `edge` nginx (prod profile); HSTS | prod profile |
| CORS | explicit origin allowlist from config; `*` disables credentialed CORS | localhost dev origins |
| Host header | `TrustedHostMiddleware` allowlist | `*` (narrow via `CAUSALGUARD_SERVER__TRUSTED_HOSTS`) |
| Response headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, COOP, `Permissions-Policy` | on |
| AuthN | optional API keys (`Authorization: Bearer` / `x-api-key`) on **mutating** routes | disabled until keys set |
| Rate limiting | per client-id sliding window, `429` + `Retry-After` | 240/min |
| Secrets | env / `deploy/env/*.env` (git-ignored); `redacted()` strips DSNs & keys from `/system/config` and logs | — |
| Telemetry DB | least-privilege `causalguard_monitor` role (`pg_monitor` + `SELECT`) | provisioned by init SQL |
| Sandbox | refuses primary host+db; destructive actions gated by `ALLOW_DESTRUCTIVE`; `pg_terminate_backend` limited to verified blockers | guards on |
| Supply chain | pinned base images, `pip install` from `pyproject`, Trivy `CRITICAL,HIGH` gate in CI, Dependabot | on |

## Threat notes

- The API trusts inbound `x-request-id` for correlation only; it is never used
  for authz.
- `/metrics` and `/health` `/ready` are unauthenticated and rate-limit-exempt by
  design — restrict them at the network / proxy layer if exposed publicly.
- The real sandbox can execute destructive SQL. Keep `ALLOW_DESTRUCTIVE=false`
  unless the `SANDBOX__DSN` is a genuinely disposable clone, and never set
  `ALLOW_PRIMARY=true` against production.
