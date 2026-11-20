# Automations

Automations are the instance's native cron jobs, exposed through a narrow adapter under `/api/assistant/automations`. The control plane never accepts a raw native RPC method, shell payload, environment, mount, webhook, recipient, provider or tool allowlist from a client.

## Routes

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/automations` | Search, enabled filter, `limit`/`offset`. Projected schedule and state, plus the exact native configuration revision. |
| GET | `/automations/runs` | History for all jobs or one `job_id`. Safe error projection, result summary, duration, timestamp. |
| GET | `/automations/{id}` | One owned job. No raw config, command, webhook, provider settings or gateway credentials. |
| POST | `/automations` | Name, instructions, typed schedule, `enabled`, `idempotency_key`. |
| POST | `/automations/{id}/update` | Supported changes plus the loaded `expected_revision` and `idempotency_key`. |
| POST | `/automations/{id}/run` | Explicit confirmation, `expected_revision`, `idempotency_key`. Returns 202: acceptance, not completion. |
| POST | `/automations/{id}/remove` | Only jobs created through Morrow. Revision and key required. History is kept. |

All routes need the usual cookie, session fence and, for POST, `Origin` plus CSRF. A job UUID only selects a job inside the authenticated owner's own runtime. Another user's UUID is denied.

## Schedules

Three types: a minute **interval**, a five-field **cron** expression with a validated IANA time zone, and a future **one-time** date converted to an explicit UTC instant. A native cron job with no zone is displayed as UTC, because the containers run UTC. New jobs start **paused** unless `enabled` is set.

New jobs run as isolated agent turns with `toolsAllow: []`, no paid fallbacks, a bounded timeout and `delivery.mode=none`. Results stay in the instance and appear in run history. Jobs that act on external services are not enabled.

## Managed jobs

Native system jobs are shown as managed:

- The heartbeat and skill-collection monitors are read-only. The heartbeat has manual run and history, but no enable switch, because native configuration owns its state.
- The memory-maintenance job can be paused, resumed and run. Its definition cannot be overwritten or deleted.
- Only jobs created through Morrow can be edited or removed.

## Idempotency and concurrency

`automation_mutations` records `(instance, owner, operation, idempotency_key)` with a request hash and outcome. The request is claimed before the native mutation, outside any long database transaction.

- A completed identical retry returns the saved result.
- The same key with different input returns a conflict.
- A pending or unknown outcome cannot be blindly retried.
- `update` uses an atomic native configuration-revision compare-and-set. `run` and `remove` do a fresh definition preflight, because the native protocol has no revision field for them.

This is not general exactly-once execution, and it is not an atomic external action with a receipt.

## Authority

The pinned OpenClaw gateway uses protocol 4 and the `cron.list`, `get`, `runs`, `add`, `update`, `remove` and `run` methods. Mutations require `operator.admin`. The adapter uses a separate **host-only** identity stored under `.state/gateway-devices/{instance-uuid}/automations/identity.pem`. Chat and review grants are not expanded, and `operator.admin` is not given to automatic browser pairing.

`scripts/setup_automation_access.py` pairs exactly that host public key, for the owner runtime, Control UI client, control origin, operator role and requested admin scope, through the pinned native approval SDK. It backs up existing pairing and control metadata privately first. New provisioning runs the same setup after native health and mount checks. It is an operator action, not an HTTP endpoint.

## Frontend behavior

The workspace sidebar links to `#automations` (`#tasks` redirects there). The page has search, All, Active, Paused and Run history views. It also has an editor, run-now confirmation, and a details and history menu. On mobile the table becomes stacked entries. Switching users or logging out clears schedules, search, editor fields and confirmations, cancels in-flight requests and blocks late responses from repainting. A normal end of the chat stream triggers a reload and resubscribe rather than an outage message.

## Notes

`automations.py` also contains helper functions (`global_automations_view`, `list_global_automations`, `get_global_automation`) for PostgreSQL-backed shared automations. No route calls them, and the SQL they contain is not used by the live API. See [Database](database.md#tables-not-used-by-the-current-code).

Design detail and live evidence: `docs/agentdocs/11-automations.md`.
