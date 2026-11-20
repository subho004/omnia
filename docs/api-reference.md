# API reference

All routes are served on the control origin, `https://app.localhost:{PUBLIC_PORT}` (default 8443). A separate frontend must be served from that same origin. Cross-origin development servers are not enabled.

## Conventions

- **Auth**: cookie `__Host-claw_session`. Unauthenticated calls get `401 AUTH_REQUIRED` or `401 INVALID_SESSION`.
- **Mutations** (`POST`) need the exact `Origin` header and `X-CSRF-Token` from `GET /auth/csrf`. Browser form posts may send a `csrf` field instead.
- **Session fence**: send `X-Workspace-Session` (SHA-256 of `"claw-workspace:" + sid`) on `/api/` and `/auth/` calls. A stale value returns `409 SESSION_CHANGED`.
- **Inputs** reject unknown fields. Bodies are capped at 8 KiB (auth) and 32 KiB (`/api/assistant`).
- **Errors** use one shape:

```json
{"error": {"code": "INSTANCE_NOT_READY", "message": "Your instance is not ready.", "request_id": "9f1c2a7be03d4a11"}}
```

Dependency failures (PostgreSQL, network, timeouts) return `503 DEPENDENCY_UNAVAILABLE`. Validation failures return `422 INVALID_INPUT`.

- The `/api/assistant/*` routes are also mounted under `/api/openclaw/*` for developer and compatibility access. They are excluded from the schema and are not customer-facing.

## Health

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/healthz` | `{"status":"ok"}`. No auth. |
| GET | `/readyz` | Database check plus `runtime: ready` or `not_configured`. No auth. |
| GET | `/api/runtime` | Authenticated. `{available, message}`. |

## Authentication

| Method | Path | Body | Notes |
| --- | --- | --- | --- |
| GET | `/auth/csrf` | none | Returns `{csrf_token}`. Without a session it returns a prelogin nonce and sets the prelogin cookie. |
| POST | `/auth/login` | `{user: "user1"\|"user2", csrf}` | Sets the session cookie. |
| POST | `/auth/switch` | `{csrf}` | Revokes the current session and signs in as the other user. |
| POST | `/auth/logout` | `{csrf}` | Revokes the session and clears the cookie. |
| GET | `/auth/me` | none | Current user and session information. |

Browser form posts get a redirect. JSON/AJAX clients get a JSON response.

## Instance

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/instance` | `{instance: {id, status, created_at, error_code}}`. `404 INSTANCE_NOT_CREATED` if none. |
| POST | `/api/instance` | Creates the caller's single instance and its provisioning job. Idempotent: a second call returns the existing row. `503 RUNTIME_NOT_CONFIGURED` when the runtime is not activated. |
| POST | `/api/instance/launch` | Returns an HTML form that exchanges a one-time ticket on the instance origin. Requires a `ready` instance that passes a probe. |
| POST | `https://{uuid}.claw.localhost:{port}/__orchestrator/launch` | Instance origin. Consumes the ticket, sets the proxy cookie, redirects to `/`. |

Instance `status` values: `pending`, `provisioning`, `ready`, `failed`, `unavailable`. Error codes seen on the instance row are `PROVISIONING_FAILED` and `RECOVERY_LIMIT`.

## Assistant API (`/api/assistant`)

The server picks the caller's instance. Clients never send a tenant id, gateway URL or token.

### Sessions and chat

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/sessions` | `limit` 1 to 100 (default 50), `offset` 0 to 10000. |
| POST | `/sessions` | Optional `title` (1 to 100 characters). Returns 201. |
| GET | `/history` | `session_key`, `limit` 1 to 100, opaque `cursor`. |
| POST | `/messages` | `session_key`, `message` (1 to 4000 characters). Returns 202: acceptance, not completion. |
| POST | `/runs/abort` | `session_key`, `run_id` (`[A-Za-z0-9_-]`, up to 128). |
| GET | `/events` | SSE for one `session_key`. `include_approvals=true` adds review events. |
| GET | `/openapi.json` | Authenticated OpenAPI schema. Docs UIs are disabled. |

### Server-sent events

Events: `ready`, `chat`, `activity`, `session.approval`, `approval.replay` and `error`. The stream sends a keepalive comment every 15 seconds and ends after about 300 seconds. The `error` event carries a `code`:

- `RECONNECT_REQUIRED`: normal expiry or a transient fault. Reload history and subscribe again. Do not resend the message.
- `SESSION_ENDED`: the session was revoked or expired. Stop and ask the user to sign in.

Browsers use cookie-authenticated `fetch` streaming rather than `EventSource`, so the session-fence header can be sent.

### Capabilities

`GET /capabilities` returns `api_version`, `instance_status`, `runtime_validation` (from the runtime manifest) and a `features` map. Each feature has a `state` of `implemented`, `partial`, `requires_validation`, `disabled` or `not_implemented`.

| Feature | State |
| --- | --- |
| `chat_sessions`, `task_status`, `schedules` | `implemented` |
| `workflow_continuation` | `partial` |
| `browser_workflows` | `requires_validation` |
| `reviews` | `disabled` |
| `tenant_connections`, `calendar`, `browser_takeover`, `email`, `memory`, `routines_channels_specialists` | `not_implemented` |

Treat this endpoint, not these docs, as the source of truth at runtime.

### Tasks

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/tasks` | Native task ledger. |
| GET | `/tasks/{task_id}` | One task. |
| POST | `/tasks/{task_id}/cancel` | Cancels exactly that task. |

### Reviews (approvals)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/approvals?session_key=...` | Pending approvals for a session. |
| GET | `/approvals/history` | Decided approvals. |
| GET | `/approvals/{approval_id}` | Detail plus a review token. |
| POST | `/approvals/{approval_id}/resolve` | Approve or deny with the review token. |

Review tokens are bound to the issuing session, are single use, and expire (stored in `approval_reviews.expires_at`). Decision history is native bookkeeping, not an external booking or order receipt. The `reviews` feature is currently `disabled`.

### Automations

See [Automations](automations.md) for the contract.

| Method | Path |
| --- | --- |
| GET | `/automations`, `/automations/runs`, `/automations/{id}` |
| POST | `/automations`, `/automations/{id}/update`, `/automations/{id}/run`, `/automations/{id}/remove` |

### Browser

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/browser` | State (`connected`, `starting`, `disconnected`) and open tabs. |
| POST | `/browser/connect` | Starts the managed browser. |
| POST | `/browser/disconnect` | Stops it. |
| POST | `/browser/tabs` | Opens a tab. The URL must resolve to public addresses (`check_destination`). Returns 201. |

## Instance origin (`https://{uuid}.claw.localhost:{port}`)

After launch, every path other than `/__orchestrator/launch` is proxied to the instance's OpenClaw UI over HTTP and WebSocket, after the proxy cookie and ownership checks.

## Client library

[`clients/assistant.ts`](../clients/assistant.ts) is a framework-independent TypeScript client. It handles CSRF and same-origin cookies. The `assistant` export covers login and chat. The `product` export covers capabilities, tasks and reviews. [`clients/openclaw.ts`](../clients/openclaw.ts) keeps legacy compatibility exports.
