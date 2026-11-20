# Claw Orchestrator: local agent instructions

## Start here

Read `docs/agentdocs/README.md` and the current frontend/API pivot in `docs/agentdocs/09-frontend-api.md`, then the requirements, architecture, security, API, runtime, and implementation documents linked there before implementing. This repository contains the Python API/UI foundation, PostgreSQL Compose configuration, tests, and an in-progress NemoClaw runtime integration. The owner has authorized implementation and local runtime validation. Keep application behavior and runtime claims aligned with verified evidence.

`AGENTS.md` and `docs/agentdocs/` are tracked in Git. Update these documents when later authorized implementation changes a decision.

## Product scope

Build a small prototype: two demo identities (`user1`, `user2`), cookie JWT login/switch/logout, one persistent instance per identity, one creation API, and an authenticated HTTP/WebSocket proxy to the owner's OpenClaw UI. Use uv for Python dependencies and execution. No public deletion, upgrade, admin, billing, registration, or multi-host scheduling APIs in this milestone.

## Current frontend pivot (29 October 2026)

The owner requested a separate frontend over selective authenticated OpenClaw APIs and directed scope to docs/FEATURE_RESEARCH.md section 4. Curated chat/session, native task, and native review APIs are authorized. The owner subsequently requested the prototype frontend: **Morrow**. Visit Morrow opens the authenticated `/workspace` shell and uses `/api/assistant/*`. Hide backend product names from all customer-facing labels, titles, assets, and request paths. The old native UI is developer compatibility access only. Calendar/connection/browser/commerce adapters need their documented feasibility and permission boundaries; do not claim them from chat alone. LM Studio inference testing is no longer required. Use the capabilities endpoint to distinguish implemented API adapters from unresolved external features.

Both native workloads were recovered on 30 October through owner-authorized runtime reset, full native snapshot restoration, and reuse of their original UUIDs and named data volumes. Native container IDs changed and were explicitly reconciled after health/mount checks. A hash-pinned rootfs startup patch prevents token/trusted-proxy conflicts and is reapplied on provisioning; the parent image digest is recorded separately. The API speaks gateway protocol 4 and sends the actual control frontend Origin. Chat and review signing keys are separate per instance to avoid silently expanding an existing device grant. Never edit native phase metadata to fake readiness. See 08-runtime-findings.md for current evidence and remaining limitations.

On 30 October the owner selected OpenRouter and authorized bounded live checks. Its key lives in gitignored mode-0600 `.env`. Dots3-Note Preview `:free` passed small direct-provider tests; Xing4.0 returned upstream 429s. Dots advertises retirement on 2026-12-31. No paid fallback. This was the pre-recovery state; the later Nemotron recovery paragraph supersedes it. `scripts/check_inference.py --smoke` uses at most five synthetic requests with no automatic retries. Provider success is not native chat, isolation or external-action evidence.

The owner subsequently selected `nvidia/nemotron-3-ultra-550b-a55b:free` on 30 October. It replaces Dots in local settings and defaults, with 1M context as advertised and 4096 output. It has tool support but no advertised JSON-schema output; smoke reports that check unsupported, not passed. Account request quota is separate from context capacity; no full-context live qualification is claimed. The later recovery migrated both retained native runtimes and verified real chat.

The custom Morrow UI runs at the control origin and stores no private browser data persistently. Each page is pinned to its login session via a non-secret server-checked header; switch/logout clears its private state and cancels requests. Separate tenant origins still apply to the legacy native UI. See 10-prototype-frontend.md for design and QA.

## Automations pivot (30 October 2026)

The owner requested replacing the Tasks page with native-style Automations. Read `docs/agentdocs/11-automations.md`. Curated schedule/history and typed create/update/run/remove APIs are authorized; existing task APIs remain. Native cron writes use a separate explicitly paired, host-only admin identity. Do not broaden native automatic browser pairing or expose general admin RPC. New schedules run private, tool-free agent turns with no external delivery; external calendar/commerce/browser automation remains gated. Protect managed monitor definitions, require loaded revisions and idempotency keys, and preserve all schedules/history and data volumes.

## Invariants

- Generate one server-side UUIDv4 per instance. Preserve it across restart, retry, and later replacement. Use native OpenShell Docker container names (owner-approved). Logical sandbox names use `co-` plus the first 16 UUID hex characters because NemoClaw caps them at 19 characters. Named volume: `openclaw-data-{uuid}`. Persist the actual native container name separately from the stable full instance UUID.
- Resolve ownership from a validated session and database lookup. A hostname, UUID, path, query, header, or request body never proves ownership.
- Mount only the selected owner's data. Never mount another user's volume, the orchestrator database, host home, runtime credentials, or Docker socket inside a tenant workload.
- Authenticate every proxy HTTP request and WebSocket handshake. Revoke existing streams on logout, switch, expiry, or loss of ownership. Never redirect a revoked connection to another instance.
- Keep upstream ingress private and use the supported OpenShell network/policy boundary; prove cross-tenant traffic is blocked. Separate volumes alone do not establish isolation.
- Use distinct browser origins per instance; keep OpenClaw at `/` with no tenant URL path. Hostnames are routing hints checked against ownership. See the documented interpretation of the user's path requirements.
- Keep orchestrator JWTs out of upstream traffic, JavaScript storage, URLs, and logs. Demo login must remain loopback-only and explicitly enabled.
- Persist control-plane metadata outside tenant volumes. Reconcile interrupted provisioning; never blindly adopt resources by name or delete a volume on failure.
- Use Docker Compose PostgreSQL for orchestrator metadata. Persist its cluster through the repo-root `./db/` bind mount; `/db/` is gitignored. Never put orchestrator data in a tenant volume or a SQLite file.
- Preserve data during replacement. No volume pruning, `down -v`, or automatic deletion of user data. Back up before a data-changing migration.

## Runtime truth

NemoClaw is an OpenShell-managed stack. Installing its CLI into a plain OpenClaw container does not establish its sandbox controls. First complete the runtime feasibility spike in `docs/agentdocs/05-runtime-and-data.md`. Verify native container identity mapping, explicit named-volume attachment, durable native state, private ingress, network separation, and trusted-proxy/device pairing with pinned versions. If upstream cannot satisfy a requirement, record the blocker and present the concrete tradeoff; do not silently weaken isolation or substitute bare OpenClaw.

## Implementation conventions for later work

- Start with one Python package, FastAPI/ASGI, PostgreSQL on Docker Compose, server-rendered HTML, and a narrow runtime adapter; avoid a frontend framework and external queue in the prototype.
- `compose.yaml` supplies the database service. Follow `README.md` for setup, use a dedicated app role, keep tenant networks separate from `control_plane`, and preserve `db/` across container recreation. Database major upgrades require a supported migration, not just changing the image tag.
- Manage Python with `pyproject.toml` and `uv.lock`; use `uv sync --locked` and `uv run --locked ...` after those files exist. Commit the lockfile when implementation is authorized.
- Use typed inputs, strict JWT algorithm/issuer/audience/time checks, parameterized SQL, and uniqueness constraints for ownership. Use structured runtime calls or argument arrays, never shell interpolation.
- Do not block the ASGI event loop with Docker/CLI work. Persist jobs before acknowledging creation. Start with a single application worker and durable reconciliation.
- Keep all resource configuration server-owned: images, commands, mounts, network destinations, and upstream ports. Clients cannot supply them.
- Pin runtime images by digest and record the NemoClaw/OpenShell/OpenClaw compatibility tuple. Do not download installers during a user request.
- Run meaningful authorization, concurrency, restart, persistence, and HTTP/WebSocket integration checks from `docs/agentdocs/06-implementation-plan.md`. Keep lightweight unit tests separate from opt-in real-runtime tests.
- Report what was verified and what remains a proposal. Never describe planned isolation or upgrades as tested.

## Chat activity

Read docs/agentdocs/12-chat-activity.md for native subscription delivery, activity/question identity separation, safe projections, sequence/reconnect behavior and validation limits. Preserve exact approval integrity: blocked presentations cannot issue or consume review tokens.

## 31 October browser and User1 recovery follow-up

User1 was recovered using supported native rebuild and its full original snapshot. The stable instance UUID and named volume were retained; the replacement native ID is recorded in PostgreSQL only after native Ready, mount and private-health checks. All 448 archived transcript events matched after restoration. Native phase metadata was not edited. Both owners currently use the authenticated local LM Studio route documented in 16-local-inference.md, superseding the prior OpenRouter choice.

Read the latest sections of 14-browser-network-findings.md before browser changes. Both retained owners have additive Chromium, a supervisor-routed public-only proxy bridge and five hash-pinned browser compatibility patches. Actual public-page snapshots and loopback/peer/metadata denials passed in both owners. These rootfs additions are not part of the original parent image; replacement durability remains unqualified. Runtime environment guidance belongs in native workspace AGENTS.md; the installed native version has retired TOOLS.md. A green tool card or model final text is insufficient evidence: inspect raw native tool arguments/results and provider continuation failures. Zepto inventory remains unverified while its site returns HTTP429.


## Local restart reliability qualification (31 October, late run)

Native local inference auth must use an environment SecretRef for `LMSTUDIO_API_KEY` in both provider configuration and the native inference auth profile. Persisting a scoped literal can fail after supported native stop/start because its namespace changes. `setup_local_inference.py` uses native transactional profile writes, supported stop/start, exact identity/mount verification, and browser bridge readiness. It preserves other local model catalog entries on the same endpoint. Do not use SIGUSR1 during active work: one observed shutdown remained in drain.

Morrow's curated gateway reconnect checks the owner-bound private forward, with repairs serialized per instance. A killed User1 forward recovered automatically and both owners returned sessions200; transient native restart failures may still briefly return503 until dead-peer detection. API startup must fail if the public-only browser egress listener cannot bind; do not swallow that error. Client recovery retains draft/conversation and never automatically resends messages.

The owner authorized downloading/testing a stronger local model, Qwen3.6 35B A3B. Download/hash verification and load succeeded. Keep model selection scoped to the test session with `modelSelectionScope=session`; do not promote it from a successful first tool call. Its first live Zepto run observed HTTP429 and retried excessively. See 16 for later qualification and the current selected default. External availability and agent behavior are separate evidence.


## Availability and session boundaries (1 November 2026)

Retained unavailable instances are rechecked by the application worker without provisioning/adoption. Ready requires actual native identity/mount/private health and browser-bridge checks and a conditional update against unchanged ownership/resource metadata. Failed provisioning remains failed. Native phase metadata is never edited. A live User1 availability interruption recovered through this path in8-9seconds with identity and volume preserved.

Guard failures must distinguish authentication/ownership loss from runtime unavailability. A transient outage closes the stream with503/reconnect semantics; it must not clear the still-live page or draft as though its cookie were revoked. Actual logout/expiry/ownership loss still terminates access and clears private state. Revalidate cookie liveness before reporting a stored availability failure so concurrent revocation wins. Identity polling likewise treats network/5xx failures as reconnects; only authoritative session/account changes clear state. See12/14for real browser checks.
