# Research record and unresolved validation

Reviewed on 2026-10-27. Upstream `latest` and `dev` URLs move; pin released versions and recheck owning code/docs before implementation. The architecture and API contracts elsewhere are our proposed design, not claimed upstream APIs.

## Primary references

| Source | What it establishes for this plan |
| --- | --- |
| [NVIDIA NemoClaw architecture](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/about/how-it-works) | Host CLI/integration/blueprint separation and OpenShell's role; native state and policy/credential stores have different ownership |
| [NVIDIA NemoClaw repository](https://github.com/NVIDIA/NemoClaw) | Canonical project and route to current platform/lifecycle documentation |
| [NemoClaw OpenClaw quickstart](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/get-started/quickstart) | Managed onboarding is more than launching a bare OpenClaw image; use its supported configuration path |
| [OpenShell sandbox runtimes, development docs](https://docs.nvidia.com/openshell/dev/how-it-works/sandboxes/runtimes) | Compute-driver configuration, identity, and persistence restrictions require release-specific verification |
| [OpenClaw trusted-proxy authentication](https://docs.openclaw.ai/gateway/trusted-proxy-auth) | Supported proxy identity integration; ingress control and header sanitation remain proxy responsibilities |
| [OpenClaw Control UI](https://docs.openclaw.ai/web/control-ui) | UI uses gateway WebSockets, has browser/device state, and needs real browser integration verification |
| [OpenClaw standalone Docker guide](https://docs.openclaw.ai/install/docker) | Comparison for standalone configuration; its paths are not automatically the NemoClaw layout |
| [Docker volumes](https://docs.docker.com/engine/storage/volumes/) | Named volume lifecycle is independent of the workload container |
| [Official PostgreSQL Docker image](https://hub.docker.com/_/postgres) | PostgreSQL 18 data layout for the repo `./db/` bind mount and first-cluster initialization behavior |
| [Docker bridge networks](https://docs.docker.com/engine/network/drivers/bridge/) | Same-network containers can communicate; a shared tenant bridge does not give the required network separation |
| [uv project execution](https://docs.astral.sh/uv/guides/projects/) and [locking/syncing](https://docs.astral.sh/uv/concepts/projects/sync/) | uv runs project commands and locks Python dependencies; `--locked` guards against unintended lockfile changes |
| [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) | ASGI WebSocket handling is available; transparent bridging is still application work |
| [MDN Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie) | Cookie scoping and security attributes for the proposed auth flow |

A search also returned `https://docs.nvidia.com/openshell/latest/reference/sandbox-compute-drivers`, but a direct open returned 404. Do not treat that stale route as the implementation reference; use the accessible runtime documentation and then the selected release's source.

## Community research: supplementary experience

Two relevant articles were read along with their comments. They inform test ideas; official documentation and runtime evidence govern the technical contract.

- [Pull the tenant from the auth context, not the request body](https://dev.to/authbyexample1/pull-the-tenant-from-the-auth-context-not-the-request-body-dag), by [@authbyexample1](https://dev.to/authbyexample1): reinforces deriving ownership from the authenticated session. A commenter additionally called out query/path/header selectors and positive-control tests; those cases appear in the isolation matrix.
- [Understanding Docker Networks: bridge, internal DNS & the proxy network](https://dev.to/serverkueche/understanding-docker-networks-bridge-internal-dns-the-proxy-network-5856), by [@serverkueche](https://dev.to/serverkueche): illustrates private container networking and the bypass risk of published application ports. Its shared proxy-network example is not adopted for mutually untrusted tenants; our design requires per-tenant network separation. No comments were returned for this post.

This is a small supplementary sample, not a claim of broad community consensus. No article was published and no event submission was made.

## Open validation items and decision owners

| Item | Proposed resolution | When |
| --- | --- | --- |
| Exact Docker name via managed runtime | Verify supported driver/blueprint behavior; block on mismatch | Milestone 0 |
| Explicit named-volume/native-home mapping | Inspect supported mounts and all mutable paths | Milestone 0 |
| Per-tenant network and ingress | Verify supported network settings and actual source IP at gateway | Milestone 0 |
| Pairing, scopes, trusted proxy | Test pinned Control UI + WS against managed gateway configuration | Milestone 0 |
| Local DNS/TLS and cross-host cookie handoff | Test target browsers; document explicit resolver/certificate setup | Milestone 0 |
| Browser caches/service workers | Verify disabled offline profile and cross-user storage isolation | Milestone 0 |
| Model/provider | Operator configures supported provider/model and scoped bindings; no secret in repository | Before real inference test |
| Python/HTTP/WS dependency versions | Select maintained compatible versions, lock with uv | Bootstrap |
| Fixed hostname alternative | Revisit only if owner requires a single identical browser hostname | Before changing routing design |
| Future image upgrades | Test backup, schema compatibility, and supported replacement operation | Later milestone |

The default plan proceeds with root URLs on separate instance hostnames. Runtime limitations that force a requirement change require an explicit design decision, not a hidden implementation shortcut.
