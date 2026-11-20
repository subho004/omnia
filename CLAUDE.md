# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

A **uv-managed Python package** (`claw_orchestrator`) implementing a **FastAPI/ASGI** service with:
- **PostgreSQL 18** on Docker Compose for metadata (persisted in `./db/` bind mount)
- **Server-rendered HTML** (Jinja2 templates), no frontend framework build
- **NemoClaw runtime adapter** for native OpenClaw container orchestration via OpenShell

### Directory Structure

```
Project structure:
  src/claw_orchestrator/
    app.py              # Main FastAPI app, auth, proxy routes
    frontend_api.py     # Curated /api/assistant routes
    auth.py             # JWT auth, session mgmt, CSRF
    config.py           # Settings validation
    db.py               # Database connection wrapper
    runtime/            # NemoClaw adapter (nemoclaw.py)
  clients/              # Frontend code (no build step)
  compose.yaml          # PostgreSQL service
  infra/                # Docker Compose patches, migrations, patches
  scripts/              # Local setup, serve
  tests/                # pytest tests
```

## Essential Commands

```bash
# Initial setup
uv sync --locked
mkdir -p .certs
mkcert -cert-file .certs/local.pem -key-file .certs/local-key.pem app.localhost '*.claw.localhost' localhost 127.0.0.1 ::1

# Database setup
docker compose up -d --wait db
docker compose ps db

# Serve application
uv run --locked scripts/serve.py
uv run --locked python scripts/setup_local.py  # Generates .env

# Database migrations run automatically on API startup (via db.py)

# Lint
uv run --locked ruff check src scripts tests

# Test
uv run --locked pytest -q   # Run all tests
uv run --locked pytest tests::test_<module>  # Run specific test
```

## Configuration (`.env`)

```bash
POSTGRES_DB=claw_orchestrator
POSTGRES_USER=claw_orchestrator
POSTGRES_APP_PASSWORD=<strong>  # Required
JWT_SECRET=<min 32 random bytes>
CONTROL_ORIGIN=https://app.localhost:8443
INSTANCE_DOMAIN=claw.localhost
PUBLIC_PORT=8443
SESSION_SECONDS=3600
INFERENCE_PROVIDER=lmstudio  # or openrouter

# OpenRouter (gitignored .env):
OPENROUTER_API_KEY=<key>  # mode 600
```

## Database

PostgreSQL 18 stores orchestrator metadata in `./db/`. Host: `127.0.0.1:5432`.

```sql
-- Initialize roles and schemas (infra/postgres/init-app.sql)
CREATE ROLE claw_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE SCHEMA claw AUTHORIZATION claw_api;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER ROLE claw_api SET search_path TO claw, public;
```

Connection string (for API): `postgresql://claw_api:{POSTGRES_APP_PASSWORD}@127.0.0.1:5432/claw_orchestrator`

Run `docker compose exec db psql -U claw_api -d claw_orchestrator` for SQL access.

## Authentication Flow

### Demo Login (cookie JWT)
1. User visits `https://app.localhost:8443/`
2. Selects user1/user2 from dropdown
3. POST `/auth/login` with `{ user: "user1" | "user2" }` and CSRF token
4. Server sets `__Host-claw_session` cookie with JWT
5. Response redirects to `/` (login page) or returns `200 OK` for AJAX

### Session Management
- JWT signed with HS256, issued to `claw-control` audience
- Claims require: `iss`, `aud`, `iat`, `nbf`, `exp`, `jti`
- Session stored in DB with `expires_at`, revoked via `revoke()`
- Demo sessions: 3600 seconds TTL by default

### Switch User
- POST `/auth/switch` with same CSRF token
- Revokes previous session via `connections.revoke()`

### Logout
- POST `/auth/logout`
- Removes `__Host-claw_session` cookie
- Calls `Auth.revoke()` on DB

### Frontend API Access
- Same cookie JWT with `claw-control` audience
- POSTs require `X-CSRF-Token` header
- Origin must match `CONTROL_ORIGIN`
- Sessions persist via `X-Workspace-Session` header (SHA256 of sid)

## API Routes

### Authentication (`/api/assistant/auth`)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/assistant/auth/login` | POST | Demo login with user selection |
| `/api/assistant/auth/switch` | POST | Switch between user1/user2 |
| `/api/assistant/auth/logout` | POST | Logout current user |
| `/api/assistant/auth/me` | GET | Current user info |
| `/api/assistant/auth/csrf` | GET | CSRF token |

### Instance Management (`/api/assistant/instance`)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/assistant/instance` | GET | Status of current user's instance |
| `/api/assistant/instance` | POST | Create new instance (CREATE) |

### Curated Assistant API (`/api/assistant/*`)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/assistant/capabilities` | GET | Feature readiness |
| `/api/assistant/sessions` | GET/POST | List/create sessions |
| `/api/assistant/history` | GET | Session message history |
| `/api/assistant/messages` | POST | Send chat message |
| `/api/assistant/runs/abort` | POST | Abort running task |
| `/api/assistant/events` | GET | SSE stream of live events |
| `/api/assistant/tasks` | GET/POST | List/create tasks |
| `/api/assistant/approvals` | GET | Pending approvals |
| `/api/assistant/approvals/{id}` | GET | Approval details + review token |
| `/api/assistant/approvals/{id}/resolve` | POST | Approve/deny |

### Legacy OpenClaw API (`/api/openclaw/*`) - Developer access only
- `/tasks` - Task status/management
- `/approvals` - Pending approvals history
- `/automations` - Schedule/management

## Instance Model

- **UUID**: Server-generated UUIDv4, preserved across restarts
- **Container Name**: `openshell-{uuid}` (OpenShell convention)
- **Sandbox Name**: `co-{uuid[:16]}` (NemoClaw 19-char limit)
- **Volume Name**: `openclaw-data-{uuid}`
- **Gateway Port**: Base port + (user1=0, user2=1)
- **Origin**: `https://{uuid}.claw.localhost:{public_port}/`

## NemoClaw Runtime Integration

### Provisioning Flow
```
User creates instance → POST /api/assistant/instance
  ↓
Durable job in PostgreSQL
  ↓
Worker process runs provisioning:
  1. sandbox (onboard native container)
  2. probe (wait for phase=Ready)
  3. patch_startup (apply hash-pinned rootfs fix)
  4. configure_gateway (trusted-proxy auth for user1)
  5. forward (private Unix socket SSH forward to agent port)
  6. prepare_workspace_access (tenant-only exec policy)
  7. prepare_automation_access (admin device pairing)
  ↓
Instance status transitions: not_created → provisioning → ready
```

### Environment (per instance)
```bash
CLAW_ORCHESTRATOR_INSTANCE_ID=<uuid>
NEMOCLAW_GATEWAY_PORT=<port>
OPENSHELL_GATEWAY=<gateway-port>
OPENSHELL_WORKSPACE=default
NEMOCLAW_PROVIDER=openrouter  # or lmstudio
OPENROUTER_API_KEY=<from .env>  # Only for openrouter
```

### Runtime Checks
- `GET /api/assistant/runtime` - Runtime availability status
- `GET /readyz` - Database and runtime readiness
- `GET /healthz` - API health

### Container Management
```bash
nemoclaw sandbox {name} get     # Get sandbox status
nemoclaw sandbox exec ...       # Execute command
docker inspect {container}      # Inspect
```

## Security Constraints

### Critical Security Rules
```
- Demo login loopback-only: bind to 127.0.0.1
- HTTPS required with self-signed cert (mkcert)
- proxy_headers=False in uvicorn (don't trust client headers)
- Strict-Origin Referrer-Policy
- CORS: form-action only, no wildcards
- JWT: HS256, issuer="claw-orchestrator", strict validation
- Keep orchestrator JWTs OUT of:
  - Upstream HTTP traffic
  - JavaScript storage (localStorage/sessionStorage)
  - URLs and logs
```

### Instance Isolation
- User resolves ownership from DB lookup
- Mount only that user's volume: `openclaw-data-{uuid}`
- Never mount: orchestrator DB, host home, Docker socket, runtime creds
- Browser origin per instance prevents cross-tab leakage
- Revoke proxy connections on logout

### Proxy Authentication
```python
# app.py middleware
async def response_policy(request):
    expected_session = request.headers.get("x-workspace-session")
    if expected_session and request.url.path.startswith(("/api/", "/auth/")):
        principal = await auth.authenticate(cookie_jwt, "claw-control")
        if workspace_session(principal.sid) != expected_session:
            raise APIError(409, "SESSION_CHANGED")
```

### Automated Rules (from `update-config` skill)
- Allow: `uv`, `docker compose`, pytest, ruff
- Move: auth permissions to user settings
- Set: `LOCAL_CLIENT_ADDRESS` for proxy routing

## API Gateway Protocol

Frontend API uses protocol v4:
- Routes prefixed `/api/assistant/`
- `OwnedGateway` binds to authenticated instance
- `Guard` validates ownership and permissions
- `OwnedGateway` opens/closes for request lifecycle

### Event Handling (SSE)
```typescript
// frontend/clients/assistant.ts
async function subscribe(session_key, handlers) {
  const source = new EventSource(`/api/assistant/events?session_key=${session_key}`);
  
  source.addEventListener("ready", () => handlers.onReady());
  source.addEventListener("chat", (e) => handlers.onChat(parse(e.data)));
  source.addEventListener("activity", (e) => handlers.onActivity(e.data));
  source.addEventListener("session.approval", (e) => handlers.onApproval(e.data));
  source.addEventListener("approval.replay", (e) => handlers.onApprovalReplay(e.data));
  
  source.addEventListener("error", (e) => {
    const event = JSON.parse(e.data);
    if (event.code === "SESSION_ENDED") handlers.onSessionEnded();
    else handlers.onReconnectRequired();
  });
}
```

### Review Tokens
- Generated on `/approvals/{id}` GET
- Consumed on `/approvals/{id}/resolve` POST
- Must be from same session
- Lifetime: 24 hours (rotate on logout)

## Migration System

Migrations stored in `src/claw_orchestrator/migrations/`:
```
001_initial_create_tables.sql
002_add_indexes.sql
```

Run transactionally on API startup via `db.py::Database.open()`

To apply:
```bash
# Add migration file to migrations/
# Restart API - migrations run automatically
```

## Testing

```bash
uv run --locked pytest -q   # Run all tests
uv run --locked pytest tests::test_<module>   # Run specific test
```

Tests require local PostgreSQL (from `docker compose up db`).

### Test Types
- **Unit tests**: Database operations, auth, validation
- **Integration tests**: API routes, session handling
- **Frontend tests**: Workspace rendering, auth page, API client interaction

Run frontend UI fixture for browser testing:
```bash
uv run --locked python tests/serve_ui_fixture.py
```

## NemoClaw Runtime Features

### Gateway Configuration
```python
{
  "mode": "trusted-proxy",
  "identityScopes": {"user1": ["operator.admin"], "user2": ["operator.admin"]},
  "trustedProxy": {
    "userHeader": "x-claw-user",
    "allowUsers": ["user1", "user2"],
    "allowLoopback": True,
    "requiredHeaders": ["x-claw-proxy"],
  },
}
```

### Browser Configuration
- Headless: true
- No sandbox
- Private network access: false

### Provider Configuration
- Default: `nvidia/nemotron-3-ultra-550b-a55b:free`
- OpenRouter requires `OPENROUTER_API_KEY`
- Context: 1M tokens (configurable)
- Max tokens: 4096

## Feature Readiness

Check `GET /api/assistant/capabilities`:
```json
{
  "api_version": "0.1.0",
  "runtime_validation": "verified_2026-10-30",
  "features": {
    "chat_sessions": {"state": "implemented"},
    "task_status": {"state": "implemented"},
    "reviews": {"state": "disabled"},
    "tenant_connections": {"state": "not_implemented"},
    "browser_workflows": {"state": "implemented"},
    "browser_takeover": {"state": "not_implemented"},
    "schedules": {"state": "implemented"},
    "calendar": {"state": "not_implemented"}
  }
}
```

## Development Workflow

### Start
```bash
uv sync --locked
docker compose up -d db
uv run --locked scripts/serve.py
```

### Browser Access
- Control origin: `https://app.localhost:8443`
- Instances: `https://{uuid}.claw.localhost:8443`

### Debugging
```bash
docker compose logs -f db
docker compose logs -f app

# Check database
docker compose exec db psql -U claw_api -d claw_orchestrator
```

## Common Pitfalls

### Session Not Persisting
- Check `POSTGRES_APP_PASSWORD` is set
- Verify DB health: `docker compose exec db pg_isready`
- Check JWT_SECRET is at least 32 bytes

### Runtime Not Ready
- Check `infra/runtime-versions.json` has correct `nemoclaw_source_revision`
- Check `OPENROUTER_API_KEY` if using openrouter
- Verify `NEMOCLAW_PROVIDER` matches config

### Cross-tenant Access
- Ensure instance origin validation works
- Check `x-workspace-session` header matches logged-in user
- Review database schema ownership

### Proxy Errors
- Ensure `proxy_headers=False` in uvicorn
- Check `x-claw-proxy` header on downstream requests
- Verify `x-claw-user` for identity lookup

## Runtime Limitations

- Native container names: 64 chars (OpenShell), NemoClaw sandboxes: 19 chars
- Agent ports: 1024-65535
- Instance UUIDs: Server-generated, preserved across replacement
- Browser tab switching: Requires same-origin isolation (per-uuid hostnames)
