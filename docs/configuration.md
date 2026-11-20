# Configuration

Settings come from environment variables and `.env`, loaded by `pydantic-settings` in `config.py`. Unknown variables are ignored. `scripts/setup_local.py` generates a working `.env`. `.env.example` lists every key.

## Settings

| Variable | Default | Notes |
| --- | --- | --- |
| `POSTGRES_DB` | `claw_orchestrator` | Database name |
| `POSTGRES_USER` | `claw_admin` (`.env.example`) | Bootstrap admin. Used by Compose and tests, never by the API. |
| `POSTGRES_PASSWORD` | none | Required by Compose |
| `POSTGRES_APP_PASSWORD` | none | **Required.** Password for the `claw_api` role. |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `127.0.0.1` / `5432` | |
| `JWT_SECRET` | none | **Required.** At least 32 characters. |
| `DEMO_AUTH_ENABLED` | `false` | Set `true` in `.env.example` for local demos |
| `CONTROL_ORIGIN` | `https://app.localhost:8443` | Must be `https`, host `app.localhost`, no path, query, credentials, and port equal to `PUBLIC_PORT` |
| `INSTANCE_DOMAIN` | `claw.localhost` | Must be exactly `claw.localhost` |
| `PUBLIC_PORT` | `8443` | Listen port and origin port |
| `SESSION_SECONDS` | `3600` | Must be 1 to 3600 |
| `LOCAL_CLIENT_ADDRESS` | auto | Routed interface address of this host, used for proxy attribution. Must not be loopback, unspecified or multicast. Auto-detected by a UDP connect that sends no packet. |
| `INFERENCE_PROVIDER` | `lmstudio` | `lmstudio` or `openrouter` (`.env.example` ships `openrouter`) |
| `LMSTUDIO_API_KEY` | none | Optional if the local server needs no auth |
| `OPENROUTER_API_KEY` | none | Required only for OpenRouter. Keep `.env` mode 0600. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Fixed to this value |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Must match `vendor/model:free` |
| `OPENROUTER_CONTEXT_WINDOW` | `1000000` | 32768 to 1000000 |
| `OPENROUTER_MAX_TOKENS` | `4096` | 64 to 8192 |
| `EGRESS_PROXY_HOST` / `EGRESS_PROXY_PORT` | `0.0.0.0` / `18490` | Public-only egress proxy listener. See [Browser and egress](browser-and-egress.md). |

The app fails to start with a clear error when validation fails (control origin, JWT length, empty app password, session range, non-`claw.localhost` domain).

## Runtime manifest

`infra/runtime-versions.json` (not `.env`) pins the NemoClaw and OpenShell versions and checksums, the inference endpoint, model and context for the LM Studio route, sampling parameters, the gateway base port, and patch file hashes. See [Runtime and provisioning](runtime-and-provisioning.md#pinned-toolchain).

## Local state (`.state/`, gitignored)

| Path | Contents |
| --- | --- |
| `.state/bin/openshell` | Pinned OpenShell binary |
| `.state/research/nemoclaw` | NemoClaw source checkout |
| `.state/runtime-ready.json` | Activation marker (see Getting started) |
| `.state/instances/` | Per-instance metadata (mode 0700) |
| `.state/gateway-devices/{uuid}/` | Host-only gateway identities, including the automation identity |
| `/tmp/co-orch-{hash}/` | Private Unix sockets for instance ingress (mode 0700) |

Other gitignored paths: `db/`, `.env*` (except `.env.example`), `.certs/`, `.secrets/`.

## Server process

`scripts/serve.py` runs uvicorn with one worker on `127.0.0.1:{PUBLIC_PORT}`, TLS from `.certs/`, `proxy_headers=False`, no access log, a 2 MiB WebSocket message cap and a 10 second graceful shutdown. Do not raise the worker count: the runtime adapter keeps in-process locks and forwards.
