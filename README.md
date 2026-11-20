<div align="center">

# Omnia

**A local control plane that gives every user a private, persistent AI agent instance.**

[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-ASGI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![uv](https://img.shields.io/badge/managed%20with-uv-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Status](https://img.shields.io/badge/status-prototype-orange)](#status)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](#contributing)

[Demo](#demo-video) · [Quick start](#quick-start) · [Documentation](#documentation) · [Architecture](#how-it-works) · [Contributing](#contributing)

</div>

---

Omnia (package `claw_orchestrator`) gives each of two demo users a private, persistent [OpenClaw](https://docs.openclaw.ai) instance, managed through NemoClaw and OpenShell. Built with uv, FastAPI and PostgreSQL.

# Demo Video


https://github.com/user-attachments/assets/6fa9c06f-d2fc-4ba3-b3a1-01fe96200d9a



## Features

- **Isolated by design**: one instance per user, its own volume, its own browser origin (`https://{uuid}.claw.localhost:8443`). Ownership always comes from the database, never from the client.
- **Safe sessions**: Secure `__Host-` cookie JWTs, CSRF protection, single-use launch tickets and instant revocation of live streams on logout.
- **Durable provisioning**: jobs live in PostgreSQL, survive restarts and recover unhealthy instances automatically.
- **Curated API**: `/api/assistant` covers chat, sessions, tasks, reviews, automations and the managed browser. No gateway credentials ever reach the browser.
- **Public-only egress**: tenant browser traffic goes through a proxy that blocks private, loopback and metadata addresses.
- **No frontend build step**: server-rendered UI with plain ES modules, plus a TypeScript client for a separate frontend.

## Status

Omnia is a prototype. Demo login lets any local visitor pick `user1` or `user2` and is **not** production authentication. The server binds to `127.0.0.1` over HTTPS only.

## Quick start

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker, [mkcert](https://github.com/FiloSottile/mkcert) and Node.js.

```sh
uv sync --locked
uv run --locked scripts/setup_local.py          # writes .env with random secrets
mkdir -p .certs
mkcert -cert-file .certs/local.pem -key-file .certs/local-key.pem \
  app.localhost '*.claw.localhost' localhost 127.0.0.1 ::1
docker compose up -d --wait db
uv run --locked scripts/serve.py
```

Open <https://app.localhost:8443>, pick a user and select **Visit Morrow**.

Creating a real instance also needs the pinned runtime (`uv run --locked python scripts/setup_runtime.py --activate`) and an inference route (LM Studio or OpenRouter). See [Getting started](docs/getting-started.md). Without the runtime the app still runs and instance creation returns `503 RUNTIME_NOT_CONFIGURED`.

## How it works

```
Browser ──https──► 127.0.0.1:8443
                      ├─ app.localhost         control app: auth, /api/assistant, workspace UI
                      └─ {uuid}.claw.localhost authenticated proxy to that user's instance
                              │
        PostgreSQL 18 ◄───────┤ provisioning worker ──► NemoClaw / OpenShell sandbox (OpenClaw)
                              └─ public-only egress proxy for tenant browsers
```

See [Architecture](docs/architecture.md) for request flows and the module map.

## Checks

```sh
uv run --locked ruff check src scripts tests
uv run --locked pytest -q
```

Tests need the Compose database. Each run uses a disposable database and never touches working data.

## Documentation

| Topic | Document |
| --- | --- |
| Install, certificates, runtime, first login | [docs/getting-started.md](docs/getting-started.md) |
| Components, request flows, module map | [docs/architecture.md](docs/architecture.md) |
| Sessions, CSRF, tickets, isolation | [docs/authentication-and-isolation.md](docs/authentication-and-isolation.md) |
| Routes, SSE events, errors, capabilities | [docs/api-reference.md](docs/api-reference.md) |
| NemoClaw adapter, patches, provisioning, recovery | [docs/runtime-and-provisioning.md](docs/runtime-and-provisioning.md) |
| Schema, migrations, roles | [docs/database.md](docs/database.md) |
| Environment variables and local state | [docs/configuration.md](docs/configuration.md) |
| Egress proxy, browser bridge and guard | [docs/browser-and-egress.md](docs/browser-and-egress.md) |
| Schedules and idempotency | [docs/automations.md](docs/automations.md) |
| UI files, session fence, TypeScript client | [docs/frontend.md](docs/frontend.md) |
| Tests, scripts, conventions, troubleshooting | [docs/development.md](docs/development.md) |
| Roadmap: market research, skills, memory, scale | [docs/future-steps.md](docs/future-steps.md) |

Planning notes and dated runtime evidence are in [`docs/agentdocs/`](docs/agentdocs/README.md). Feature scope comes from [FEATURE_RESEARCH.md](docs/FEATURE_RESEARCH.md) section 4.

## Repository layout

```
src/claw_orchestrator/   FastAPI app, auth, proxy, provisioning, runtime adapter, templates, static UI
clients/                 TypeScript browser clients
infra/                   Runtime manifest, patches, browser guard plugin, PostgreSQL init SQL
scripts/                 Setup, serve and diagnostic scripts
tests/                   pytest suite and UI fixture
docs/                    Documentation, planning notes (docs/agentdocs), feature research
compose.yaml             PostgreSQL 18 service
```

## Contributing

Issues and pull requests are welcome. Before opening a PR:

```sh
uv run --locked ruff check src scripts tests
uv run --locked pytest -q
```

Read [Development](docs/development.md) for conventions, and [Authentication and isolation](docs/authentication-and-isolation.md) before touching anything on the security boundary. Agent-specific instructions are in [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md).
