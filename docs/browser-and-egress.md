# Browser and egress

Each instance runs a managed headless browser (no GPU, private network access off) driven by the agent. Three layers keep that browser away from internal services and keep it on the destination the user named.

## 1. Public-only egress proxy (`egress_proxy.py`)

A host-side TCP proxy started with the API (`EGRESS_PROXY_HOST`:`EGRESS_PROXY_PORT`, default `0.0.0.0:18490`). Tenant browsers reach it as `host.openshell.internal:18490`.

- Only `CONNECT` tunnels are accepted.
- The destination hostname is resolved on the host (5 second timeout) and **every resolved address** is checked before any socket opens. Addresses in loopback, RFC 1918, link-local (including cloud metadata `169.254.169.254`), `0.0.0.0/8`, multicast, reserved, `::1`, `fc00::/7` and `fe80::/10` are denied. Because the check runs on the resolved address, DNS tricks cannot reach private ranges, and peer tenants' addresses are covered by the private ranges.
- Ports `22`, `1234` (LM Studio), `5432` (PostgreSQL), `18480`, `18481`, `18789` and `18790` are blocked.
- Denials return `403 Forbidden` and are logged by host, port and reason.

The proxy is the security boundary. The browser guard below is guidance, not enforcement.

## 2. Sandbox network policy and bridge

`ensure_egress_policy` adds an OpenShell network policy rule (`allow_host_openshell_internal_{port}`) allowing the sandbox to reach only `host.openshell.internal:{EGRESS_PROXY_PORT}`. `browser_bridge.py` is a stdlib-only script installed root-owned in the workload and run through native sandbox exec. It listens on `127.0.0.1:{port}` inside the sandbox's network namespace and relays to the fixed host proxy. It never chooses a destination from browser input. `--serve` runs the relay and `--ensure` checks and repairs it. `probe` calls `ensure_egress_bridge`, so the bridge is restored after a native restart.

Patches in `infra/openclaw-proxy-*.patch` make browser navigation, snapshots and Playwright use this proxy. See [Runtime and provisioning](runtime-and-provisioning.md#pinned-toolchain).

## 3. Browser guard plugin (`infra/morrow-browser-guard/`)

An OpenClaw plugin that checks the first browser navigation in each run:

- `suppliedHost(prompt)` extracts hostnames from the user's prompt. If exactly one distinct host is present (file-like suffixes such as `.md` or `.json` are ignored, and URLs with credentials are skipped), the guard remembers it.
- On `before_tool_call`, a first navigation to a different hostname is blocked with a reason telling the agent to use the supplied URL. It does not rewrite URLs, responses or final answers.
- Hooks: `llm_input`, `before_tool_call`, `agent_end`.

`infra/morrow-browser-guidance.md` supplies execution rules to the agent: copy the user's hostname exactly, use the managed browser tool rather than shell or curl, and stop at an observed HTTP 429 and report the URL and status without speculating on the cause. Tests: `tests/browser-guard.test.mjs` and `tests/test_browser_guard.py`.

## Browser API

`/api/assistant/browser*` (see [API reference](api-reference.md#browser)) calls fixed native browser-control operations (`/start`, `/stop`, `/tabs/open`). `POST /browser/tabs` runs `check_destination`, which rejects URLs that do not resolve to public addresses, before asking the browser to open the tab. This is defense in depth in front of the egress proxy.

## Limits

- Browser workflows are `requires_validation` in `/capabilities`. A live check passed native navigation and input, plus a Wikipedia search, through Morrow. A request for an e-commerce site reached the host and observed HTTP 429, so no product availability was verified.
- Browser takeover (the user steering the agent's browser) is not implemented.
- External calendar and merchant workflows are unqualified.
- `scripts/check_cdp_zepto.py` and `scripts/test_cdp_with_egress_proxy.py` are operator diagnostics for direct browser-protocol and proxy checks. They are not part of the test suite.
