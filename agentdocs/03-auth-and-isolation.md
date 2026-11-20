# Authentication and isolation contract

## Trust and demo authentication

The two buttons select demo identities. They intentionally do not verify a real person's identity. Enable this only with `DEMO_AUTH_ENABLED=true` on a loopback-bound deployment. Refuse public/nonlocal demo startup unless a separate, deliberate development configuration is supplied; production must replace this identity provider. Isolation tests assume the caller holds a valid session for one identity and tries to cross its authorization boundary.

Both login and proxy cookies are server-signed JWTs. Prototype claim contract:

```json
{
  "iss": "claw-orchestrator",
  "aud": "claw-control",
  "sub": "user1",
  "sid": "cryptographically-random-session-id",
  "iat": 0,
  "nbf": 0,
  "exp": 0,
  "jti": "cryptographically-random-token-id"
}
```

The timestamps above are schema placeholders, not usable values. Use HS256 with a random key of at least 32 bytes held only by trusted infrastructure and an explicit algorithm allowlist. Reject incorrect issuer/audience, absent required claims, expired/not-yet-valid tokens, unknown users, and inactive sessions. Allow at most 30 seconds of clock skew. Start with a 1-hour session, no refresh flow; cookie lifetime must not exceed token expiry. Proxy JWTs use audience `claw-proxy` and an additional `iid` claim, with expiry no later than the parent session. Never accept a control JWT at the proxy or a proxy JWT at control endpoints.

The database is authoritative: check `sid`, owner, expiry, revocation, and current instance mapping on each request. A valid signature alone does not grant access after logout. Proxy `iid` must equal the instance currently owned by `sub`; it cannot redirect routing to an arbitrary instance.

## Cookie and CSRF policy

| Cookie | Host | Attributes |
| --- | --- | --- |
| `__Host-claw_session` | Login/control hostname only | HttpOnly; Secure; SameSite=Lax; Path=/; no Domain |
| `__Host-claw_proxy` | Selected instance hostname only | HttpOnly; Secure; SameSite=Lax; Path=/; no Domain |

Use local HTTPS for browser integration. Do not weaken production cookie attributes to work around development TLS. Host-only cookies avoid sending an orchestration session to sibling tenant hosts; the `__Host-` prefix constrains cookie scope. [Cookie attribute reference](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).

For control POSTs, use a server-issued synchronizer CSRF token bound to the session (or a short-lived signed pre-login nonce for signed-out login), and an exact Origin check. Reject missing/foreign Origins for browser state changes. Never allow GET to login, logout, switch, provision, or mint a ticket. SameSite alone is insufficient: sibling tenant origins may be same-site.

## Launch without sharing cookies or credentials

1. User submits `POST /api/instance` from the control page; poll `GET /api/instance` until ready.
2. “Visit OpenClaw” submits `POST /api/instance/launch` with the control session and CSRF token. Recheck readiness and ownership.
3. Store a hash of a random one-use ticket (at least 32 random bytes), bound to `sid`, user, instance, exact target origin, and a 30-second expiry.
4. Return a no-store minimal HTML form that POSTs the ticket in its body to `https://{uuid}.claw.localhost/__orchestrator/launch`. The form target is computed server-side. Set `Referrer-Policy: strict-origin` (Chromium otherwise nulls Origin on form POSTs); do not use a query string, fragment, or JWT in the URL.
5. On the target host, require the exact control-page Origin, atomically consume the ticket, and revalidate its live session and ownership. Mint the host-only proxy cookie, then `303` to `/` on that same host. The temporary reserved handoff path contains no tenant identifier and is never an OpenClaw upstream route.
6. Every subsequent request, including `/` and WebSockets, validates the proxy cookie and ownership before any upstream work. The hostname UUID must match this resolved instance; it never independently selects authorization.

The consumed ticket cannot be replayed, used for another host, or used after a switch/logout. Do not return provider credentials, gateway secrets, or orchestrator JWTs in HTML or JSON. Any launch ticket response contains a short-lived bearer capability, so redact request bodies on these endpoints and prohibit caching.

```mermaid
sequenceDiagram
    participant B as Browser
    participant C as Control API
    participant D as Session/instance DB
    participant P as Instance-origin proxy
    participant O as Owner's OpenClaw
    B->>C: POST login + CSRF (user1)
    C->>D: Create session
    C-->>B: Set host-only JWT cookie
    B->>C: POST create then POST launch + CSRF
    C->>D: Resolve owner, ready instance, one-use ticket
    C-->>B: Form POST to owner's instance origin
    B->>P: POST launch ticket
    P->>D: Consume ticket, validate live session/owner
    P-->>B: Set proxy JWT cookie; redirect /
    B->>P: GET / or WebSocket handshake
    P->>D: Validate sid, owner, iid, hostname
    P->>O: Private upstream request with rebuilt identity
    O-->>P: Response or stream
    P-->>B: Authorized response or stream
```

## Proxy enforcement

- Map only a validated principal to its DB instance and verified private upstream. Never accept a target URL, Docker name, port, or mount from client input. Disable environment-configured outbound proxies and automatic redirect following in the upstream client.
- Validate allowed Host values at ingress and app layers. Trust forwarding headers only from the configured edge, then rebuild them. Reject malformed/duplicate Host, ambiguous framing, and unsupported upgrades rather than interpreting them differently across layers.
- Strip browser Authorization, orchestration cookies, `Forwarded`, `X-Forwarded-*`, identity/scope headers, and hop-by-hop headers before forwarding. Generate upstream identity and forwarding headers from verified server state. Preserve required WS upgrade semantics through the WS implementation, not by blindly copying headers.
- Use a server-owned header such as `X-Claw-User` for OpenClaw trusted-proxy auth; allow only the instance owner's immutable identity. Configure the exact observed trusted proxy source and exact external allowed origin. No wildcard origins, broad trusted subnets, token-in-URL fallback, or disabled auth.
- Gateway auth/device enrollment must be verified against the pinned release. Keep required pairing enabled; if supported auto-approval is chosen, explicitly constrain scopes to those necessary for the prototype. Do not assume proxy auth automatically removes device pairing, or inject a bearer header and assume it satisfies the gateway's WS connect protocol. [OpenClaw trusted-proxy reference](https://docs.openclaw.ai/gateway/trusted-proxy-auth).
- Keep instance upstream ports unreachable by browsers and other workloads. Authorize every route even when OpenClaw itself supports device tokens or other auth paths. Upstream credentials must never bypass the outer session boundary.
- Require exact instance Origin on WebSocket handshakes and unsafe upstream HTTP methods; deny missing or `null` Origin in v0 browser mode. Disable cross-origin credentialed CORS. Validate origins on reads when supplied; top-level navigation may omit Origin.
- Strip or constrain upstream `Set-Cookie` Domain to the current host; reject reserved orchestrator cookie names. Rewrite only approved internal redirects to the same external instance origin; reject cross-tenant/internal-host redirects. Never follow upstream redirects with user credentials.
- Use `Cache-Control: private, no-store` for v0 proxy/control responses; no shared authenticated cache. Disable OpenClaw's service-worker/offline persistence behavior in the verified integration profile, or treat inability to do so as a browser-isolation issue to resolve in milestone 0. Separate origins prevent user2's UI from accessing user1's web storage.
- Forward HTTP bodies, files, and streaming data with bounded buffers, deadlines, and cancellation. Cap message/body sizes and connection counts. Never log cookies, credentials, launch tickets, file contents, or chat bodies.

## Switching, logout, and long-lived connections

Switching revokes the old browser session transactionally and creates a new session for the selected identity. It does not revoke that user's independent sessions in other browser profiles. Logout revokes the current `sid` and clears the control cookie with the same attributes used to set it. Sibling-host proxy cookies cannot be cleared directly from the control origin; session revocation makes them unusable.

Track active HTTP streams and WS connections by `sid` and instance. In this single-worker prototype, switch/logout must cancel their forwarding and close sockets as part of revocation handling. Check session expiry during long-lived connections with a timer and check liveness periodically (target maximum 1 second for externally observed revocation). Cancel pending handshakes and recheck authorization after asynchronous upstream setup. No queued message may be rerouted to the new user's instance. Drop late upstream frames after revocation.

Tenant origins have no control API and no sibling origin access. The demo selector navigates in the same tab, and returning to control rechecks its session. Previously rendered content in an old tab cannot be retroactively erased by a proxy; retained content is outside the server-access guarantee. Do not claim cross-user secrecy on a shared physical browser profile solely from logout.

## Workload boundary

Each tenant gets its own volume, config/state, gateway, and scoped inference binding. Use the supported OpenShell isolation and mediated ingress rather than manually attaching networks that bypass its controls. Verify effective cross-tenant network isolation for the pinned release. OpenShell egress policy must block other tenant ranges, host management services, private control-plane endpoints, and metadata services while allowing the selected provider. Test the effective policy, including IPv6 and host aliases.

No privileged mode, host networking, host PID/IPC namespaces, extra capabilities without a verified runtime need, Docker socket, or arbitrary host bind mounts inside tenants. Apply CPU, memory, PID, storage/logging, and request limits to keep one user from exhausting the host. Container controls reduce risk; they do not create a separate host/kernel per tenant. [Docker bridge behavior](https://docs.docker.com/engine/network/drivers/bridge/).
