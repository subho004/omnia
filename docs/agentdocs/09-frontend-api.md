# Frontend API and feature map

Updated: 29 October 2026, Asia/Kolkata. The owner asked for a separate frontend over authenticated, selective OpenClaw APIs and directed scope to **FEATURE_RESEARCH.md, section 4**. LM Studio inference testing is no longer required. This document supersedes the assumption that the native OpenClaw UI is the primary future frontend.

## Boundary and deployment

A separate frontend project calls `/auth/*`, `/api/instance`, and `/api/assistant/*` at `https://app.localhost:8443`. Deploy its assets behind that **same public origin**. A separate project does not require a separate browser origin. A development reverse proxy must preserve the configured browser Origin and cookie behavior; arbitrary `localhost:3000` cross-origin calls are intentionally unsupported. Do not enable wildcard credentialed CORS or put a JWT in browser storage to work around this. A genuinely separate-origin deployment needs a deliberate cookie/CORS/OAuth design first.

The frontend never supplies an instance UUID, upstream URL, user identity header, node, RPC method, gateway token, mount, or command. The server authenticates the control cookie, looks up the caller's instance, checks its readiness and ownership, and opens private ingress. A native session key, task ID, or approval ID selects a resource **inside that instance**, never another tenant. Unknown request fields are rejected.

The old native UI launch remains available for compatibility when the runtime is healthy, at its own tenant origin. The curated API is a new control-origin interface; it does not need a launch ticket or proxy cookie. This API allowlist is not a claim that the legacy owner/admin native UI has been removed.

The Python adapter translates specific HTTP operations to the pinned OpenClaw v4 WebSocket RPC protocol. Ordinary operations request `operator.read` and `operator.write`. Review operations request `operator.read` and `operator.approvals`, without `operator.admin`. Server-held Ed25519 identities live separately under `.state/gateway-devices/{instance-uuid}/identity.pem`, with a private directory and 0600 key. Each instance has its own chat identity and a separate reviewer identity under `reviewer/`. Native pairing refuses silent scope upgrades, so review requests never expand the chat key. The WebSocket Origin is the actual control frontend origin; tenant Host routing remains server-selected. Both exact origins are configured in native allowedOrigins. Node's built-in crypto signs the gateway's nonce using the pinned v3 device-auth signature payload (distinct from gateway wire protocol 4). The native trusted-proxy policy and its constrained device approval remain active. No signing private key, gateway token, session JWT, or upstream connect frame is returned to the frontend.

## Automations addition (30 October)

The owner requested replacing the Tasks page with native-style Automations. See [11-automations.md](11-automations.md) for the implemented `/api/assistant/automations*` routes, schedule editor, run history, exact native permission boundary, idempotency and validation evidence. Existing task APIs remain available. Scheduler mutations use a separate explicitly paired host-only identity because the installed native protocol requires admin scope; no raw administration API or broader browser auto-pairing policy is exposed. New jobs are private tool-free agent turns, not external-service workflows.

## Implemented contract

All paths below are real routes. Instance-backed routes require a ready native workload. Current native recovery limitations are recorded in 08-runtime-findings.md; protocol integration tests are not proof of a successful live merchant, calendar, or model operation.

| Method | Route | Result |
| --- | --- | --- |
| GET | `/auth/csrf` | Pre-login or live-session CSRF token; session JWT remains HttpOnly |
| POST | `/auth/login`, `/auth/switch`, `/auth/logout` | Existing JSON demo authentication flow |
| GET | `/auth/me` | Current display identity |
| POST / GET | `/api/instance` | Create-own / read-own status |
| GET | `/api/assistant/capabilities` | API implementation states and caller's instance status |
| GET | `/api/assistant/sessions` | Main-agent sessions; `limit=1..100`, `offset=0..10000` |
| POST | `/api/assistant/sessions` | Create a session using required `idempotency_key`, optional `title` |
| GET | `/api/assistant/history` | `session_key`, optional `limit=1..100` and opaque `cursor` |
| POST | `/api/assistant/messages` | `session_key`, `message`, `idempotency_key`; returns 202 acceptance and `run_id` |
| POST | `/api/assistant/runs/abort` | `session_key`, exact `run_id`; cancellation of that run |
| GET | `/api/assistant/events` | SSE for `session_key`; optional `include_approvals=true` |
| GET | `/api/assistant/tasks` | Native ledger, optional `status`, `session_key`, `cursor`, bounded `limit` |
| GET | `/api/assistant/tasks/{task_id}` | One native task's status/result |
| POST | `/api/assistant/tasks/{task_id}/cancel` | Optional `reason`; cancels that task, not every delegated job or schedule |
| GET | `/api/assistant/approvals?session_key=...` | Paired reviewer's native pending approvals for that session |
| GET | `/api/assistant/approvals/history` | Native terminal decision history; optional cursor/limit |
| GET | `/api/assistant/approvals/{approval_id}` | Exact reviewer-safe proposal and short-lived opaque `review_token` if pending |
| POST | `/api/assistant/approvals/{approval_id}/resolve` | `decision` (`allow-once` or `deny`) and `review_token` |
| GET | `/api/assistant/openapi.json` | Authenticated schema for these frontend routes |

POSTs require both the exact configured Origin and `X-CSRF-Token`. JSON bodies are capped at 32 KiB for this namespace. Text messages are 1–4000 characters. Session keys are restricted to `agent:main:` followed by 1–128 letters, digits, underscores, or hyphens. No arbitrary file attachments, tool arguments, permission mode, external-delivery destination, or system provenance can be submitted. Message commands are suppressed; external channel delivery is disabled for this send endpoint. Approval APIs do not expose standing grants or `allow-always`.

Response projections omit native config, paths, handshake credentials, tool-result internals, and raw provider errors. Chat history is text-only for user/assistant messages. Task results are agent output, not independently verified external receipts. Approval presentations retain the known pinned reviewer-safe shape; unknown presentation/scope fields block review rather than hiding unreviewed changes.

## Framework-independent client

Use the tracked `clients/assistant.ts` from any browser frontend. It uses same-origin cookies, obtains CSRF tokens, and never handles a session JWT. The `assistant` export covers authentication/chat; `product` covers capabilities, tasks, and reviews.

```ts
import { assistant, product } from './openclaw';

await assistant.login('user1');
const capabilities = await product.capabilities();
const instance = await assistant.createInstance();
// Poll assistant.instance() until ready. Show an unavailable state on failure.
const { session_key } = await assistant.createSession(crypto.randomUUID(), 'My assistant');
```

Subscribe before sending. Wait for `ready`, load history, then enable sending. Render text as text, not unsanitized HTML. A delta may replace previous text; use `replace`, `sequence`, and `run_id`. A send acknowledgment is not an assistant reply or completed task.

```ts
const disconnect = assistant.subscribe(session_key, {
  includeApprovals: true,
  onReady: () => { /* reload history before enabling send */ },
  onChat: event => { /* update this run's text/state */ },
  onApprovalReplay: event => { /* populate pending reviews */ },
  onApproval: event => { /* update one review */ },
  onSessionEnded: () => { /* clear private UI state and sign in again */ },
  onReconnectRequired: () => { /* reload history, then establish a fresh stream */ },
});
const submission = crypto.randomUUID();
await assistant.send(session_key, 'Find a suitable evening for a movie.', submission);
```

Retain the same submission key when reconciling a lost acknowledgment. Do not automatically resend with a new key. Streams are live-only, have 15-second keepalives and a five-minute maximum, and have no replay cursor. Reconnect by reading history and pending reviews; do not claim gap-free events. Switching/logout/expiry or failed liveness checks close old streams. Already accepted native work may continue until explicitly cancelled; revoking browser access cannot undo an external action.

## Review integrity and receipts

1. Fetch the exact approval. Render the complete presentation, scope, target, amount/currency if present, warnings, expiry, and available supported decisions.
2. The server records only a hash of the opaque review token, bound to session, owner, instance, approval ID, and a hash of that full presentation. Expiry is the earliest of five minutes, session expiry, and native proposal expiry.
3. Resolve via CSRF-protected POST. The server fetches the current native proposal again, rejects a changed/terminal proposal, and atomically consumes the owner-bound token before forwarding the exact decision.
4. One concurrent caller can consume a token. No client-supplied reviewer identity, replacement proposal, permission escalation, or persistent grant is accepted.
5. Read back the native terminal record. A lost acknowledgment requires reading current state; the consumed token must not be blindly reused. A decision receipt is **not** evidence that a calendar event, email, payment, booking, or order completed. Those require a trusted provider adapter and independent provider read-back.

Native review support is not a universal commerce policy. A future executor must stop before external mutations and require an applicable approval outside the model's text. An agent saying “approved” or inventing an order ID is not authorization or completion evidence.

## Section 4 feature mapping and next adapters

The owner has selected this list to guide the frontend/API design. It does not supply provider credentials, authorize live purchases/messages, or resolve the research document's browser blockers.

| Feature | Current usable foundation | Still required |
| --- | --- | --- |
| Calendar | Auth, owner boundary, task/review surfaces | OAuth/PKCE, selected account/calendars, scoped reads, immutable write proposals, idempotency and provider read-back |
| Interactive websites | Chat/task/result/event APIs | Managed browser worker, persistent owner profile, site feasibility, safe observation/input transport |
| Movie tickets | Task progress and native reviews | Selected provider, real inventory/seat map, fees/hold reconciliation, reviewed checkout, verified provider receipt |
| Zepto | Same task/review foundation | Account/address/serviceability, exact SKUs, substitution choices, stock/fees, checkout and confirmed order |
| Task status/continuation | Native task list/get/cancel; same-session chat continuation | Durable application workflow checkpoints, waiting/reconciliation states, fencing and exactly scoped continuation |
| Browser takeover | Capability reports not implemented | Owner-bound expiring lease; pause and fence agent input; fresh observation before resuming |
| Reviews/receipts | Exact native proposals, one-use decisions, decision history | Provider-specific transaction enforcement and independently confirmed external receipts |
| Tenant connections | Existing instance/session ownership | Provider grant custody, revocation, selected account UI, per-owner connection records |
| Email | Optional capability only | Explicit mailbox grant, separate read/draft/save/send controls; no account creation |
| Schedules | Native Automations list/history/create/edit/pause/run/remove | External delivery and connected-service execution |
| Memory | Managed native maintenance visible in Automations | Editable typed preferences |
| Routines/channels/specialists | Later capability only | Reliable one-time workflows and identity/permission decisions first |

Proposed next routes below are **contracts only, not implemented endpoints**. Unsupported features are represented by capabilities, not fake successful responses.

| Planned route family | Required behavior before exposure |
| --- | --- |
| `/api/connections` | List only caller's grants; no access/refresh tokens in JSON |
| `/api/connections/google-calendar/authorize` and `/callback` | Server-owned redirect, PKCE, opaque state bound to live session/owner/instance, exact redirect URI and requested scopes |
| `/api/connections/{id}/disconnect` | Revoke the selected own grant and fail subsequent accesses closed |
| `/api/calendar/events` and `/availability` | Selected authorized account/calendar and bounded zoned interval |
| `/api/calendar/proposals` and `/{id}/commit` | Immutable reviewed event, exact attendees/invitations, idempotent provider write and read-back |
| `/api/workflows` and `/{id}/continue` | Typed calendar/movie/Zepto inputs, durable checkpoint/version, idempotency, explicit waiting/uncertain-result states |
| `/api/browser/view` and `/takeover` | Authenticated observation transport and owner lease; no cookies/credentials/OTP values in model-visible logs |
| `/api/browser/takeover/end` | Fence all human/agent input at lease transition; reobserve before agent resumes |
| `/api/receipts/{id}` | Provider-backed evidence, observation time, source, immutable action/proposal binding; distinguish unknown outcome from failure |

No arbitrary browser-node RPC, terminal, filesystem, gateway configuration, OAuth token export, or raw tool invocation is exposed to make these features appear complete. Provider/browser integrations must pass their own two-owner isolation and failure/reconciliation checks before capability states change.

## Validation and remaining runtime gate

Automated checks exercise a real local WebSocket server with pinned-protocol frames, PostgreSQL in disposable test databases, strict frontend inputs, identity/header filtering, SSE filtering/revocation, review changes/replay/expiry/concurrent consumption, and cross-owner token rejection. They do not run a model, connect a calendar, or purchase anything. TypeScript is checked in strict mode.

The 30 October owner-authorized runtime reset recovered both workloads with the same instance UUIDs and data volumes; complete native snapshots were restored and replacement native IDs reconciled after mount/private-health checks. Native stop/start passed after a hash-checked startup compatibility patch. Real gateway protocol 4, sessions/history, tasks, review replay, and User1 streamed Nemotron chat now work; see the latest 08 findings for the final two-user browser evidence. Host Docker-daemon restart and version-changing upgrades are distinct checks and have not been requalified. Never reset PostgreSQL, edit native phases, or remove data volumes to repair a connection.

Protocol references: [OpenClaw Gateway protocol](https://docs.assistant.ai/gateway/protocol), [building a client](https://docs.assistant.ai/gateway/clients). The implementation was checked against the **installed 2026.9.2 bundle schemas**, not assumed to match the moving latest docs.

## Prototype frontend update

The owner requested the frontend and named it anything other than the backend; its selected name is Morrow. Visit Morrow now opens `/workspace`, using the current control cookie and a per-page server session fence. See 10-prototype-frontend.md. The prototype uses product-neutral `/api/assistant/*` paths; legacy backend-named aliases remain developer-only compatibility.

## Chat activity update (30 October)

See 12-chat-activity.md. History now adds activities and optional in_flight; SSE adds normalized activity events. The previous text-only history statement is superseded by these safe tool/context projections. Activity streams use a separate read/questions/approvals identity; question contents and mutation remain unexposed.
