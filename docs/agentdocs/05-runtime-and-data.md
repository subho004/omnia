# Runtime, persistence, and later upgrades

## Current evidence and API pivot

The runtime spike created two native workloads with exact UUID volumes and private Unix ingress, but restart recovery is blocked and complete isolation/replacement gates are not closed. Read 08-runtime-findings.md for results; older feasibility tables below are requirements, not current completion claims. The separate frontend/API contract is 09-frontend-api.md. Further model inference testing is no longer required.

## Important stack distinction

NemoClaw is the host-side integration/lifecycle layer; OpenShell manages sandboxes; OpenClaw is the agent and its gateway/UI inside the sandbox. The current architecture describes separate lifecycle, policy, credential custody, and native-state responsibilities. A plain `docker run openclaw` with the NemoClaw package installed alongside it does not establish those protections. [NVIDIA architecture](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/about/how-it-works).

The prototype must use a supported pinned NemoClaw/OpenShell path. Do not nest a privileged Docker daemon or mount the host socket inside each tenant to make it work. Shared infrastructure containers/volumes may exist in addition to the two specifically named tenant resources; they are not tenant data volumes and must not be tenant-readable.

## Milestone 0: mandatory feasibility spike

Before building provisioning, choose a compatible released NemoClaw/OpenShell/OpenClaw tuple and prove the following on the intended host. Record commands, versions/digests, sanitized inspect output, and results here. Runtime experiment results are now recorded in 08-runtime-findings.md.

| Gate | Required evidence | Current result |
| --- | --- | --- |
| Runtime platform | Supported Docker-backed sandbox on this host/architecture; resource controls active | Unverified |
| Native container mapping | Owner accepted OpenShell Docker names; bind them to the full instance UUID | Source-verified; live inspection pending |
| Explicit volume | Actual mount source is `openclaw-data-{uuid}`, an ordinary Docker named volume | Unverified |
| Native state coverage | Config, sessions, workspace, plugins, identities, and supported user files survive recreation | Unverified |
| Runtime ownership | NemoClaw/OpenShell registry remains consistent with orchestrator resource identity | Unverified |
| Network separation | Tenant 1 cannot connect to tenant 2, host management, or proxy control paths | Unverified |
| Private ingress | Trusted proxy can reach the gateway without a browser-accessible tenant port | Unverified |
| Gateway auth | Real UI HTTP + WS works behind authenticated proxy, with pairing/scopes handled | Unverified |
| Browser handoff | Host-only cookies work across launch; final URL is `/`; storage remains isolated | Unverified |
| Independent lifecycle | Stopping/recreating one sandbox leaves the other usable | Unverified |

OpenShell's development runtime documentation describes Docker compute support and custom mounts, but development documentation is not a release compatibility guarantee. Its mount restrictions also mean replacing a workspace root cannot simply be assumed valid. Use the selected release's supported configuration. [OpenShell sandbox runtimes](https://docs.nvidia.com/openshell/dev/how-it-works/sandboxes/runtimes).

The native container identity mapping, exact data-volume binding through NemoClaw, and supported OpenShell network/ingress configuration are **hard gates**, not facts established by the docs. Do not manually rename managed containers or attach unsupported networks behind OpenShell's back. If the chosen runtime cannot satisfy these requirements, document the precise limitation and supported alternatives (runtime adapter extension, a compatible release, or a revised requirement) for the owner. Do not silently substitute bare OpenClaw or weaken network isolation.

## Runtime adapter contract

Define an internal Python interface such as `inspect`, `ensure_volume`, `create_managed_instance`, `probe`, and `resolve_private_upstream`. These are proposed application methods, not claimed NemoClaw/OpenShell API names. The adapter translates server-owned settings into documented runtime operations and parses structured output where available. Use CLI argument arrays and an isolated environment if no supported client is available; never interpolate user strings into shell commands.

Install host tooling separately from requests. Pin the managed image by immutable digest, blueprint provenance, runtime versions, and policy profile. Record them with the instance. Serialize operations that touch shared runtime registry/configuration; a single worker is sufficient for v0. Provider bindings are sandbox-scoped where supported; do not alter shared global inference settings when creating another tenant.

## Resource naming and ownership

For an illustrative UUID `8ce7da1b-5744-4b0b-9d41-538d7fe597a1`:

```text
sandbox:   co-8ce7da1b57444b0b
container: native OpenShell name (recorded after creation)
volume:    openclaw-data-8ce7da1b-5744-4b0b-9d41-538d7fe597a1
network:   supported OpenShell isolation (verify pinned driver)
```

Use canonical UUIDv4 values from the server. Store UUID plus exact runtime IDs; never rebuild ownership from a name alone. Apply server-owned metadata where the runtime supports it:

```text
claw-orchestrator.managed=true
claw-orchestrator.instance-id=<uuid>
claw-orchestrator.owner-id=<immutable seeded user id>
claw-orchestrator.schema-version=1
```

Reconciliation checks metadata, mount source/options, image, runtime registration, and expected networks. Refuse mismatches. A named volume using local-driver bind options is not an acceptable substitute for an ordinary named data volume.

The original topology requirement was a proxy joining only required trusted interfaces and separate tenant networks. The pinned prototype instead uses native OpenShell shared-bridge policy controls, so separate Docker networks are not established evidence. The feasibility spike must confirm that the chosen OpenShell Docker driver exposes supported configuration for this topology. Default shared runtime networks do not count as isolation. Avoid publishing tenant gateway ports; even loopback ports are reachable by trusted host processes and may create unwanted routes via host aliases.

## Durable state layout

Use one persistent named data volume per instance, with a documented directory layout established by the pinned integration. The following is a **logical layout**, not a verified upstream mount target:

```text
openclaw-data-{uuid}/
  home/              # required durable native home state
  workspace/         # durable user workspace if distinct from home
  metadata/          # app-owned state format marker, no control-plane credentials
```

Map supported volume subpaths or approved mount locations to the actual native paths. If a runtime owns/protects the workspace root, use its supported persistence mechanism and verify how the exact requested named volume participates. Do not invent a mount flag or force an overlay over protected roots.

Inventory all mutable state by inspecting the selected image and runtime: HOME, OpenClaw config/state/workspace paths, agent memories, session databases, uploaded/generated files, channel session state, plugins/skills, and per-device pairing records. Keep writable required state inside this tenant volume. Preserve the complete supported native user-state tree instead of backing up only transcripts. Upstream NemoClaw documents native-home/workspace preservation while OpenShell retains its own policy/credential stores. [NVIDIA state architecture](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/about/how-it-works).

Do not hard-code the plain OpenClaw Docker image's `/home/node/.openclaw` layout into a NemoClaw image. The standalone Docker guide is useful as a comparison, not evidence for the managed image's paths. [Standalone OpenClaw Docker guide](https://docs.openclaw.ai/install/docker).

Initialize only empty directories; match the verified workload UID/GID and restrictive file permissions. Initialization must be idempotent and must not overwrite an existing config. Store application/runtime binaries in the pinned image; preserve user-managed native packages when they are part of supported durable state. Avoid mounting over image dependencies in a way that hides upgraded code. Temporary caches may be ephemeral when confirmed reconstructible.

## Failure and restart behavior

- The orchestrator PostgreSQL service is managed by root `compose.yaml`, with the cluster persisted in repo `./db/`. Recreating that container must retain users, sessions, instances, jobs, and tickets. Keep `db/` out of tenant mounts and Git. Use PostgreSQL-aware backups; changing PostgreSQL major versions requires a supported migration and is separate from replacing an OpenClaw image.
- Persist the intended UUID/job before creating external resources; use a lease and per-step checkpointing.
- After restart, inspect exact resources and runtime registration before resuming. A container with a matching name but wrong ownership is a conflict.
- If volume creation succeeds and the workload fails, retain that volume and same UUID. Never auto-delete partially initialized user data.
- If the workload exists but DB readiness was not committed, verify it and complete the record; do not launch a duplicate.
- If data is missing, fail visibly. Do not start a ready-looking empty instance under the same user and hide the loss.
- Retry transient control operations with bounded backoff; quarantine permanent mismatches for operator repair. No recursive unlimited retries.
- Keep runtime registry/config, private keys, provider bindings, and ownership DB backed up separately. A data volume alone cannot rebuild all control-plane configuration.

## Replacement procedure: future operator workflow

Named volumes persist beyond a container's lifetime, but they do not establish image/data compatibility or provide backups. [Docker volume lifecycle](https://docs.docker.com/engine/storage/volumes/).

1. Select and pin a compatible replacement tuple; review state migrations and validate using a restored copy first.
2. Mark only the selected instance unavailable, reject new ingress, drain/cancel streams, and stop its writers using supported runtime lifecycle commands.
3. Take a consistent backup of its volume and necessary control-plane metadata, using PostgreSQL-aware tooling for the orchestrator database. Verify that restoration works. Avoid raw copies of live database files, including any embedded databases within the tenant's state.
4. Replace that workload through supported NemoClaw/OpenShell operations, retaining stable UUID, recorded native container identity, and the same data volume. Do not run two writers against the same volume. Managed workload replacement implies a short service interruption in this prototype.
5. Verify UID/GID, mounts, policy, scoped provider bindings, application readiness, HTTP/WS access, and a known persisted file/session. Keep the other user's instance running throughout.
6. Reopen ingress only after checks pass. On failure stop the replacement; restore a compatible backup before rolling back if migrations changed the data format.

“Seamless” here means users retain their data and instance identity. Zero downtime is not promised by v0. Image rollback alone may fail after a schema migration. Docker volume deletion, pruning, broad cleanup, and `docker compose down -v` are excluded from routine failures, restarts, and upgrades.
