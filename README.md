# Morrow / Claw Orchestrator

Local NemoClaw/OpenClaw orchestration prototype using uv, FastAPI, and PostgreSQL.

Implemented: demo cookie authentication, durable own-instance creation, and a curated frontend API for chat/sessions, native task status/cancellation, and presentation-bound reviews. Visit Morrow opens the authenticated prototype frontend: chat, sessions, Automations with schedules/run history, review decisions/history, and feature readiness. A separate frontend can also use the tracked TypeScript client without receiving gateway credentials. PostgreSQL metadata and both tenant volumes are retained.

**Current local runtime (1 November):** both retained workspaces select LM Studio `qwen/qwen3.6-27b` with 200000 configured context, 4096 output and no model fallback. Native browser navigation/input and a Wikipedia search passed through Morrow with raw tool-result checks. The exact Zepto/Monster prompt reached the requested host and observed HTTP429; no product availability was verified. Private ingress and browser egress recover after supported native restarts, preserving original UUIDs and volumes. External calendar/merchant workflows remain unqualified. See the local [browser-agent qualification](agentdocs/17-browser-agent-qualification.md) for evidence and limits.

## Start the local application

```sh
uv sync --locked
uv run --locked scripts/setup_local.py
docker compose up -d --wait db
mkdir -p .certs
mkcert -cert-file .certs/local.pem -key-file .certs/local-key.pem app.localhost '*.claw.localhost' localhost 127.0.0.1 ::1
uv run --locked scripts/serve.py
```

Open [Morrow](https://app.localhost:8443). `mkcert` must already be installed; follow its local CA setup if your browser does not trust the generated certificate. The server binds only to `127.0.0.1`, requires HTTPS, and does not trust client-supplied proxy headers. Hostname selection is checked against the authenticated user's instance; tenant IDs do not appear in URL paths.

The setup script generates `.env` with private permissions and random database/JWT secrets. It preserves an existing `.env`; compare it with `.env.example` when settings change. Demo login intentionally lets a local visitor choose either identity and is not production authentication.

## Automations

Open Automations in the workspace sidebar. Search schedules, filter active/paused jobs, inspect run history, and create interval, cron/time-zone or one-time schedules. New automations start paused unless enabled; run-now and deletion require confirmation. Managed heartbeat/maintenance entries retain their native rules. Results stay in the workspace; external service automations are not enabled. The existing task ledger API remains available.

For an already-running checkout after updating code, restart the API and run `uv run --locked scripts/setup_automation_access.py` to pair its dedicated server scheduler identities. New provisioning includes this setup. Native admin pairing is not granted to browser devices.

## API for a separate frontend

Serve the separate frontend project at the same public origin as the API: `https://app.localhost:8443`. Authentication remains in Secure, HttpOnly cookies; POSTs require the exact Origin and `X-CSRF-Token` from `GET /auth/csrf`. Arbitrary cross-origin development servers are not enabled.

| API surface | Routes |
| --- | --- |
| Feature readiness | `GET /api/assistant/capabilities` |
| Sessions | `GET/POST /api/assistant/sessions`; `GET /api/assistant/history` |
| Automations | `GET/POST /api/assistant/automations`; `GET /automations/runs`; `GET /automations/{id}` and `POST /automations/{id}/update`, `/run`, `/remove` under the same prefix |
| Chat | `POST /api/assistant/messages`; `POST /api/assistant/runs/abort` |
| Live events | `GET /api/assistant/events?session_key=...` (SSE; optional `include_approvals=true`) |
| Tasks | `GET /api/assistant/tasks`; `GET /tasks/{id}`; `POST /tasks/{id}/cancel` under the same prefix |
| Reviews | `GET /api/assistant/approvals?session_key=...`; `GET /approvals/{id}`; `POST /approvals/{id}/resolve`; `GET /approvals/history` under the same prefix |
| Schema | Authenticated `GET /api/assistant/openapi.json` |

Use [clients/assistant.ts](clients/assistant.ts), a framework-independent browser client. It obtains CSRF tokens and uses same-origin cookies. The `assistant` export handles login/chat; `product` handles capabilities/tasks/reviews. The server selects the caller's instance; there is no client-selected tenant URL, arbitrary RPC method, or gateway token.

The API scope follows **FEATURE_RESEARCH.md section 4**. Calendar, managed browser/takeover, movie tickets, Zepto, and provider connection adapters remain explicitly unimplemented or unvalidated in capabilities. Native decision history is not a verified external booking/order receipt. Local endpoint examples, review integrity, stream/reconnect behavior, and planned provider/browser contracts are in the intentionally ignored [frontend API guide](agentdocs/09-frontend-api.md).

## Local PostgreSQL

Configure secrets with the setup script above, or copy `.env.example` to `.env` and fill all required secrets manually. Then start the database:

```sh
docker compose up -d --wait db
docker compose ps db
```

Compose refuses to start if either database password is empty. PostgreSQL 18 stores its cluster under `./db/18/docker/` through a bind mount from this repo's `./db/` to `/var/lib/postgresql`. Both `/db/` and `.env` are gitignored. The mount follows the [official PostgreSQL image's PostgreSQL 18 layout](https://hub.docker.com/_/postgres). The health check verifies TCP readiness and the application role's login.

The host endpoint is `127.0.0.1:5432`, with database `claw_orchestrator`, bootstrap administrator `claw_admin`, and non-superuser API role `claw_api`. The initialization SQL creates the API role and its private `claw` schema; migrations run transactionally on API startup. For a future API container on the same Compose network, use hostname `db` and port `5432`. Never attach tenant workloads to the database network.

Open an SQL shell without installing PostgreSQL locally:

```sh
docker compose exec db sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Stop/remove the container while keeping database files:

```sh
docker compose down
```

Recreating the database container reuses `./db/`. Initialization variables apply to a new cluster; changing `.env` does not rotate credentials or rename an existing database. Make such changes through PostgreSQL. Use database-aware backups and a supported upgrade procedure before changing PostgreSQL major versions. Do not delete `db/` to resolve a startup problem.

The API never uses the bootstrap administrator credentials. For an existing cluster created before the app-role initializer was added, apply `infra/postgres/init-app.sql` once using the administrator; do not delete `db/` or expect first-start initialization to rerun.

## Checks

```sh
uv run --locked ruff check src scripts tests
uv run --locked pytest -q
```

Tests require the local Compose database and `.env` bootstrap credentials. Each run creates a uniquely named disposable PostgreSQL database and removes only that test database afterwards. They do not truncate the working application's tables. Proxy tests use controlled HTTP/WS upstreams; these tests do not establish real NemoClaw container or filesystem isolation. Frontend tests also run a real local WebSocket RPC peer, validate SSE revocation and review-token binding/replay/expiry, and never invoke a model. Node is required for the private Ed25519 gateway identity helper.

## Optional OpenRouter and managed runtime

OpenRouter is an optional earlier route, not the current selected local route. Store `OPENROUTER_API_KEY` only in gitignored mode-0600 `.env`, with `INFERENCE_PROVIDER=openrouter`; see `.env.example`. The owner-selected endpoint is `nvidia/nemotron-3-ultra-550b-a55b:free`, with a configured 1,000,000-token context and 4096-token output limit. The context size matches current provider metadata; small smoke tests do not qualify a full 1M-token request. This endpoint advertises tools but no schema-enforced JSON output. The optional JSON-schema smoke check is explicitly skipped for unsupported models; it is not reported as passing. No paid or random model fallback is configured.

```sh
# Credential, quota and current free model/tool metadata; no inference.
uv run --locked python scripts/check_inference.py
# Optional: at most five synthetic free-model requests, no automatic retries.
uv run --locked python scripts/check_inference.py --smoke
```

Before the owner selected Nemotron on 30 October, Dots passed short text, automatic tool calling with exact arguments, a streamed tool-result reply, JSON schema output, and roughly 3200-token context recall. Named-function forcing returned 404; automatic selection worked. Xing4.0 returned upstream Phala 429s. These are direct-provider tests, not native Morrow chat or full-context qualification. The account initially reported 50 free requests/day shared by app users.

The current route uses `INFERENCE_PROVIDER=lmstudio` and a private mode-0600 `LMSTUDIO_API_KEY` in `.env`. Run `uv run --locked python scripts/setup_local_inference.py` as an operator to configure the retained workspaces, or add `--user user1` / `--user user2` for one owner. It validates the endpoint-limited native provider, stores environment references rather than raw credentials in tenant configuration, preserves original identities/data, and uses supported stop/start with browser-bridge readiness checks. No key is sent to the frontend. New provisioning/replacement still needs its documented local-provider setup and qualification; do not infer a complete replacement lifecycle from these retained-runtime checks.

Native OpenShell container names are accepted; our instance UUID remains stable and the desired data volume is `openclaw-data-{uuid}`. NemoClaw limits logical sandbox names to 19 characters, so the adapter uses `co-` plus the first 16 UUID hex characters, with a unique DB constraint. The full UUID remains authoritative. The reviewed local patch in `infra/nemoclaw-state-volume.patch` binds that short name to the full UUID and fails closed if its binding is missing. It is an explicit local upstream customization, not an upstream-supported naming flag. Exact attachment was verified for two instances; supported stop/start was verified; full replacement/browser dependency packaging remains an open qualification gate.

Local plans, runtime findings, and agent instructions live in the intentionally gitignored `agentdocs/` and `AGENTS.md`. Private runtime downloads, source checkouts, and logs live under `.state/`.

## Prototype frontend

Sign in as User1 or User2 and click **Visit Morrow**. The server renders `/workspace` even while the runtime is unavailable. It uses plain HTML/CSS/JavaScript modules, so the existing uv command serves the entire app with no frontend build step.

The page and every API/stream request are bound to the current login session with a non-secret `X-Workspace-Session` marker. Switching users in another tab clears old messages, drafts and review tokens. No JWT or private content is stored in localStorage/sessionStorage. All mutating requests use CSRF protection; streamed responses use cookie-authenticated fetch with the same session fence. Unavailable provider/browser features are visibly disabled.

For browser QA without a model or external actions, an explicit disposable fixture is available:

```sh
uv run --locked python tests/serve_ui_fixture.py
```

It serves `https://app.localhost:8444` with a visible simulated-results notice and a unique disposable PostgreSQL database. Stop it with Ctrl+C to remove only that database. It never creates tenant containers, uses working tenant data, invokes a model, or performs a provider action. Cookies for the same hostname are shared across ports: use a separate browser profile if you need to keep a simultaneous normal login. This fixture is never used as a production fallback.

Preferred client: `clients/assistant.ts`. Legacy developer endpoints and `clients/openclaw.ts` compatibility exports remain available; they are not customer-facing navigation.
