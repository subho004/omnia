# Runtime and provisioning

## The `Runtime` protocol

`runtime/base.py` defines the seam between the control plane and a workload manager:

```python
class Runtime(Protocol):
    available: bool
    reason: str
    async def provision(self, instance: dict) -> RuntimeResult: ...   # runtime_id, upstream_url, container_name
    async def probe(self, instance: dict) -> bool: ...
```

`NemoClawRuntime` (`runtime/nemoclaw.py`) is the only real implementation. Tests inject a stub runtime through `create_app(settings, runtime, start_worker)`.

## Availability

`available` is true only when `.state/runtime-ready.json` exists and its `source_revision` equals `nemoclaw_source_revision` in `infra/runtime-versions.json`. Run `scripts/setup_runtime.py --activate` to create it. While unavailable:

- `POST /api/instance` returns `503 RUNTIME_NOT_CONFIGURED` and creates nothing;
- the worker does nothing;
- `/readyz` reports `runtime: not_configured`.

Activation permits provisioning. It does not mark any existing sandbox healthy. Every job still passes runtime, mount, ownership and ingress checks.

## Pinned toolchain

`infra/runtime-versions.json` is the manifest. It pins the NemoClaw tag and source revision, the OpenShell version and revision with darwin-arm64 SHA-256 checksums, the inference endpoint and sampling parameters, and the SHA-256 of every file the adapter patches (original and patched). Patches must match these hashes exactly, and the adapter refuses to apply them to unexpected input. This is how a rootfs or bundle change is "hash-pinned".

| Patch (`infra/`) | Purpose |
| --- | --- |
| `nemoclaw-state-volume.patch` | Binds the short sandbox name to the full instance UUID and volume. Fails closed if the binding is missing. A local customization, not an upstream flag. |
| `nemoclaw-trusted-proxy.patch` | Startup support for trusted-proxy gateway authentication. |
| `nemoclaw-policy-read-write.patch` | Network-policy schema change for read/write rules. |
| `openclaw-proxy-dns.patch` | Browser navigation resolves through the egress proxy. |
| `openclaw-proxy-snapshot.patch`, `openclaw-proxy-playwright.patch` | Browser snapshots and Playwright traffic use the proxy. |
| `openclaw-browser-observation.patch`, `openclaw-browser-catalog.patch` | Browser observation output and the lean tool catalog for local models. |

Other files in `infra/`: `lmstudio-provider.json` (provider definition), `browser-observation-transforms.json`, `morrow-browser-guard/` (plugin, see [Browser and egress](browser-and-egress.md)), `morrow-browser-guidance.md` (execution rules installed for the agent), and `postgres/init-app.sql`.

## Instance identity

| Item | Value |
| --- | --- |
| Instance id | Server-generated UUIDv4, stable across restarts and replacement |
| Sandbox name | `co-{uuid.hex[:16]}` (NemoClaw limit is 19 characters). A unique database constraint backs it. |
| Container name | Native OpenShell name, recorded after provisioning (`openshell-...`, up to 64 characters) |
| Volume | `openclaw-data-{uuid}` |
| Gateway port | Allocated per instance by the adapter (`NEMOCLAW_GATEWAY_PORT`) |
| Origin | `https://{uuid}.claw.localhost:{PUBLIC_PORT}/` |

`provision` refuses to run if `sandbox_name` does not match the UUID (`INVALID_INSTANCE_BINDING`).

## Provisioning flow

The worker (`provisioning.py`) claims one job with `FOR UPDATE SKIP LOCKED`. A job is claimable when it is `pending`, or `running` with an expired lease. It sets a 660-second lease and increments `attempts`. After 3 attempts the job and instance become `failed` with `RECOVERY_LIMIT`. The whole attempt has a 630-second timeout.

`NemoClawRuntime.provision` then runs, under a process-wide lock:

1. **Sandbox**: if none exists, run `nemoclaw onboard --non-interactive --name {sandbox} --no-gpu --events=jsonl` (600 second timeout). The sandbox phase must be `Ready`.
2. **Limits**: `docker update` caps the container at no more than 2 GiB memory (swap equal), 2 CPUs and 512 PIDs.
3. **Startup patch** (`patch_startup`): applies the hash-pinned rootfs fix.
4. **Browser navigation patch** and related browser bundles, including the browser guard plugin and guidance.
5. **Gateway configuration** (`configure_gateway`): trusted-proxy mode for the owner only:

```python
{"mode": "trusted-proxy",
 "identityScopes": {owner: ["operator.admin"]},
 "trustedProxy": {"userHeader": "x-claw-user", "allowUsers": [owner],
                  "allowLoopback": True, "requiredHeaders": ["x-claw-proxy"], ...}}
```

6. **Private ingress** (`forward`): a Unix-socket SSH forward to the agent port in a private directory (`/tmp/co-orch-{hash}`, mode 0700, owner-checked). A temporary TCP forward used during setup is then removed (`remove_tcp_forward`).
7. **Readiness**: probe up to 12 times, one second apart.
8. **Automation access** (`prepare_automation_access`): pairs the host-only scheduler identity. See [Automations](automations.md).
9. **Workspace access** (`prepare_workspace_access`): applies the tenant-only execution policy, keeping private backups of native policy files.

On success the instance row gets `status='ready'`, `runtime_id`, `upstream_url` (the Unix-socket endpoint) and `container_name`, and the job becomes `done`. On any exception both rows become `failed` with `PROVISIONING_FAILED`. Exception text is never logged or returned, because it can contain CLI output or credentials.

## Probe and recovery

`probe` confirms the sandbox exists, inspects the container, re-establishes the private forward, and ensures the egress policy and browser bridge. It returns false on any failure.

- **On startup**, every `ready` instance is probed and set to `unavailable` if it fails.
- **Every 10 seconds** the worker re-probes `unavailable` instances that have `runtime_id`, `upstream_url` and `container_name`, and returns them to `ready` when healthy. It never provisions or adopts unknown resources. Private ingress and browser egress recover after supported native stop/start with the original UUID and volume.

## Per-instance environment

The adapter builds the environment for NemoClaw commands from the manifest and settings, including `CLAW_ORCHESTRATOR_INSTANCE_ID`, `NEMOCLAW_GATEWAY_PORT`, `OPENSHELL_GATEWAY`, `OPENSHELL_WORKSPACE=default`, the inference endpoint and model, `NEMOCLAW_NON_INTERACTIVE=1`, and `NEMOCLAW_WEB_SEARCH_PROVIDER=none`. OpenRouter credentials are added only when `INFERENCE_PROVIDER=openrouter`. For LM Studio, only an environment reference is stored in tenant configuration, never the raw key.

## Inference routes

| Route | Default model | Notes |
| --- | --- | --- |
| LM Studio (`INFERENCE_PROVIDER=lmstudio`) | `qwen/qwen3.6-27b` at `http://127.0.0.1:1234/v1`, 200000 context, 4096 output | Sampling: temperature 0.7, top_p 0.8, top_k 20, presence penalty 1.5, reasoning off, 600 second timeout. No fallback model. Configure existing instances with `scripts/setup_local_inference.py`. |
| OpenRouter (`openrouter`) | `nvidia/nemotron-3-ultra-550b-a55b:free` | `OPENROUTER_MODEL` must be an explicit `:free` model. `inference.openrouter_preflight` checks the key, that the model is listed and zero-priced, and that it advertises tools and enough context. No paid or random fallback. |

## Limitations

- Replacement and browser dependency packaging are not fully qualified. Do not infer a complete replacement lifecycle from retained-instance checks.
- There is no upgrade, deletion or multi-host API. To change the pinned runtime, follow the procedure in `docs/agentdocs/05-runtime-and-data.md`.
- Exact volume attachment was verified for two instances. Validation status is the `validation_status` field in the manifest.
