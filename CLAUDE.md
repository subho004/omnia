# CLAUDE.md

Guidance for Claude Code in this repository. Full documentation is in [docs/](docs/README.md). When this file and the code disagree, the code wins.

## What this is

Morrow (`claw_orchestrator`): a uv-managed FastAPI/ASGI control plane. Each demo user (`user1`, `user2`) gets one persistent OpenClaw instance, managed through NemoClaw and OpenShell. PostgreSQL 18 (Docker Compose, `./db/` bind mount) holds metadata. The UI is server-rendered Jinja2 plus plain ES modules, with no build step.

## Commands

```bash
uv sync --locked
uv run --locked scripts/setup_local.py                     # generate .env (never overwrites)
mkdir -p .certs && mkcert -cert-file .certs/local.pem -key-file .certs/local-key.pem \
  app.localhost '*.claw.localhost' localhost 127.0.0.1 ::1
docker compose up -d --wait db
uv run --locked python scripts/setup_runtime.py --activate # pinned NemoClaw/OpenShell runtime
uv run --locked scripts/serve.py                           # https://app.localhost:8443

uv run --locked ruff check src scripts tests
uv run --locked pytest -q                                  # needs the Compose db
uv run --locked pytest tests/test_control.py -q            # one module
node --test tests/browser-guard.test.mjs
uv run --locked python tests/serve_ui_fixture.py           # simulated UI at :8444
```

Migrations (`src/claw_orchestrator/migrations/*.sql`) run on API startup via `Database.open()`. Add the next numbered file; never edit an applied one.

## Layout

```
src/claw_orchestrator/
  app.py               app factory, lifespan, middleware, /auth/*, /api/instance*, tenant app
  boundary.py          host/TLS/loopback enforcement, instance id from Host
  config.py auth.py db.py errors.py
  instances.py         instance rows, launch tickets   provisioning.py  job worker, recovery
  runtime/             Runtime protocol + NemoClaw adapter (nemoclaw.py)
  proxy.py             HTTP/WS proxy to the instance   connections.py   revocation Guard
  gateway.py           OpenClaw protocol v4 WS RPC client
  frontend_api.py feature_api.py automations.py browser_api.py   /api/assistant/*
  egress_proxy.py browser_bridge.py                    public-only browser egress
  chat_activity.py presentation.py                     safe projection of native data
  templates/ static/                                   server-rendered UI
clients/               TypeScript clients (assistant.ts preferred)
infra/                 runtime-versions.json manifest, patches, browser guard plugin, postgres init
scripts/ tests/ docs/ (docs/agentdocs = planning notes, docs/FEATURE_RESEARCH.md)
```

## Settings (`.env`, see `.env.example` and docs/configuration.md)

Required: `POSTGRES_APP_PASSWORD`, `JWT_SECRET` (32+ chars). `POSTGRES_PASSWORD` is required by Compose. `CONTROL_ORIGIN` must be `https://app.localhost:{PUBLIC_PORT}`, `INSTANCE_DOMAIN` must be `claw.localhost`, and `SESSION_SECONDS` must be 1..3600. `INFERENCE_PROVIDER` is `lmstudio` (default) or `openrouter` (needs `OPENROUTER_API_KEY`, and the model must be an explicit `:free` one). The runtime manifest `infra/runtime-versions.json` pins versions, patch hashes and the LM Studio model (`qwen/qwen3.6-27b`).

## Database

The API connects as `claw_api` (non-superuser, owns schema `claw`, search_path `claw,public`) to `127.0.0.1:5432`. The bootstrap admin is `claw_admin`, and the API never uses it. SQL shell: `docker compose exec db sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`. Never delete `./db/`.

Tables in use: `users`, `sessions`, `instances` (unique `owner_user_id`), `provisioning_jobs`, `launch_tickets`, `approval_reviews`, `automation_mutations`. `automations`, `automation_members` and `browser_connections` exist but no live route uses them.

## Auth and routes

- Cookies (`Secure`, `HttpOnly`, `SameSite=Lax`, `__Host-`): `__Host-claw_prelogin` (10 min), `__Host-claw_session` (audience `claw-control`), `__Host-claw_proxy` (audience `claw-proxy`, instance origin only). JWTs are HS256 with issuer `claw-orchestrator` and claims `iss aud iat nbf exp jti`. A live, unrevoked `sessions` row is also required.
- Control origin routes: `GET /auth/csrf`, `POST /auth/login|switch|logout`, `GET /auth/me`, `GET|POST /api/instance`, `POST /api/instance/launch`, `GET /api/runtime`, `/healthz`, `/readyz`, `/workspace`.
- POSTs need the exact `Origin` equal to `CONTROL_ORIGIN` plus the CSRF token (`X-CSRF-Token` header or `csrf` field). `X-Workspace-Session` (SHA-256 of `"claw-workspace:" + sid`) mismatch returns `409 SESSION_CHANGED`.
- Curated API under `/api/assistant`: `capabilities`, `sessions`, `history`, `messages`, `runs/abort`, `events` (SSE), `tasks[/id[/cancel]]`, `approvals[/id[/resolve]|/history]`, `automations*`, `browser`, `browser/connect|disconnect|tabs`, `openapi.json`. The same routes are mounted at `/api/openclaw` for developers and are not customer-facing.
- Instance origin `https://{uuid}.claw.localhost:{port}`: `POST /__orchestrator/launch` consumes a 30 second single-use ticket. Everything else is proxied after cookie and ownership checks.

## Security rules

- Uvicorn runs on `127.0.0.1` with HTTPS and `proxy_headers=False`. `BoundaryMiddleware` requires a loopback client, https/wss and an exact Host.
- Never accept a tenant id, URL or token from a client. Resolve the instance from the database (`owned_gateway`, `authorize_proxy`).
- Keep orchestrator JWTs out of upstream traffic, URLs, logs and browser storage. Strip client identity headers in `proxy.upstream_headers`.
- Never mount the orchestrator database, host home, Docker socket or runtime credentials into a tenant. Each instance mounts only `openclaw-data-{uuid}`.
- Never log or return runtime exception text or CLI output. Use stable `APIError` codes with generic messages.
- Input models use `extra="forbid"`. Bodies are capped at 8 KiB (auth) and 32 KiB (`/api/assistant`).
- Do not scale beyond one uvicorn worker. The runtime adapter keeps in-process state.

## Instance model

UUIDv4 generated server side and stable across replacement. Sandbox name `co-{uuid.hex[:16]}` (NemoClaw's 19 character limit), volume `openclaw-data-{uuid}`, container name recorded after provisioning (`openshell-...`). Status: `pending`, `provisioning`, `ready`, `failed`, `unavailable`. The worker leases a job for 660 seconds, allows 3 attempts (then `RECOVERY_LIMIT`), and re-probes `unavailable` instances every 10 seconds. Steps are in docs/runtime-and-provisioning.md.

## Feature readiness

`GET /api/assistant/capabilities` is authoritative. Currently implemented: `chat_sessions`, `task_status`, `schedules`. Partial: `workflow_continuation`. Needs validation: `browser_workflows`. Disabled: `reviews`. Not implemented: `tenant_connections`, `calendar`, `browser_takeover`, `email`, `memory`, `routines_channels_specialists`.

## Pitfalls

- `RUNTIME_NOT_CONFIGURED`: run `scripts/setup_runtime.py --activate`. The `.state/runtime-ready.json` revision must match the manifest.
- `409 SESSION_CHANGED`: another tab switched users.
- `CLIENT_ATTRIBUTION_UNAVAILABLE`: set `LOCAL_CLIENT_ADDRESS` to the host's routed interface address.
- Tests need the Compose db and `.env` credentials. They create and drop a disposable database and never invoke a model.
