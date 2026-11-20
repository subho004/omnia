# NemoClaw Orchestrator: prototype plan

Planning date: 2026-10-27 (Asia/Kolkata). Status: **Morrow prototype frontend, curated API, PostgreSQL, and protocol tests implemented; native runtime recovered on 30 October; real two-user browser chat and isolation verified**. See the repository [README](../README.md) for database startup.

The prototype gives each demo user one independent OpenClaw instance, managed through NemoClaw/OpenShell, with a dedicated Docker named volume. A uv-managed Python service provides creation, demo authentication, and an authenticated proxy. Container replacement must retain the user's data and stable instance identity.

## Reading order

1. [Requirements and login flow](01-requirements.md)
2. [Architecture and decisions](02-architecture.md)
3. [Authentication and isolation](03-auth-and-isolation.md)
4. [API contracts](04-api-contracts.md)
5. [Runtime, persistence, and upgrades](05-runtime-and-data.md)
6. [Implementation sequence and acceptance checks](06-implementation-plan.md)
7. [Research sources and open validation items](07-research.md)
8. [Implementation and runtime findings](08-runtime-findings.md)
9. [Current frontend API and section 4 feature map](09-frontend-api.md) — read first for the 29 October frontend pivot.
10. [Morrow prototype frontend and QA](10-prototype-frontend.md) — current customer UI, session boundary, design reference, and validation evidence.
11. [Automations page and scheduler contract](11-automations.md) — current replacement for the Tasks page.

## Central decisions

| Concern | Prototype decision |
| --- | --- |
| Python environment | uv manages dependencies and runs the Python service; Docker/OpenShell manage workloads |
| API/UI | FastAPI/ASGI and small server-rendered HTML page; HTTP and WebSocket proxy |
| Control-plane storage | PostgreSQL in Docker Compose; repo `./db/` bind mount; one active instance row per user |
| Provisioning | Durable job in PostgreSQL, one in-process worker, restart reconciliation |
| Resource identity | Server-generated UUIDv4; native OpenShell container names and `openclaw-data-{uuid}` |
| Routing authority | Valid JWT + live session + database ownership; never a client-selected target |
| Browser URL | Root `/` on an opaque per-instance hostname, no tenant path or token URL |
| Login | Local demo user selection only; not proof of a real person's identity |
| Runtime | Pinned NemoClaw/OpenShell adapter; current recovery gate recorded in 08 |
| Upgrade scope | Documented replacement procedure; no upgrade endpoint in v0 |

## Interpretation of the routing request

The request mentions both routing “based on paths” and routing “without a URL path.” This plan interprets the final constraint as **no instance-selection path such as `/instances/{uuid}/...`**. The proxy keeps OpenClaw's own paths unchanged at the instance origin's root. Identity selects the permitted instance; ordinary upstream paths still work.

The planned browser address is `https://{uuid}.claw.localhost/`, and the login page is `https://app.localhost/`. All hosts reach the same proxy service. Separate origins keep browser storage and device identities apart. This adds a hostname, not an instance path. A single fixed browser hostname is not the selected design because user switching would otherwise require proving complete cache/storage/service-worker isolation. If a fixed hostname is later required, revisit this decision before implementation.

## Definition of done for this planning task

Local instructions, requirements, diagrams, API and auth contracts, persistence design, runtime feasibility gates, implementation milestones, and isolation checks are written. Both documentation paths are ignored by Git. The owner has authorized runtime experiments; current evidence and unresolved gates are tracked in 08-runtime-findings.md.

## Current scope clarification

The owner selected FEATURE_RESEARCH.md section 4 to guide the separate frontend. The current contract is 09-frontend-api.md. Original UI-only statements in earlier plan chapters are superseded by that contract; provider/browser integrations remain explicitly gated. LM Studio tests stopped; on 30 October the owner authorized OpenRouter integration and small live checks. See 08 for evidence and the remaining native gate.

12. [Chat activity and evidence](12-chat-activity.md) — native status projection, safe history/reconnect and brand boundary.

13. [Runtime access and browser prerequisites](13-runtime-policy-notes.md).
14. [Browser networking findings and remaining boundary](14-browser-network-findings.md).
15. [Current integration validation](15-integration-status.md).
16. [Authenticated local LM Studio inference](16-local-inference.md) — current model route, scoped credentials, verification and provisioning limits; supersedes earlier provider selection.
