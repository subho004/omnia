# Getting started

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Docker with Compose (PostgreSQL 18, and the OpenShell workloads)
- [mkcert](https://github.com/FiloSottile/mkcert) with its local CA installed
- Node.js (used by the Ed25519 gateway identity helper `src/claw_orchestrator/device.mjs`, the NemoClaw CLI, and the browser guard tests)
- macOS on Apple silicon for the pinned OpenShell binaries (`infra/runtime-versions.json` carries darwin-arm64 checksums)
- Optional: [LM Studio](https://lmstudio.ai/) serving `qwen/qwen3.6-27b` on `127.0.0.1:1234`, or an OpenRouter key

## 1. Install and configure

```sh
uv sync --locked
uv run --locked scripts/setup_local.py
```

`setup_local.py` writes `.env` with mode 0600 and random database and JWT secrets. It never overwrites an existing `.env`, and it prints no credentials. When settings change, compare your `.env` with `.env.example`. See [Configuration](configuration.md).

## 2. Certificates

The server requires HTTPS on `app.localhost` and `*.claw.localhost`.

```sh
mkdir -p .certs
mkcert -cert-file .certs/local.pem -key-file .certs/local-key.pem \
  app.localhost '*.claw.localhost' localhost 127.0.0.1 ::1
```

`scripts/serve.py` exits with an error if either file is missing.

## 3. Database

```sh
docker compose up -d --wait db
docker compose ps db
```

Migrations run automatically when the API starts. See [Database](database.md).

## 4. Runtime (needed for real instances)

Without a runtime the app still serves the login page and the workspace shell, and `POST /api/instance` returns `503 RUNTIME_NOT_CONFIGURED`. No placeholder instance or job is created.

```sh
uv run --locked python scripts/setup_runtime.py --activate
```

This installs the pinned NemoClaw and OpenShell toolchain under `.state/` and verifies checksums. Activation writes `.state/runtime-ready.json`. The adapter treats the runtime as available only when that file's `source_revision` equals `nemoclaw_source_revision` in `infra/runtime-versions.json`. Details are in [Runtime and provisioning](runtime-and-provisioning.md).

Then pick an inference route:

- **LM Studio (default):** set `LMSTUDIO_API_KEY` in `.env` if the local server requires one, then run `uv run --locked python scripts/setup_local_inference.py` to configure already-provisioned instances (`--user user1` or `--user user2` limits it to one owner).
- **OpenRouter:** set `INFERENCE_PROVIDER=openrouter` and `OPENROUTER_API_KEY`. Check the account and model first with `uv run --locked python scripts/check_inference.py`. Add `--smoke` for at most five synthetic requests.

## 5. Serve

```sh
uv run --locked scripts/serve.py
```

Open <https://app.localhost:8443>, pick User1 or User2, and select **Visit Morrow**. Create an instance from the workspace (or `POST /api/instance`). The status moves `pending` → `provisioning` → `ready`.

## Existing checkouts

After pulling changes that touch automations, restart the API and run:

```sh
uv run --locked scripts/setup_automation_access.py
```

This pairs the host scheduler identities for instances provisioned earlier. New provisioning already includes it. See [Automations](automations.md).

## Browser QA without a model

```sh
uv run --locked python tests/serve_ui_fixture.py
```

This serves a simulated UI at `https://app.localhost:8444`. See [Frontend](frontend.md).
