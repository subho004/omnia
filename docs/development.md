# Development

## Commands

```sh
uv sync --locked
uv run --locked ruff check src scripts tests      # lint (E, F, I, UP, B, ASYNC; line length 100)
uv run --locked pytest -q                         # full suite
uv run --locked pytest tests/test_control.py -q   # one module
node --test tests/browser-guard.test.mjs          # browser guard plugin
```

Python 3.12+, `asyncio_mode = auto`. Dependencies are in `pyproject.toml` and locked in `uv.lock`.

## Tests

Tests need the Compose database (`docker compose up -d --wait db`) and the bootstrap credentials in `.env`. Each run creates a uniquely named disposable PostgreSQL database and removes only that database afterwards. The working application's tables are never truncated. No test invokes a model.

`tests/conftest.py` builds the app with a stub `TestRuntime` (fixed upstream, fake container names), so tests do not need NemoClaw or Docker workloads.

| Test module | Covers |
| --- | --- |
| `test_control.py` | Login, switch, logout, instance creation, launch tickets, CSRF and Origin |
| `test_frontend_api.py` | Curated routes, SSE, session revocation, review-token binding, replay and expiry, against a real local WebSocket RPC peer |
| `test_automations.py`, `test_automation_errors.py` | Schedules, ownership, strict input, revision conflicts, idempotency, concurrent runs, lost acknowledgements |
| `test_browser_api.py`, `test_browser_bridge.py`, `test_browser_guard.py`, `browser-guard.test.mjs` | Browser routes, bridge relay, guard plugin |
| `test_egress_proxy.py` | Private-range, port and DNS denial |
| `test_private_ingress.py`, `test_websocket.py`, `test_connections.py` | Unix-socket ingress, WebSocket proxy, revocation of live connections |
| `test_runtime_binding.py`, `test_reconciliation.py` | Sandbox/UUID binding, startup and periodic recovery |
| `test_chat_activity.py`, `test_presentation.py` | Native-frame projection, brand and credential scrubbing |
| `test_inference.py`, `test_local_inference.py` | OpenRouter preflight, LM Studio route setup |
| `test_workspace.py` | Workspace rendering and the auth page |

Limits to keep in mind: proxy tests use controlled upstreams, so they do not prove container or filesystem isolation. Node is required for the Ed25519 gateway identity helper.

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/setup_local.py` | Generate `.env` once (mode 0600, random secrets) |
| `scripts/setup_runtime.py [--activate]` | Install and verify the pinned runtime under `.state/`. `--activate` writes the readiness marker. |
| `scripts/serve.py` | Run the app on loopback HTTPS |
| `scripts/setup_local_inference.py [--user]` | Point retained instances at the local LM Studio route |
| `scripts/setup_automation_access.py` | Pair the scheduler identity for existing instances |
| `scripts/setup_workspace_access.py` | Apply the tenant-only workspace execution policy to existing instances, with private backups |
| `scripts/check_inference.py [--smoke]` | OpenRouter credential, quota and model checks. `--smoke` sends at most five free requests. |
| `scripts/check_cdp_zepto.py`, `scripts/test_cdp_with_egress_proxy.py` | Manual browser-protocol and proxy diagnostics |

## Conventions

- Raise `APIError(status, code, message)` for client-visible failures. Messages must be generic and codes stable. Never include runtime, CLI or upstream text.
- Every new mutating route needs the Origin and CSRF checks and an `extra="forbid"` input model.
- Resolve the instance from the database through `owned_gateway`. Never accept a tenant id, URL or token from the client.
- Project native data through `presentation` or an explicit view function before returning it.
- Keep orchestrator JWTs out of upstream requests, logs, URLs and browser storage.
- Add a migration as the next numbered SQL file. Never edit an applied one.
- Do not change the runtime manifest hashes without re-qualifying the matching patch.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| App exits at startup | `Settings` validation: `JWT_SECRET` length, `POSTGRES_APP_PASSWORD`, `CONTROL_ORIGIN` host and port matching `PUBLIC_PORT` |
| `serve.py` says to generate certificates | Run the mkcert command in Getting started |
| Browser does not trust the certificate | Install the mkcert local CA (`mkcert -install`) |
| Database errors or 503s | `docker compose ps db`, `docker compose exec db pg_isready`. Do not delete `db/`. |
| `RUNTIME_NOT_CONFIGURED` | Run `scripts/setup_runtime.py --activate`. The marker's `source_revision` must match the manifest. |
| Instance stuck `unavailable` | The worker re-probes every 10 seconds. Check Docker, the sandbox phase and the private forward. |
| Instance `failed` with `RECOVERY_LIMIT` | The job exhausted 3 attempts. Inspect the sandbox directly. Exception text is deliberately not logged. |
| `409 SESSION_CHANGED` | Another tab switched users. Reload. |
| `CLIENT_ATTRIBUTION_UNAVAILABLE` | Set `LOCAL_CLIENT_ADDRESS` to this host's routed LAN address |
| Cross-tenant access suspected | Verify the Host UUID, `__Host-claw_proxy` `iid` claim and the `instances.owner_user_id` row all agree |
