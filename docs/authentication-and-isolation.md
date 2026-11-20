# Authentication and isolation

## Demo login

There are two fixed identities, `user1` and `user2` (`auth.USERS`, mirrored by a `CHECK` constraint on `users.id`). Demo login lets a local visitor choose either one. It proves nothing about a real person and exists only for the prototype. `DEMO_AUTH_ENABLED` defaults to `false` in code and is `true` in `.env.example`.

## Tokens and cookies

All tokens are HS256 JWTs signed with `JWT_SECRET` (at least 32 characters). `iss` is `claw-orchestrator`. Required claims are `iss`, `aud`, `iat`, `nbf`, `exp` and `jti`. `iat`, `nbf` and `exp` must be integers.

| Cookie | Audience | Lifetime | Set on | Contents |
| --- | --- | --- | --- | --- |
| `__Host-claw_prelogin` | `claw-prelogin` | 10 minutes | `GET /auth/csrf` before login | CSRF nonce |
| `__Host-claw_session` | `claw-control` | `SESSION_SECONDS` (1 to 3600) | Login, switch | `sub` (user), `sid` |
| `__Host-claw_proxy` | `claw-proxy` | Remainder of the session | Launch ticket exchange on the instance host | `sub`, `sid`, `iid` (instance id) |

All cookies are `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`. The `__Host-` prefix means they are host-only, so the instance origins cannot read the control cookie.

A token alone is not enough. `Auth.authenticate` also requires a matching `sessions` row that is not revoked and has not expired. The token's `exp` cannot exceed the row's `expires_at`.

## Session lifecycle

- **Login**: the client fetches a CSRF nonce from `GET /auth/csrf`, which sets the prelogin cookie. `POST /auth/login` with `{user, csrf}` validates the nonce against the prelogin token, inserts a session row (random `sid` and per-session `csrf_token`) and sets the session cookie.
- **Switch**: `POST /auth/switch` revokes the current session and creates one for the other user, in a single transaction. If the previous session is no longer live it fails with `INVALID_SESSION`.
- **Logout**: `POST /auth/logout` revokes the row and clears the cookie.
- **Revocation propagation**: `Connections.revoke(sid)` signals every open stream and proxy socket registered for that session, so SSE and WebSocket connections end when the user switches or logs out.

## CSRF, Origin and the session fence

- Every mutating request needs the exact `Origin` equal to `CONTROL_ORIGIN`, and the session's CSRF token (form field `csrf` or the `X-CSRF-Token` header). Tokens are compared with `secrets.compare_digest`.
- Request bodies on auth routes are capped at 8 KiB, and bodies under `/api/assistant/` and `/api/openclaw/` at 32 KiB. Input models forbid extra fields, and form posts with duplicate fields are rejected.
- **Workspace session fence**: browsers send `X-Workspace-Session`, the SHA-256 of `"claw-workspace:" + sid`. The middleware authenticates the cookie and compares the two. A mismatch returns `409 SESSION_CHANGED`. This stops a tab that is still showing user1's data from acting after another tab switched to user2. The value is not a credential.

## Instance launch tickets

Instance hosts never see the control JWT. The control app issues a one-time ticket (see [Architecture](architecture.md#launching-an-instance-ui)). Only the SHA-256 of the ticket is stored. It lives 30 seconds, is bound to session, owner, instance and target origin, and is consumed under a row lock on the parent session. A ticket cannot be used after logout, and cannot be replayed.

## Isolation guarantees

| Boundary | Enforcement |
| --- | --- |
| Network | `BoundaryMiddleware`: loopback client, HTTPS/WSS, exact host match. The server binds `127.0.0.1` and uvicorn runs with `proxy_headers=False`, so forwarded headers are never trusted. |
| Browser | One origin per instance UUID. Cookies are host-only. Content-Security-Policy is `default-src 'none'` with `'self'` scripts, styles and connections, `frame-ancestors 'none'`, and `form-action` limited to self and `https://*.claw.localhost:{port}`. `Referrer-Policy: strict-origin` keeps paths private while keeping `Origin` checks working. |
| Ownership | The instance comes from `instances WHERE owner_user_id = <session user>`. `authorize_proxy` requires the proxy token's `iid`, the Host UUID and the owned row to agree, and the instance to be `ready`. |
| Upstream identity | `proxy.upstream_headers` strips client-supplied `authorization`, `cookie` entries named `__Host-claw_*`, `forwarded`, `x-forwarded-*`, `x-claw-*`, `x-real-ip` and related headers, then sets `x-claw-user`, `x-forwarded-*` and `x-claw-proxy`. The gateway runs in trusted-proxy mode and accepts only `x-claw-user` of `user1` or `user2`, with `x-claw-proxy` required. |
| Secrets | Orchestrator JWTs stay out of upstream traffic, JavaScript storage, URLs and logs. Provider keys live in `.env` (mode 0600) and are passed to workloads as environment references, never to the frontend. |
| Data | Each instance mounts only its own `openclaw-data-{uuid}` volume. The orchestrator database, host home, Docker socket and runtime credentials are never mounted. |
| Egress | Tenant browser traffic goes through the public-only egress proxy. See [Browser and egress](browser-and-egress.md). |
| Errors | Responses carry stable codes and generic messages. Runtime exception text and CLI output are never logged or returned. Responses are `Cache-Control: private, no-store`. |

## What the tests do and do not prove

Proxy tests use controlled HTTP and WebSocket upstreams. They show header handling, ownership checks and revocation behavior. They do not establish real container or filesystem isolation, which depends on NemoClaw and OpenShell. Live two-user checks are recorded in `docs/agentdocs/08-runtime-findings.md`.
