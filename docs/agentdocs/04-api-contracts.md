# Prototype API contracts

The original control/proxy contracts below are implemented. The current separate-frontend contract and section 4 feature map are in 09-frontend-api.md; it adds curated chat, task, and review routes without arbitrary RPC forwarding. Use JSON for API responses, strict schemas that reject unknown fields, and no public target-selection parameter. Server-rendered form handlers may call the same service functions.

## Control host: `https://app.localhost`

| Method and path | Purpose | Authentication |
| --- | --- | --- |
| `GET /` | Render button state from session | Optional; signed-out view if absent |
| `POST /auth/login` | Select user1 or user2; issue session cookie | Demo-mode gate; pre-login CSRF/Origin |
| `POST /auth/switch` | Revoke current session; select other user | Control JWT + live session + CSRF/Origin |
| `POST /auth/logout` | Revoke current session; clear cookie | Control JWT + live session + CSRF/Origin |
| `GET /auth/me` | Return current display identity | Control JWT + live session |
| `POST /api/instance` | Create or return caller's own instance | Control JWT + live session + CSRF/Origin |
| `GET /api/instance` | Read caller's own provisioning/readiness status | Control JWT + live session |
| `POST /api/instance/launch` | Mint one-use browser launch form | Control JWT + live session + CSRF/Origin |
| `GET /healthz` | Service liveness only | No tenant or runtime inventory exposed |

The only resource mutation API in v0 is instance creation. Auth and launch endpoints support the requested browser flow; the read endpoint avoids waiting for a long-running create request. There is no arbitrary-user provisioning endpoint or public instance list/get-by-ID/update/delete/upgrade endpoint.

## Authentication bodies

```json
{"user": "user1"}
```

For login/switch, allow only the two seeded identities. CSRF can be supplied as a form field or `X-CSRF-Token`; content-type handling is explicit. Reject other fields and identities with `422`. Login while already signed in follows the same revocation rules as switching, so it cannot leave an old grant alive. Logout is safe to repeat; clear an absent/expired cookie and return the signed-out page without exposing session state. JSON clients receive `204`; browser forms receive `303 /`.

JWTs are delivered only via Set-Cookie. A successful JSON login returns safe identity data, not a token. A valid `/auth/me` response is `{"user":{"id":"user1","display_name":"User1"}}`.

## `POST /api/instance`

No request body is required; `{}` is accepted. Reject user IDs, UUIDs, image/command/network/mount fields, and unknown fields. Owner uniqueness provides natural idempotency without requiring an Idempotency-Key.

First request: `202 Accepted`, with `Location: /api/instance` and `Retry-After: 2`.

```json
{
  "instance": {
    "id": "8ce7da1b-5744-4b0b-9d41-538d7fe597a1",
    "status": "pending",
    "created_at": "2026-10-27T00:00:00Z"
  }
}
```

The UUID/time are illustrative. In-flight duplicate: `202`, same UUID. Existing ready instance: `200`, same UUID, `status: ready`. Existing failed or unavailable instance: `409` with the same instance ID and safe error code; no new resources or automatic data reset. A temporarily full worker queue returns `429` or `503` before accepting new work. Limit total instances to the two seeded owners.

`GET /api/instance` returns `200` with the same shape and current state, or `404 INSTANCE_NOT_CREATED`. Additional safe fields may include `updated_at` and an error code; never include private upstream addresses, Docker credentials, or gateway secrets. It does not create resources. Report live readiness conservatively; an instance is not launchable simply because an old DB row says ready.

## `POST /api/instance/launch`

Require an existing, currently ready own instance. Return `404` if absent and `409 INSTANCE_NOT_READY` if provisioning/failed/unavailable. The button's flow creates and polls first.

Success: `200 text/html`, a no-store auto-submit form (with a manual submit fallback) to the instance-origin handoff. The only body field sent there is the one-use ticket. The server chooses the target and final redirect; do not accept `return_url` or a user-selected instance hostname.

## Instance origin: `https://{uuid}.claw.localhost`

| Method/path | Behavior |
| --- | --- |
| `POST /__orchestrator/launch` | Exact control Origin + one-use ticket; set proxy cookie and `303 /` |
| `GET /{upstream_path}` and supported HTTP methods | Validate proxy session/owner/host, then forward to that owner's gateway |
| WebSocket on upstream-supported paths | Validate session/owner/host/Origin before upgrade, then bridge to that gateway |

The reserved `__orchestrator` prefix is never forwarded upstream. Reject unexpected methods there. Proxy known upstream protocols only; deny CONNECT/TRACE and unsupported upgrades. Preserve normal OpenClaw paths and safe query parameters without using them to select a tenant. Reject legacy tenant-selector paths instead of routing them.

Before returning HTML/assets, the proxy validates authentication too. Missing/expired proxy auth returns `401` with a safe control-page link; it must not serve another instance or expose a direct gateway login fallback. Forged, unknown, or mismatched instance host/owner returns generic `404`, without revealing who owns it. Do not redirect authentication errors into an unbounded login loop. WS failures are HTTP errors before upgrade; after upgrade use policy-violation close semantics (1008) for revocation/expiry.

## Error envelope and transport behavior

```json
{
  "error": {
    "code": "INSTANCE_NOT_READY",
    "message": "Your instance is still being prepared.",
    "request_id": "server-generated-correlation-id"
  }
}
```

| Status | Use |
| --- | --- |
| `401` | Missing/invalid/expired/revoked session |
| `403` | Invalid CSRF or Origin on a known control/launch route |
| `404` | No own instance; unknown or unauthorized target host/resource |
| `409` | Known own instance not ready, or safe runtime-resource conflict |
| `422` | Invalid input/schema |
| `429` | Per-session/rate/concurrency limit |
| `502` | Authenticated own upstream fails unexpectedly |
| `503` | Runtime/control dependency unavailable |
| `504` | Upstream/setup deadline exceeded |

Set no-store on auth, launch, metadata, and proxy responses. Avoid detailed runtime exceptions in client errors. On an instance-host auth failure, do not reveal whether that hostname corresponds to a running tenant. Log correlation ID, safe event type, caller subject, own instance ID, and outcome only.
