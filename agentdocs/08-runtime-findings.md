# Implementation and runtime findings

## Current recovery status — 31 October 2026

User1 was recovered with the original instance UUID `dc5d15cd-d1f0-4294-bbcc-cb0bf44d2832` and named volume `openclaw-data-dc5d15cd-d1f0-4294-bbcc-cb0bf44d2832`. Native replacement ID is `ee235caa-5a8d-45fe-a9ea-f1db7cf884d6`; the parent image remains the pinned `sha256:459cccec79acf48f8c763410f33093dba054f3e52beea72b14964763f91f0061`. The source runtime entered Error after a configuration reload encountered a root-owned config file. The installed OpenShell version rejects stop from Error, so the supported NemoClaw terminal-state rebuild was used. No native phase metadata was edited.

Fresh stopped `/sandbox` and selected-volume archives plus a PostgreSQL dump are retained under `.state/backups/user1-recovery-20261031`. NemoClaw additionally captured a full native snapshot with digest `ba61afd84abda40469842d6bfeca1f026dfd72ce3d85382d2c591f41509d1373`. The native rebuild required a narrow schema compatibility patch for existing REST `access: read-write` rules; it is recorded in `infra/nemoclaw-policy-read-write.patch` and the runtime manifest. This preserves the policy rather than broadening endpoints. The failed native retry cleaned up its policy handoff; the last independently recorded live policy observation was republished through the native SDK. A changed preferred API selector was restored to the original value only after reproducing the transaction's original target hash. Recovery used an independent copy of the same hash-verified native archive when an earlier failed transaction retained ownership of the first backup.

The native restore initially refused root-owned private backup directories. Their ownership was corrected to the volume owner, then native restoration and its final gateway start both passed. The hash-pinned trusted-proxy startup compatibility patch was reapplied. The owner-specific proxy policy and endpoint-limited local inference provider attachment were reapplied afterward. Existing host chat and activity identities were explicitly repaired for their original read/write and read/questions scopes respectively; no broad automatic pairing rule was added. The native SDK does not persist browserOrigin on pending pairing records in this release; checks used the host public key, exact client/platform/mode, attributed address and exact scope set, with the actual control Origin confirmed in native connection logs.

Before reconciling the control plane to Ready, native phase, container/volume identity, original parent image, config owner and private HTTP health passed. All 448 pre-recovery transcript events were compared by session/sequence/content and remained unchanged (SHA256 `8f7bf26ab98b1cfbad2dc84a01af27d6484f13e6c57772916d51784c5cc0370d`). Real authenticated User1 sessions/history and a local-model exact-marker chat passed. User2 sessions remained available. Configuration writes now preserve the volume UID/GID, and policy-backup directories/files are assigned to that owner. The inference setup supports `--user user1` for scoped recovery and waits for the supervisor's scoped provider handle before saving it.

Chromium had been installed only in the removed container's root filesystem and is absent from the replacement. Browser workflows remain unvalidated and the capabilities response is corrected to `requires_validation`. Workspace recovery is not browser/Zepto completion. See 14 for the raw tool-call findings. Earlier recovery status below is historical.

## Current recovery status — 30 October 2026

This section supersedes the historical unavailable/recovery-blocked findings below. Both owner workspaces were recovered after the owner authorized resetting affected Docker runtime environments. PostgreSQL and both named data volumes were preserved. The immutable parent image remains `sha256:459cccec79acf48f8c763410f33093dba054f3e52beea72b14964763f91f0061`. NemoClaw/OpenShell versions remain pinned.

- Backups: `.state/backups/runtime-recovery-20261030T040529Z` contains both full data-volume archives, a PostgreSQL custom dump, native gateway/registry/control state, and identity manifest. Complete stopped `/sandbox` archives were additionally captured using NemoClaw's native snapshot authority, including provider/runtime receipts and archive hashes. Native restore authority verified source and replacement before restoration.
- OpenShell native deletion removed only the two terminal sandbox runtimes. Exact NemoClaw registry rows were removed with reversible native receipts; no native phase database was edited. Native onboarding selected OpenRouter/Nemotron and reused the UUID-bound volumes. Original `trusted-proxy` auth was temporarily replaced by private token auth during onboarding while control-plane rows remained unavailable; exact owner proxy policy was restored before app readiness. Native public TCP forwards were removed.
- UUIDs and volume names remain unchanged. User1 replacement native ID: `463fed2f-7631-40ff-93e9-407e45933f1e`; User2: `ca554edd-c3a1-4d00-836e-ed541f4c9dbf`. Stable full UUIDs remain the PostgreSQL ownership keys. Native IDs/container names were explicitly reconciled only after real Ready, volume/mount and private health checks.
- Stock startup SHA-256 `fc08fafeff512c0b9e15a18853f6b7cc9b791c5e87e0dc8c4b0a30ce94fb9a79` unconditionally adds a token. Reviewed `infra/nemoclaw-trusted-proxy.patch` retains proxy policy and removes token only for trusted-proxy mode; token mode still rotates. Patched SHA-256 `c4d278b4fdd283b3be32460ce0134a3ca8569bafa6679c1a7a9a38ffdf660286`. Runtime provisioning verifies exact source/installed hashes and atomically installs the patch in the managed container rootfs. This is a separately recorded container compatibility patch, not a claim that the official image digest contains it. A derived local image was prepared but was not deployed or represented as an official managed image.
- Both replacements passed native OpenShell stop/start with the same replacement ID and original named volume. `Ready` alone refers to supervisor/SSH, so provisioning now waits for actual assistant HTTP health. Private AF_UNIX forwards are owned by the long-lived application process.
- Runtime testing exposed two adapter mismatches hidden by protocol fixtures: installed gateway wire protocol is **4**, while device signatures still use the v3 payload; independently hosted frontend requests must send their actual control Origin. Both are fixed. Exact allowed Origins include the control origin and the owner's native tenant origin. No wildcard origins, fake development build IDs, or token fallback were added.
- Native pairing correctly rejected expanding the chat signing key from read/write to approvals. Reviews now use a separate persistent owner-specific host signing identity under `gateway-devices/{uuid}/reviewer`, constrained to read/approvals. First native pairing succeeds under the existing explicit auto-approval allowlist; the chat grant is not expanded.
- Network verification used temporary TCP listeners with a positive administrative control. Native untrusted sandbox processes could not connect to the peer's reachable bridge address/port in either direction. Both containers have only their selected data volume plus native scoped identity/TLS/supervisor mounts; no host home, DB, Docker socket, privilege, or published ports.
- Volume audit compared original workspace and session files. User2: 8/8 matched; User1: 16/17 initially matched. `workspace/DREAMS.md` had been regenerated by native memory maintenance. Its generated replacement was saved privately and the original restored from the verified archive; chat/session histories were retained. This distinction matters: startup/maintenance can mutate native data even when named volumes are retained.

Final verification: 49 automated tests passed; Ruff passed. Browser fallback was required because the in-app browser API returned `browser.user is unavailable`. Installed Chrome through Playwright CLI at 1280×720 verified the real HTTPS login → Visit Morrow → Online → streamed exact synthetic reply for each identity, restored history, task list, and empty pending reviews. A same-browser switch locked the old tab, cleared the old messages/session list and unsent draft, and left User2 with only its own history. A direct authenticated API check supplied User1's actual native session key while logged in as User2; no User1 message was returned. Both owners' task and review-history APIs returned success. Native task cancellation and approval resolution remain covered by controlled protocol tests; no external purchase/calendar/browser task was attempted. Screenshots are outside the repo: `/tmp/claw-orchestrator-qa/user1-online.png`, `user2-online.png`, and `stale-tab-locked.png`. The follow-up read-only browser/API checks used no additional model calls. Both native runtimes were still healthy several hours after their stop/start checks.

Native methods verified directly: sessions list, history, tasks list, review history, and approval-enabled event subscription/replay. Browser model requests use only synthetic text and the exact owner-selected `nvidia/nemotron-3-ultra-550b-a55b:free`. Real external calendar/browser/merchant adapters remain unavailable or in validation. A Docker-daemon/host restart and version-changing upgrade are not covered by native stop/start; do not claim those passed.


Updated: 29 October 2026, Asia/Kolkata. The owner accepted native OpenShell names, stable instance UUIDs and exact `openclaw-data-{uuid}` volumes, selected LM Studio, and authorized setting its listener to loopback. The current task pivots to a separate frontend/API using FEATURE_RESEARCH.md section 4; **further LM Studio inference tests are no longer required**.

## Current status

The control API, curated frontend API, local PostgreSQL, TypeScript client, and controlled-protocol tests are implemented. **The retained native instances are currently unavailable after the host/Docker restart.** Their original UUIDs and volumes remain. The API fails closed on native-backed operations; it does not launch substitute workloads or return invented data.

API guide: 09-frontend-api.md. `infra/runtime-versions.json` records `validation_status: native_recovery_required`. A configured runtime toolchain is not evidence that a particular workload is ready.

## Verified implementation

- uv project and locked dependencies; FastAPI; bounded asyncpg pool; transactional migrations and persisted ownership/session/job/ticket records.
- PostgreSQL 18 through Docker Compose; repo `db/18/docker/` bind storage; non-superuser `claw_api` role and private schema. Database container recreation retained observed session records. The 29 October Docker restart retained both instance records and their IDs.
- Demo User1/User2 login/switch/logout and required button order. Secure host-only HttpOnly cookie JWTs, exact Origin/CSRF, persisted revocation and strict issuer/audience/algorithm/time checks. JSON CSRF bootstrap supports a standalone frontend without scraping HTML.
- Durable idempotent own-instance creation, job leases, bounded crash recovery, failure retention and one-use launch tickets.
- Authenticated HTTP/WS proxy with rebuilt identity headers, protected Unix-socket ingress, session/ownership liveness checks and stream revocation.
- Curated frontend API: sessions, text history, message submission/abort, filtered SSE, native tasks/cancellation, pending reviews/decision history, presentation-bound one-use decisions, capabilities and authenticated OpenAPI. No raw RPC method, tenant target, gateway config, arbitrary file/tool arguments or standing grants are accepted.
- Native reviewer access requires a device identity in the installed bundle. The adapter has an independent server-held Ed25519 identity per instance, private key mode 0600, v3 nonce signature, and constrained read/write or read/approval scopes. Keys and connect credentials are never frontend data.
- Approval review tokens are opaque random capabilities stored only by hash, owner/session/instance/proposal-bound, expiry-bounded, and atomically consumed. Tests reject changed presentations, cross-owner use, expiry, replay and concurrent double consumption.
- Current automated suite: **37 passing tests** against uniquely named disposable PostgreSQL databases and controlled HTTP/real WebSocket protocol peers. These do not establish native sandbox isolation or external action completion. Ruff and strict TypeScript checking pass.
- Browser on 27 October verified login → user1 → switch user2 → logout at the real HTTPS app, desktop and 390×844. Native user1 OpenClaw UI and its WebSocket connect succeeded without a gateway token in the browser. Full native user2 UI/chat and complete cross-tenant browser checks were not completed.
- Browser launch testing found that `Referrer-Policy: no-referrer` produced null Origin on Chromium form POST. It uses `strict-origin` now, with exact Origin checks retained.

## Native tuple, state and ingress observed on 27 October

| Component | Evidence |
| --- | --- |
| NemoClaw | v0.0.139, source `a08ae7aa911ef5bd7a4b72d9020f575d75d0adb1` |
| OpenShell | 0.0.116, source `d1155aa70042d3e2ee49dbfa15346b108b7c1d92`; verified macOS ARM64 archive hashes in manifest |
| OpenClaw | 2026.9.2 in managed image ID `sha256:459cccec79acf48f8c763410f33093dba054f3e52beea72b14964763f91f0061` |
| Workloads | Two actual managed containers, distinct native IDs/names and exact owner volumes |
| Persistence mount | Each own named volume RW at `/sandbox/.openclaw`; workload UID 998 |
| Naming | Logical `co-{first16UUIDhex}` due upstream 19-character cap; native Docker `openshell-default--{name}-{native-id}` |
| UUID volume patch | Narrow `infra/nemoclaw-state-volume.patch`, fails without canonical full-UUID binding; unrelated native names unchanged |
| Gateways | Per-owner gateway ports 18480 and 18481, separate native state directories and registries |
| Agent ports | Actual configured port read per instance: 18789 for user1 and 18790 for user2; do not hardcode one port |
| Private ingress | Per-instance Unix sockets under an owner-only 0700 `/tmp/co-orch-*` directory, through authenticated native SSH relay; native public TCP dashboard forwards stopped |
| Workload exposure | No published tenant ports, no privileged mode, no Docker socket or orchestrator DB mounts |
| Resource limits | At most 2 CPUs, 2 GiB memory/swap, 512 processes per native workload |

A source checkout without a release tag reported 0.1.0 and a missing managed-image catalog; the selected released tag resolved that initial onboarding failure. Private downloads/source/logs live under `.state/`; upstream native per-port registries also live under the user's NemoClaw home. Do not delete those registries or credentials to retry.

The native OpenShell supervisor mounts scoped guest identity/TLS material as part of its supported boundary. Those are distinct from orchestrator signing keys, host administration credentials, provider grants and the database, which are not tenant mounts. The pinned release uses its native shared Docker bridge and supervisor/policy controls; do not describe it as newer OpenShell main's network=none architecture or as separate Docker bridge networks per tenant.

## Isolation evidence and remaining limits

Each native UID 998 process wrote/read a distinct marker at `/sandbox/.openclaw/workspace/isolation-check.txt`. Neither had `/var/run/docker.sock` or `/db`. Probes to the peer's gateway address were refused; host DB/management probes via the host alias were blocked. These bounded probes are useful evidence but **do not prove universal cross-tenant network isolation**: an exposed peer listener, all control-plane routes, IPv6/metadata, and a full same-browser native switch still require live tests.

Independent workload restart/recreation with persisted chat/config/pairing and a restored backup has not passed. Preserve this as a remaining gate rather than claiming volume attachment alone proves upgrade safety.

## Restart failure found on 29 October

Docker and LM Studio were stopped when work resumed. Docker and the Compose database were started, and existing data remained. The API and metadata are usable independently of a model.

Starting the retained native user1 sandbox through OpenShell exposed a pinned integration conflict: NemoClaw's startup rotates `gateway.auth.token` even though the preserved gateway uses `trusted-proxy`. OpenClaw rejects that combination. OpenShell records a terminal **Error** phase; its ordinary start requires Stopped, stop requires Ready, and its SSH relay refuses Error. A running underlying container alone cannot be used as proof of recovery or bypass those checks.

An attempted maintenance recovery did not resolve that native phase. The temporary token-mode change was reverted to the original scoped trusted-proxy policy, the unsuccessful recovery script was removed, and the workload was stopped. No native phase row was edited, no volume was pruned or recreated, no user data was reset, and no unprotected replacement was introduced. An ignored private PostgreSQL backup was taken before applying the frontend review-table migration.

Next runtime work needs a supported native recovery/rebuild path with a consistent backup and identity/volume checks, plus a reproducible solution for startup token rotation. It is separate from model-provider testing. Keep all native-backed frontend routes explicit about unavailable state until that passes.

## LM Studio evidence boundary

On 27 October the listener was changed from `*:1234` to `127.0.0.1:1234` using `lms server stop` and `lms server start --bind 127.0.0.1 --port 1234`, confirmed with lsof. A direct model request succeeded; the initial full OpenClaw run failed at 8K context. The selected `qwen/qwen3.5-9b` model was loaded with 32768 context and the configuration recorded, but full native chat completion was not established. After the owner's 29 October pivot, further inference testing stopped. Do not turn this into an inference or external-workflow success claim.

## Final HTTPS API smoke (29 October)

System Chrome/Playwright at https://app.localhost:8443 verified JSON CSRF bootstrap/login (200), identity user1, capabilities with native instance unavailable and calendar not implemented, authenticated schema (200, 13 path entries), native sessions fail-closed (503), switch to user2 (200), logout (204), then identity denied (401). Console entries were the intentional 503 and 401 responses, not a new frontend exception. No model or external provider was invoked. Browser plugin was unavailable; Playwright was used.

## Morrow frontend validation (29 October)

The owner authorized the customer frontend and required neutral branding. Visit Morrow opens `/workspace`; customer requests use `/api/assistant/*`. Plain JavaScript modules carry the HttpOnly cookie plus a non-secret page-session marker, with CSRF for mutations. Stale pages are rejected before native dispatch after account switching. The native compatibility aliases are absent from customer assets and UI.

Built-in in-app browser verified real HTTPS User1 login → Visit Morrow → workspace, navigation, unavailable capabilities, disabled sending while offline, desktop 1505×1045 and mobile 390×844. Final browser console had no warnings/errors, mobile had no horizontal overflow, and visible DOM contained none of the backend product names. The native workload remains unavailable; this is not native chat verification.

An opt-in disposable PostgreSQL/protocol fixture exercised authenticated conversation history, literal malicious-looking text without image injection, streamed replies, new conversations, task cancellation with confirmation, and a presentation-bound one-use review decision. Switching the shared login to User2 locked the old page and cleared User1 messages/draft; User2 saw only its own marker. Fixture actions were simulated and invoked no model, command, calendar, or merchant. The fixture banner made that explicit. Its server was stopped and its disposable database and test keys removed; a final database query found no `claw_ui_test_*` databases.

Four new automated checks cover the authenticated shell, stale-page rejection on API/CSRF/SSE routes, marker-vs-auth/CSRF separation and revocation, and generic assets/schema. Full suite: 37 passed. JavaScript syntax, Ruff, and strict TypeScript client checks passed. Design and screenshot evidence: 10-prototype-frontend.md.

## OpenRouter selection and small tests (30 October)

The owner authorized the supplied OpenRouter key in gitignored `.env` and bounded live/browser checks. `.env` was verified untracked and ignored, written atomically, mode 0600. No key value belongs in documentation, logs, fixtures, browser code or tenant config. Settings holds it as SecretStr, accepts only the exact OpenRouter HTTPS base URL and explicit `:free` model. Native onboarding selects the supported `openrouter` provider and receives the key only for that host-side operation. Ordinary runtime subprocesses remove it. Existing native bindings and volumes were not changed.

Credential verification returned 200. The account initially reported 0 used / 50 allowed / 50 remaining free daily requests. Preflight checks zero prompt/completion pricing, context and advertised tools. Smoke requests cap prompt/completion prices at zero, disable reasoning, use at most 256 output tokens, no paid/random fallback or plugins, no retries and a 180-second total deadline. Prompts are synthetic; the only demo tool is validated local addition.

| Direct provider check | Observation |
| --- | --- |
| Xing4.0 free | Listed, but two bounded probes returned temporary upstream Phala 429 without retry hints. Stopped retrying. |
| Dots short reply | Exact READY, passed. |
| Dots named-function forcing | 404. Advertised tools do not establish every tool-choice form. Not supported by this checked endpoint. |
| Dots automatic tool selection | Exact add_demo_numbers arguments 17 and 25, passed. |
| Dots streamed tool result | Terminal stream and answer containing 42, passed. |
| Dots JSON schema | Exact status ready, passed. |
| Dots context recall | Marker recalled across a 3239-prompt-token request, passed; not a 64K/512K qualification. |

Complete five-request Dots smoke passed. Non-stream responses reported cost 0; all requests enforced zero prompt/completion prices. Dots is selected in local `.env` and `.env.example`, with 65536 context / 4096 output for future native onboarding. Its catalog expiration is 2026-12-31; requalify a replacement. Catalog/endpoint metadata: https://openrouter.ai/api/v1/models; protocol: https://openrouter.ai/docs/guides/features/tool-calling.

Automated suite: 46 passed, including nine new provider cases. Native command tests also prove provider-key redaction from operator logs and returned output. These check alternate credential-host and paid/random-model rejection, omitted keys in routine runtime environments, distinct owner gateway bindings, credential failure, retired models, missing tools, changed prices and insufficient context. Controlled responses consume no live quota.

Both retained instances still report unavailable; native sandbox queries currently return no live record. This does not bypass or resolve the earlier Error-state recovery gate. Native chat/tasks/reviews and external integrations are still blocked or unimplemented. Built-in browser checks real login, expired-session handling, Visit Morrow, Chat/Tasks/Reviews/Connections offline gates and switching User1→User2: the old page locks and a synthetic draft is cleared. Protocol tests independently cover feature success/authorization. No native phase metadata or user data was reset.

Final checks: Ruff passed; complete suite 46 passed (one existing Starlette/httpx deprecation warning). Built-in browser 1280×720: no console errors/warnings, no backend product names, Send disabled while native unavailable, logout returned to identity selection. Final credential audit: key absent from all Git-visible files, .env ignored and mode 0600. Final OpenRouter quota reported 7/50 used, 43 remaining; no paid route invoked. Screenshot outside repo: /tmp/morrow-openrouter-qa/workspace-offline.png.

## Owner-selected Nemotron 3 Ultra (30 October, supersedes Dots selection)

The owner explicitly selected `nvidia/nemotron-3-ultra-550b-a55b:free`. Local `.env`, Settings defaults and `.env.example` now select it; the running API was restarted. Current model and endpoint metadata advertise 1,000,000 context tokens, at most 65,536 completion tokens, optional reasoning, tools/tool_choice, no response_format/structured_outputs, zero prompt/completion price and no listed expiration date. Configured context is 1,000,000, output remains 4096. No full-context stress request was made. Source: https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b:free and its public model/endpoints API.

Four synthetic live requests passed: exact READY (21 prompt / 3 completion tokens), correct automatic arithmetic tool arguments (314 / 37), streamed answer from tool result 42 with terminal event, and context-marker recall (3244 / 9). Non-stream responses reported cost 0; all requests enforced zero input/output prices and no retries/paid fallbacks. JSON schema output is unsupported and explicitly skipped, not passed. The smoke runner now determines whether to run that optional test from advertised capabilities and reports the actual request count.

Ruff and all 46 local tests passed. Key remains gitignored mode 0600. The key endpoint still reported 7 used / 50 allowed / 43 remaining after the four requests; this counter is a reported account policy snapshot, not proof of this provider's enforced quota or immediate accounting. A 1M context limit does not establish a higher request allowance. Native recovery remains blocked, existing tenant bindings/volumes were not migrated, and direct model success is not Morrow native chat completion.
