# Implementation plan and verification

The API/UI foundation and Docker Compose PostgreSQL are implemented. The curated frontend/API pivot is implemented against controlled protocol peers; native recovery remains unresolved. See 08-runtime-findings.md and 09-frontend-api.md. The milestones below remain the acceptance checklist. Do not skip feasibility and then describe isolation as working.

## 0. Prove the runtime contract

Complete all gates in [runtime and data](05-runtime-and-data.md). Pin a released compatible stack, record native state/mount paths, verify exact names and isolated networks, and prove trusted-proxy UI + WS behavior with pairing. Resolve local HTTPS/hostname handling and disable offline/service-worker persistence for the demo profile. Exit with a reproducible minimal manifest and actual evidence, or a precise blocker with supported alternatives.

## 1. Bootstrap Python and metadata

Use the existing root `compose.yaml` database service and gitignored `./db/` bind mount. Follow the root README to configure `.env` and start PostgreSQL. Create the package layout, `pyproject.toml`, `uv.lock`, PostgreSQL driver/pool, schema/migrations, safe structured logs, and health check. Create a least-privilege application role and seed immutable user1/user2 IDs. Keep database files, state, secrets, and certificates ignored. Implement strict settings and the local demo-auth guard. Use one application worker until multi-process session/connection revocation and job leasing are designed.

Planned commands, **only after implementation creates the referenced files**:

```sh
uv sync --locked
uv run --locked uvicorn claw_orchestrator.app:app --host 127.0.0.1 --port 8000 --workers 1
uv run --locked pytest tests/unit
```

The host command is for local control/API development. Full tenant networking and HTTPS integration use the infrastructure deployment proven in milestone 0. The service command inside that deployment still uses uv; bind/public exposure is controlled by its private network and edge. Do not enable development reload while running persisted provisioning jobs.

## 2. Implement instance creation

Build the runtime adapter, unique-owner instance reservation, persistent jobs/leases, step reconciliation, quotas, and conservative readiness. Implement only create-own and get-own status endpoints. Keep resource parameters server-owned. Exercise duplicate requests, partial failures, daemon outage, and process restart before adding the UI.

## 3. Implement authentication and minimal UI

Add host-only JWT cookies, strict claim validation, live sessions, CSRF/Origin enforcement, and button states from the requirements. Implement switching and logout as revocation operations. Add asynchronous create/status behavior behind “Visit OpenClaw.” Do not treat the demo selector as production authentication.

## 4. Implement launch and proxy

Add one-use launch tickets, exact host checks, private upstream discovery, sanitized HTTP forwarding, streaming, WebSocket bridging, and cancellation. Configure the pinned gateway's trusted-proxy identity, origins, scopes, and pairing. Authorize all paths. Track active streams by session and close them on revocation or expiry. Prove two simultaneous instances before calling the prototype complete.

## 5. Verify isolation and persistence

Use unit tests for policy/state logic, HTTP/WS integration tests with controllable upstreams, and opt-in real NemoClaw/OpenShell/Docker tests. Browser tests use both isolated browser contexts and a same-context switch. Mocks cannot establish real sandbox, mount, or network isolation.

| Case | Action | Required result |
| --- | --- | --- |
| Two instances | Create as both users concurrently | Two distinct UUIDs, native container identity mappings and exact volumes, no shared tenant mounts |
| Duplicate create | Many simultaneous user1 requests | Same UUID; one volume/workload/job; no orphan duplicate |
| UI state | Login each user, switch, logout | Exact button order; current identity correct; tokens absent from JS storage |
| Data marker | Write unique file/chat marker as each owner | Each owner sees its own marker, never the other's |
| Cross-target access | user2 session against user1 hostname, UUID paths, queries, body, and identity headers | Denied or ignored selectors; no user1 bytes; repeat as user1 to prove the resource exists |
| JWT validation | Tamper payload/signature, wrong algorithm/audience/issuer, expiry, nonexistent sid | Rejected before upstream contact |
| Gateway bypass | Try direct published/private addresses and captured gateway/device credentials | No browser/tenant bypass of proxy ownership checks |
| Pairing | Open real Control UI and reconnect after pairing | Works under pinned auth policy without disabled security checks |
| Origin/CSRF | Foreign/sibling origin POST and WS handshake; absent/null Origin | Rejected under the browser policy |
| Launch tickets | Replay, expiry, wrong host, revoked sid, parallel consumption | At most one valid exchange; no fallback to another instance |
| Logout/switch WS | Open socket and a slow HTTP stream, then switch/logout | Old forwarding canceled; old credentials cannot reconnect; no retargeting |
| Expiry WS | Let session expire while connected | Stream/socket closed promptly; no late frames delivered |
| Setup race | Revoke while upstream handshake/setup is pending | Authorization recheck prevents a late live connection |
| Browser separation | Same browser switches user1 to user2 and opens user2 UI | Distinct origins/storage/device state; no user1 marker rendered in user2 UI |
| Proxy headers | Supply forged forwarding/identity/scope headers and reserved cookies | Removed/rebuilt; no identity injection or sibling cookie scope |
| Redirect/cache | Upstream redirects internally or across tenants; response caching/offline attempts | No credential leakage, cross-tenant redirect, or cached response served as user2 |
| Network boundary | From tenant1 probe tenant2, host aliases, management ports, metadata, IPv4/IPv6 | Blocked; allowed provider connectivity still works |
| Resource limits | Saturate user1 CPU/memory/connections within configured limits | User2 remains usable; pressure does not create another instance |
| Restart | Restart orchestrator and each workload independently | Ownership/session metadata durable; correct resources reconciled |
| PostgreSQL recreation | Recreate Compose `db` with the same repo bind mount | Cluster remains under `./db/`; orchestrator records survive |
| PostgreSQL unavailable | Stop DB while authenticated requests/streams are active | New access fails closed; streams close when liveness cannot be established |
| Partial failure | Crash after volume/container creation but before DB checkpoint | Same resources resumed or quarantined; volume retained |
| Name collision | Precreate wrong-owner/labeled resource with expected name | Conflict; never adopted, overwritten, mounted, or deleted |
| Missing state | Remove test state under explicit test control | Failure reported; no silent empty replacement |
| Persistence | Stop/remove/recreate disposable test workload via supported operations | Same volume/UUID; file, session, config, plugins/pairing persist as specified |
| Independent replacement | Recreate user1 while actively using user2 | user2 unaffected; user1 resumes with own data |
| Backup/restore | Restore a disposable backup to a new test environment | Data and ownership recovered with compatible runtime |

Real-runtime cleanup must target only resources tagged for that specific test run and explicitly marked disposable. Do not use broad prune commands or touch user-created/persistent instances.

## Completion evidence to collect later

- Pinned compatibility tuple, image digest, policy, and supported runtime creation configuration.
- Sanitized Docker/runtime inspection proving exact names, mount sources, UID/GID, networks, no public tenant ports, and no control-plane mounts.
- Automated HTTP/WS results for positive owner access and negative cross-owner access.
- Browser evidence for the two button states, launch root URL, same-context switching, and isolated storage.
- Restart/recreation and backup restoration evidence for known user data, plus independent-user availability.
- Explicit remaining limitations: local demo identities, trusted host, single worker/host, brief replacement downtime, and unresolved upstream constraints.

Only evidence-backed items in 08-runtime-findings.md are marked verified; controlled-upstream proxy tests do not establish real sandbox isolation.
