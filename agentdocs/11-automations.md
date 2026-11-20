# Morrow Automations — 30 October 2026

The owner requested replacing the Tasks page with an Automations page using the supplied native UI screenshot as the layout/behavior reference. This authorizes a curated scheduler adapter in addition to the existing task APIs. The sidebar now links to `#automations`; `#tasks` redirects there. Morrow branding, login/session fencing and owner isolation remain unchanged. Existing `/api/assistant/tasks*` APIs remain available; a task ledger entry is not a schedule definition.

## Page

Dark, wide schedule table in the existing Morrow shell: search; All / Active / Paused / Run history; New automation; name, schedule, next and last run; enabled toggle; run-now confirmation; details/history/edit/delete menu. On mobile, table rows become stacked entries. The side status rail is hidden on this page. Creation starts paused unless the user explicitly enables it. Schedule editor supports minute intervals, five-field cron with a validated named time zone, and a future one-time date converted to an explicit UTC instant. An omitted native cron zone is shown as UTC because the verified containers run UTC.

Native system heartbeat and skill-collection monitors are shown as managed, with read-only definitions. Heartbeat has manual run and history but no enabled switch: its desired state is owned by native heartbeat configuration. The existing memory maintenance job can be paused/resumed and run, but its prompt/definition cannot be overwritten or deleted here. User-created Morrow jobs can be edited and deleted, with confirmation before manual runs or deletion. Existing jobs are not silently migrated or reset.

## Authenticated routes

All routes are beneath `/api/assistant`, use the existing cookie/live-session/owner lookup and page session fence, and require exact Origin plus CSRF on POST. UUIDs select a job only inside the authenticated owner's runtime. Unknown input fields are rejected.

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/automations` | Bounded search, enabled filter, limit/offset; projected schedule/state and exact native configuration revision |
| GET | `/automations/runs` | Bounded all-job history or exact `job_id`; safe error projection, result summary, duration and timestamp |
| GET | `/automations/{id}` | One owned native job; no raw config, command, webhook, provider settings or gateway credentials |
| POST | `/automations` | Name, instructions, typed schedule, enabled flag and idempotency key |
| POST | `/automations/{id}/update` | Supported changes plus loaded revision and idempotency key; native revision CAS |
| POST | `/automations/{id}/run` | Explicit confirmation; exact loaded revision and idempotency key; acceptance is not completion |
| POST | `/automations/{id}/remove` | Morrow-created jobs only; exact loaded revision and idempotency key; history retained |

`automation_mutations` in PostgreSQL stores owner/instance-bound request hashes and outcomes. The request is claimed before mutation, outside a long DB transaction. Identical completed retries return their saved result; changed input with the same key conflicts. Pending/unknown outcomes cannot be blindly retried. Native update performs atomic configuration-revision comparison. Run/removal perform a fresh definition preflight; the native protocol does not offer the same revision-CAS field for those operations. Do not claim general exactly-once execution or an atomic external action/receipt.

## Runtime authority and limits

The installed gateway uses protocol 4 and `cron.list/get/runs/add/update/remove/run`. Its cron mutations require `operator.admin`. A separate host-only identity lives under `.state/gateway-devices/{instance-uuid}/automations/identity.pem`. Neither chat nor review grants are expanded, and `operator.admin` is not added to native automatic browser pairing. `scripts/setup_automation_access.py` pairs only the exact host public key, owner runtime, Control UI client, control Origin, operator role and requested admin scope through the pinned native approval SDK. Existing pairing state and control metadata are backed up privately first. New provisioning performs the same constrained setup after native health/mount verification. This is an operator/provisioning action, not an HTTP endpoint.

The transport scope is broad because the native protocol requires it; the public adapter is narrow. No arbitrary native RPC, provider/model selection, shell/script payload, environment, mounts, webhook/channel recipient, or tool allowlist can be supplied. New jobs use isolated agent turns with explicit `toolsAllow: []`, no paid fallbacks, a bounded timeout, and `delivery.mode=none`. Results stay in the owner runtime and appear through history. Calendar/browser/commerce connections and general external-action automations are not implemented.

## Session and reconnect behavior

Switch/logout clears the schedule list, search, details, confirmation, editor fields and all private in-memory state, cancels requests, and prevents late responses from repainting it. Normal expiry of the bounded chat SSE stream is no longer treated as a workspace outage: the client reloads session/history state and subscribes again without resending a message. Actual unavailable API errors still fail closed.

## Validation

Evidence is recorded after the final live checks in 08-runtime-findings.md. Tests use isolated disposable PostgreSQL databases and a real WebSocket server, including owner isolation, strict inputs, CSRF/Origin, managed-job protection, configuration revision conflicts, idempotency, concurrent manual runs, lost acknowledgments, safe projections, and separate host identities. Native checks use only a temporary paused synthetic job; existing heartbeat/memory definitions are preserved.

### Completed evidence

- 63 automated tests pass; Ruff and JavaScript syntax checks pass. A disposable PostgreSQL database is used for unit/protocol fixtures. The existing Starlette/httpx deprecation warning remains.
- Installed Chrome at 1280×720 and 390×844: real native jobs listed; search, All/Active/Paused tabs, interval create, enable/pause, cron edit with Asia/Kolkata, one-time create/remove, manual-run confirmation, run history and exact result display verified. No horizontal overflow at mobile size.
- Exactly one small live synthetic schedule run completed in about 5.4 seconds and returned `AUTOMATION_READY_4631`. It remained paused afterward. The temporary interval/cron and one-time jobs were deleted; the original three managed jobs were untouched. The completed run remains in native history after schedule deletion. No additional model calls were needed for the other checks.
- Live authenticated User2 requests for User1's actual automation UUID were denied for both read and manual run. User switching while an editor held an unsaved name/instructions closed the dialog, cleared all its fields and schedule rows, and locked the old page. User2's list contained only its own native jobs.
- A controlled short SSE response reproduced normal `RECONNECT_REQUIRED`; the browser renewed the subscription and retained online schedule controls. This is a specific transport regression check, separate from the real native CRUD/model evidence.
- Browser fallback: in-app tab acquisition returned `browser.user is unavailable`; installed Chrome through Playwright CLI was used instead, as authorized. Final evidence is outside the repo at `/tmp/claw-orchestrator-qa/automations-final.png`, `automations-mobile.png`, `automations-run-history.png`, `automations-reconnect.png`, and `automations-session-cleared.png`.

Sources checked: the installed 2026.9.2 protocol schemas/cron handlers and [native automation management](https://docs.openclaw.ai/automation/cron-jobs/managing-jobs). Community research on explicit time zones: [The agent scheduled the nightly job in its own local time, and the container ran it seven hours off](https://dev.to/jeff_pdc/the-agent-scheduled-the-nightly-job-in-its-own-local-time-and-the-container-ran-it-seven-hours-off-3pl6). Durable idempotency research: [Idempotent drafts: keeping a scheduled agent from writing the same post again](https://dev.to/craig_solomon/idempotent-drafts-keeping-a-scheduled-agent-from-writing-the-same-post-again-g3j). Native/primary code, not community claims, determines this adapter's supported capabilities.
