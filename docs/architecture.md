# Architecture

## Overview

```
Browser ──https──► 127.0.0.1:8443  (uvicorn, one worker, proxy_headers=False)
                      │
              BoundaryMiddleware      host/TLS/loopback check, extracts instance id from Host
                      │
              TenantDispatch
        ┌─────────────┴──────────────────┐
  Host = app.localhost:8443       Host = {uuid}.claw.localhost:8443
  control app (FastAPI)           tenant app (FastAPI)
   • login/switch/logout           • POST /__orchestrator/launch
   • /api/instance*                • everything else → authenticated
   • /api/assistant/*                HTTP/WebSocket proxy to the instance
   • /workspace, /healthz, ...
        │                                   │
        ▼                                   ▼
  PostgreSQL 18 (claw schema)       private Unix-socket SSH forward
  gateway WS RPC (protocol v4) ───► OpenClaw gateway inside the OpenShell sandbox
```

Alongside the API, the process runs:

- a **provisioning worker** (one asyncio task) that executes durable jobs from PostgreSQL and rechecks unavailable instances every 10 seconds;
- a **public-only egress proxy** (default `0.0.0.0:18490`) that tenant browsers use to reach the internet. See [Browser and egress](browser-and-egress.md).

## Two origins, one process

Every host reaches the same listener. `BoundaryMiddleware` (`boundary.py`) accepts a request only when all of these hold:

1. The client address is loopback.
2. The scheme is `https` or `wss`.
3. Exactly one `Host` header equals `app.localhost:{PUBLIC_PORT}`, or equals `{uuid-v4}.claw.localhost:{PUBLIC_PORT}` with a canonical lowercase UUIDv4.

Anything else gets a JSON 404 (WebSockets are closed with code 1008). For tenant hosts the UUID is stored in `scope["state"]["instance_id"]`, and `TenantDispatch` then routes to the tenant app. Separate origins mean separate cookies, storage, service workers and device identities per instance, so switching users cannot leak browser state between tenants. Instance URLs have no tenant path: the proxy keeps OpenClaw's own paths at the root of the instance origin.

## Request flows

### Launching an instance UI

1. `POST /api/instance/launch` on the control origin. The server checks the instance is `ready` and probes it, then stores a single-use ticket (SHA-256 hash, 30 second lifetime, bound to session, owner, instance and target origin).
2. It returns `launch.html`, a form that POSTs the ticket to `https://{uuid}.claw.localhost:8443/__orchestrator/launch`.
3. The tenant app checks `Origin`, consumes the ticket inside a transaction that locks the parent session row, sets the `__Host-claw_proxy` cookie (a JWT with audience `claw-proxy` and an `iid` claim) and redirects to `/`.
4. All later requests on that host go through `proxy_http` and `proxy_ws`.

### Chat through the curated API

1. The frontend calls `/api/assistant/...` with the control cookie. A `Guard` (`connections.py`) validates the session. `owned_gateway` resolves the caller's instance from the database and opens a short-lived WebSocket RPC connection to that instance's gateway (`gateway.py`).
2. Native frames are projected to public shapes (`chat_activity.py`, `presentation.py`) before they reach the browser. Raw RPC data and gateway credentials never leave the server.
3. `GET /api/assistant/events` streams SSE. It ends with `RECONNECT_REQUIRED` at its time bound, or `SESSION_ENDED` if the session was revoked.

### Provisioning

`POST /api/instance` inserts an `instances` row (`pending`) and a `provisioning_jobs` row in one transaction. `ON CONFLICT (owner_user_id) DO NOTHING` makes creation idempotent per user. The worker leases the job, runs `runtime.provision`, probes the result, and marks the instance `ready` or `failed`. See [Runtime and provisioning](runtime-and-provisioning.md).

## Module map

| Module | Responsibility |
| --- | --- |
| `app.py` | App factory, lifespan, middleware (session fence, body limit, security headers), auth routes, instance routes, tenant app |
| `boundary.py` | Host, TLS and loopback enforcement; instance id extraction |
| `config.py` | `Settings` and validation of the control origin, secrets, session length |
| `auth.py` | JWT encode/decode, session creation/revocation, CSRF, cookies |
| `db.py` | asyncpg pool, advisory-locked migration runner |
| `instances.py` | Instance rows, launch tickets, proxy authorization |
| `provisioning.py` | Job lease/attempt logic, retained-instance recovery, worker loop |
| `runtime/base.py`, `runtime/nemoclaw.py` | `Runtime` protocol and the NemoClaw/OpenShell adapter |
| `proxy.py` | Header sanitising, HTTP streaming proxy, WebSocket proxy over a Unix socket |
| `connections.py` | `Connections` registry and `Guard`; closes live streams when a session is revoked |
| `gateway.py` | Bounded client for the OpenClaw v4 WebSocket RPC protocol |
| `frontend_api.py` | Sessions, history, messages, abort, SSE, CSRF endpoint, OpenAPI schema |
| `feature_api.py` | Capabilities, tasks, approvals (reviews) |
| `automations.py` | Schedule CRUD, runs, idempotency |
| `browser_api.py`, `browser_connections.py`, `browser_bridge.py` | Owner-selected browser connection and tabs |
| `egress_proxy.py` | Public-only egress proxy |
| `chat_activity.py`, `presentation.py` | Safe projection of native frames and text (brand and credential scrubbing) |
| `inference.py` | OpenRouter preflight (credential, free-model, tool-support checks) |
| `errors.py` | `APIError(status, code, message)` |

## Design decisions

| Decision | Reason |
| --- | --- |
| Routing authority is a valid JWT, a live session row, and database ownership. A client never selects a target. | Prevents cross-tenant access through crafted paths or headers. |
| One instance per user (`UNIQUE(owner_user_id)`). | Keeps the prototype's isolation model simple. |
| Instance UUID is server-generated and stable. Sandbox name is `co-{uuid.hex[:16]}` and volume is `openclaw-data-{uuid}`. | NemoClaw sandbox names are limited to 19 characters. The full UUID stays authoritative. |
| Durable provisioning jobs with leases instead of fire-and-forget tasks. | Survives API restarts. At most 3 attempts. |
| Server-rendered HTML with plain ES modules. | No frontend build step. |
| Curated API over a raw gateway proxy. | The browser never gets arbitrary RPC methods, provider settings or gateway tokens. |
| Single uvicorn worker. | The runtime adapter holds in-process locks and forwards. Do not scale it out without redesign. |

## Non-goals in this milestone

Public deletion, upgrade, admin, billing, registration and multi-host scheduling APIs do not exist. Calendar, mailbox, provider connections and browser takeover are reported as `not_implemented` by `/api/assistant/capabilities`.
