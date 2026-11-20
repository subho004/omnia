# Documentation

Morrow (package `claw_orchestrator`) is a local control plane that gives each of two demo users a private, persistent OpenClaw instance. The instance is managed through NemoClaw and OpenShell. The control plane authenticates users, provisions and probes instances, proxies traffic, and exposes a curated API to a browser frontend.

| Document | Read it for |
| --- | --- |
| [Getting started](getting-started.md) | Install, certificates, database, runtime activation, first login |
| [Architecture](architecture.md) | Components, request flows, module map, design decisions |
| [Authentication and isolation](authentication-and-isolation.md) | JWT sessions, CSRF, launch tickets, tenant boundaries, headers |
| [API reference](api-reference.md) | Every HTTP route, SSE events, error format, feature readiness |
| [Runtime and provisioning](runtime-and-provisioning.md) | NemoClaw adapter, provisioning steps, patches, pinned versions, recovery |
| [Database](database.md) | Roles, schema, migrations, backups |
| [Configuration](configuration.md) | Every `.env` setting and the validation rules behind it |
| [Browser and egress](browser-and-egress.md) | Public-only egress proxy, browser bridge, browser guard plugin |
| [Automations](automations.md) | Schedule API, idempotency, the admin identity |
| [Frontend](frontend.md) | Server-rendered shell, JS modules, the TypeScript client, UI fixture |
| [Development](development.md) | Tests, lint, scripts, conventions, troubleshooting |
| [Future steps](future-steps.md) | Market research, gaps, phased roadmap toward a general agent |

## Status

This is a prototype. Demo login lets any local visitor pick `user1` or `user2`, so it is not production authentication. The control plane binds to `127.0.0.1` over HTTPS. Runtime claims in these docs describe what the code enforces. Qualification evidence from live runs is kept in the historical notes below.

## Historical notes

The repository also tracks planning and evidence notes from the prototype's development:

- [`agentdocs/`](agentdocs/README.md): numbered planning, runtime-finding and QA notes. They record dated decisions and test evidence. Where they disagree with the code or with `docs/`, the code wins.
- [`FEATURE_RESEARCH.md`](FEATURE_RESEARCH.md): product feature research. API scope follows its section 4.
- [`AGENTS.md`](../AGENTS.md) and [`CLAUDE.md`](../CLAUDE.md): instructions for coding agents.
