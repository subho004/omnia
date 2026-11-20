# Browser connection and network findings

Updated 31 October 2026 (Asia/Kolkata). This records the implemented connection foundation and a remaining public-navigation blocker. It is not a claim that arbitrary website browsing is ready.

## Implemented adapter

`browser_api.py` exposes owner-selected status, connect, disconnect and public-URL tab creation beneath `/api/assistant/browser`. It reuses cookie/live-session ownership, exact Origin/CSRF for writes and the private selected gateway. No browser profile, node, target, native path, RPC method, debugging URL or instance selector can be supplied by a client. The server chooses the native dedicated profile and gateway-local browser. It requests native `browser.request` through the already explicitly paired host admin identity; no general admin RPC is exposed.

The browser request API contract was read from installed 2026.9.2 shipped source:

- `browser-gateway-contract-B6OC_gCs.js`: method browser.request, operator.admin scope.
- `browser-cli-shared-Co4TmZyV.js`: method/path/query/body/timeout request structure.
- `client-x-IUPjVX.js:451-468`: GET /tabs and POST /tabs/open.
- `plugin-service-CaWAXW9h.js:2853-3031`: fixed host target uses the selected gateway's local browser and returns the route body.

Public URL input rejects credentials, non-HTTP(S), nonstandard ports, literal private/loopback addresses and local hostnames. DNS checking rejects any currently resolved private address. This input check is not DNS-rebinding or redirect protection by itself. Native/browser/OpenShell enforcement remains necessary.

## Real runtime validation

Both retained tenant containers have Debian Chromium 156.0.8078.73 and chromium-sandbox installed additively. This is current rootfs installation, not proof that the original pinned runtime image contains Chromium. Replacements need the documented image/build qualification; do not silently claim browser-binary durability from the data volume alone.

The native managed browser could not launch its own nested sandbox: the OpenShell-managed gateway process reported NoNewPrivs=1 and Seccomp=2, and Chromium's setuid helper failed with `PR_SET_NO_NEW_PRIVS` / namespace `Operation not permitted`. With the owner's full-access prototype scope, inner Chromium uses `browser.noSandbox=true` **inside the existing OpenShell tenant boundary**. OpenShell restrictions, container network topology, private ingress and separate data volumes were retained. This does not make inner Chromium's own sandbox available.

The browser-control bootstrap uses gateway.auth.password when gateway auth mode is trusted-proxy. Provision the credential privately before first browser service startup to avoid generation/reload races; never return it through the frontend. Runtime configuration preserves the credential and trusted-proxy mode. No password is reproduced here.

Native RPC lifecycle passed for both identities: start -> running=true/cdpReady=true -> create exact about:blank -> list -> stop -> running=false. User1 and User2 reported disjoint target-ID sets. User1 new target was `73AB13059E7CCA2CE2C6319CF0ADCBE9`; User2 new target was `42F234273E5B160435B1C7AABAA54258`. The tests did not use model tokens, host browser profiles, published CDP ports or external account data. Projected observations are retained privately in `.state/browser-native-observations.json`. Both browsers were stopped at the end of these lifecycle probes; subsequent UI checks have their own lifecycle.

Fifteen focused tests passed, including fixed-operation projections, forbidden selectors, URL/DNS rejection, generic native errors and real application authentication/CSRF gates. Most connection tests use a controlled gateway and are separate from the native lifecycle proof above.

## Public navigation blocker

Keep native `browser.ssrfPolicy.dangerouslyAllowPrivateNetwork=false` and no new network grants.

Actual native navigation to https://example.com was rejected before loading the page:

> strict browser SSRF policy requires an IP-literal URL because browser DNS rebinding protections are unavailable for hostname-based navigation

The installed source `chrome-CtUCaDWQ.js:240-252` confirms two distinct restrictions:

1. Explicitly proxy-routed browser profiles cannot enforce strict private-network rejection.
2. Explicit strict mode rejects hostname navigation unless the host is specifically allowlisted or an IP literal.

The same file at 2773 and 2895 removes inherited proxy variables and adds `--no-proxy-server` unless browser.extraArgs explicitly selects a proxy. Merely inheriting OpenShell's HTTP_PROXY therefore does not connect Chromium to the supported OpenShell proxy boundary.

Native OpenShell exec probes used the existing proxy at 10.200.0.1:3128. An explicit HTTPConnection to that proxy, with absolute request URLs (avoiding urllib/NO_PROXY loopback bypass), returned 403 for BOTH owners for:

- public http://example.com/;
- loopback http://127.0.0.1:18789/;
- User1 container http://172.20.0.2:18789/;
- User2 container http://172.20.0.3:18790/;
- private http://10.0.0.1/;
- metadata root http://169.254.169.254/.

A public HTTPS CONNECT to example.com was also denied with 403. No response bodies or credential endpoints were read. These are bounded denial observations under the **current** policy. They do not establish a general public-only proxy policy, arbitrary DNS rebinding safety or the safety of a future wildcard/public-internet grant. An earlier urllib loopback probe automatically bypassed the proxy and reached User1's own gateway; that observation was explicitly excluded from proxy-isolation evidence.

The local OpenShell checkout contains a partial Docker-driver source tree, not the pinned full network-proxy implementation. General resolver/socket/private-range enforcement was not established from that source. Do not infer it from a few 403 responses.

## Required tradeoff before broad browsing

A supported destination boundary must enforce public-only access for actual resolved connections, redirects and subresources while preserving tenant separation. Then native proxy-routing/strict-mode compatibility needs qualification against the pinned browser implementation. An exact trusted public-site allowlist is narrower than arbitrary browsing and must be reported as such. No production allowlist, wildcard grant, proxy extraArgs, private-network relaxation or native source patch was applied as a shortcut.

The Connections UI may truthfully expose browser process connection and isolated tabs. It must keep browsing capability at requires_validation and clearly state that website navigation is restricted. A connected CDP process does not prove public browsing, login, browser takeover or connected-service workflows.

## Resolution: Dedicated Public-Only Egress Proxy (Option 3 implemented)

On 31 October 2026, the owner approved Option 3 to allow safe arbitrary public website browsing without requiring domain-by-domain allowlisting:
1. `claw_orchestrator/egress_proxy.py` runs a dedicated `PublicEgressProxy` on port 18490 on the host bridge.
2. The proxy intercepts CONNECT requests, resolves target hostnames on the host, and enforces that every resolved IP is a global routable address (`is_allowed_public_ip`). It hard-drops all RFC 1918 private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`), link-local/cloud metadata (`169.254.169.254`), and peer tenant container IPs (`172.20.0.3`).
3. Because the proxy acts as a transparent CONNECT tunnel for permitted public destinations, Chromium directly verifies origin TLS certificates (no MITM or untrusted custom CA warnings).
4. Tenant OpenClaw browser configuration routes via `--proxy-server=http://host.openshell.internal:18490`.
5. OpenShell sandbox policy explicitly authorizes egress to `host.openshell.internal:18490` for `/usr/lib/chromium/chromium` and `/usr/local/bin/node`.

## Follow-up: assistant tool use and provisioning discrepancy (31 October)

A real User1 native `browser.request` opened `https://example.com/` and returned the title `Example Domain` using the currently running browser. This is one public navigation, not evidence for Zepto, browser actions, redirection safety, replacement durability, or cross-tenant isolation. The two retained runtimes had different proxy configurations at readback; the currently checked-in provisioning code uses the loopback bridge. Chromium implicitly bypasses proxies for loopback unless explicitly told otherwise, so provisioning now adds `--proxy-bypass-list=<-loopback>`. This code change has not been applied to or validated on the retained runtimes, and must not be treated as proof that other direct paths are blocked.

An authenticated Morrow chat run requested browser navigation to Example Domain. Its history recorded a tool-discovery result for the browser, followed by a literal tool-call markup in assistant text and a final answer; it did not record a completed browser navigation or snapshot tool call. The answer must not be taken as verified browser evidence. A separate small LM Studio OpenAI-compatible request did return a structured tool call, so this does not establish that the provider lacks tool-call support; the native agent/model interaction needs further diagnosis. Browser workflow capability remains unverified. No model, inference provider, native runtime, browser profile, network policy, or customer data was reset in this check.

## Exact prompt and runtime incident — 31 October follow-up

User2 authenticated Morrow test used the exact request: `Use the browser to open zepto and search for "Monster" in its searchbar, then tell me what the available products are.` The model invoked a shell command which attempted native browser control against `www.zeptomart.com`; the DNS lookup returned EAI_AGAIN. Its final answer did not list observed products. This is a failed end-to-end test. A separate User1 native browser navigation to `https://www.zepto.com/` reached a browser error page displaying HTTP 429; no search or products were observed.

A User1 experiment to disable native tool-search compaction requested a gateway restart while the existing config file had root ownership. The gateway could not read the config, exited, and OpenShell recorded the sandbox phase Error. The pre-experiment tool-search configuration was restored and the config file ownership corrected to match the volume owner; the same native container now runs and reports Docker healthy. OpenShell nevertheless remains in Error and its supported `nemoclaw ... recover` did not clear that phase. The control-plane status is unavailable based on failed native probe; no phase metadata was edited. User1 UUID, native container, volume, data and backups remain retained. User2's native phase was Ready and probe passed before the exact prompt test. Fixing the browsing task still requires a supported User1 recovery, then verification of actual native tool invocation and the merchant's response. Do not treat Docker health or a site search index as proof of a successful live user-specific search.


## Raw transcript correction and recovery follow-up — 31 October

The authoritative archived native agent SQLite transcripts were inspected rather than relying on the frontend projection. Some earlier notes inferred that a browser tool call only described the tool; that conclusion was incomplete. The wrapper contains both `tool` metadata and an executed `result`, and successful browser-open results included real target IDs. The important failures are the actual inputs/results:

- One run executed `echo "Opening Zepto..."` and then fabricated generic product suggestions.
- Another called the CLI with `openclaw browser open url=https://www.zepto.com`, producing `Invalid URL: url=https://www.zepto.com`; a later genuine browser navigation returned `ERR_PROXY_CONNECTION_FAILED`.
- Another genuinely opened the URL but supplied invalid act arguments (`type: type` at the image-format field); validation rejected it. Later navigation returned `ERR_HTTP_RESPONSE_CODE_FAILURE`, and web_fetch returned no content.
- A separate native snapshot observed the Zepto HTTP429 error page. None of these runs searched an observed search field or returned verified products.

Native exec results can carry `isError=false` despite an explicit nonzero command exit. A green frontend Completed label does not establish successful navigation. These source transcripts and their original contents were preserved during recovery; all 448 archived events matched after restore. The model/tool invocation and browser-network issues remain distinct and unresolved. The User1 replacement has no Chromium binary because the earlier installation was additive rootfs state; no automatic browser readiness is claimed.

## Browser transport qualification — 31 October, after User1 recovery

This section supersedes the earlier unresolved Chromium/proxy statements above. User1 was recovered through native rebuild and full snapshot restore, retaining its UUID and named volume; no native phase was edited. Chromium 156.0.8078.73 was restored additively. Both retained owners now have the same browser configuration, loopback bridge and five hash-pinned compatibility patches recorded in `infra/runtime-versions.json`.

The old bridge's process-name check could match its own shell and skip starting. `browser_bridge.py` now starts through supported native sandbox execution, verifies its process identity/network namespace and checks that the host proxy rejects a private destination. The bridge tunnels only to the fixed host egress endpoint through the supervisor. Native browser navigation and two snapshot layers were resolving DNS locally despite an explicit proxy. Their patches propagate proxy policy and omit local DNS only for the explicitly configured proxy mode. Direct mode, strict policy, scheme and credential checks remain enforced; actual resolved destinations are checked at the host proxy before dialing.

Actual native Chromium navigation and snapshots succeeded for a public documentation page in both owners. Browser requests to loopback gateway, the other owner's container/gateway and cloud metadata returned the proxy's public-only denial in both directions. These are bounded connection checks, not exhaustive browser security or DNS-rebinding qualification. The original parent image digest is unchanged. Chromium and native bundle patches are current rootfs additions; image rebuild/replacement durability remains unqualified.

The original exact Morrow prompt was submitted through the real authenticated UI. Inspection of raw SQLite transcripts and provider streaming packets exposed a further model continuation failure: after a real browser open, the local provider sometimes returned only reasoning and stopped. Native isolated finalization could then emit invalid tool markup or invent products. These are failed runs, even when the browser-open activity is green. The native version no longer reads TOOLS.md for environment notes; managed guidance now resides in workspace AGENTS.md. Replays with explicit local model reasoning/sampling controls produced structured snapshot calls. Live qualification is recorded separately below after its terminal tool results are inspected.

A separate clean host Chromium tab observed `www.zepto.com` returning HTTP429. No product availability can be established from that response. Do not report likely products as observed inventory.

Browser open/navigation tool results now include a fresh bounded page snapshot (12000 characters), retaining native untrusted-content wrapping, same-tab tracking and snapshot-unavailable errors. The trusted built-in browser extension stays directly visible during native tools-mode discovery; the full remaining catalog remains available on demand. This changes schema visibility only for a tool already allowed by native policy, not permission grants. Managed browser notes are placed first in native workspace AGENTS.md so the local model sees the required observation steps before longer defaults.


## API and native restart recovery, 31 October late run

A native stop/start closes its private SSH forward. Curated GatewayClient now asks the owned runtime to restore that forward before opening protocol4; per-instance locks serialize repairs without blocking the other owner. A bounded fault check terminated only User1's exact API-owned forward process and authenticated session listing recovered to200 for both owners without an API restart. Native SSH dead-peer detection can briefly return503 after sandbox restart; frontend recovery retries authenticated bootstrap without resending messages.

Morrow now presents Reconnecting during transient API/network failures, preserving the selected conversation and draft. Controlled browser tests passed for a single sessions503 and for one aborted activity-stream request: automatic return to Online, draft retained, zero POST messages. This is client recovery evidence, separate from merchant access.

API startup previously swallowed an egress listener bind failure, leaving chat apparently available but browser traffic broken. Startup now propagates that failure; a real occupied-port integration test verifies refusal to start. Tests bind ephemeral egress ports to avoid competing with the running local service. The API was restarted with its own18490 listener verified, and the native browser bridge readiness check passed afterward.


## Retained-workspace recovery qualification, 1 November 2026

Startup could mark a retained workspace unavailable on a transient health failure, but the worker only reconciled provisioning jobs. It now rechecks existing unavailable workloads every10seconds, requiring recorded runtime/container/upstream metadata, native probe success, and an unchanged owner/resource mapping before setting control-plane status ready. Failed provisioning remains failed; no new job, native identity adoption, native phase write, or volume replacement occurs. Unit/integration checks cover two owners, unhealthy resources staying unavailable, and replacement metadata invalidating stale health.

Native probe now also re-ensures its fixed browser bridge after a supported restart, with per-instance bridge locks. Gateway health and exact native identity/mount checks precede this. A live controlled check changed only User1's orchestrator availability to unavailable; the application worker recovered it after9.07seconds through actual probes, preserving UUID/native ID/container/volume/upstream. Both owners then returned sessions200. Evidence: `.state/backups/user1-recovery-20261031/retained-recovery-evidence.json`. No native phase or readiness was written by the test helper.

The HTTPS runner now limits graceful shutdown drain to10seconds so long-lived activity streams cannot indefinitely retain the browser egress listener during an authorized server restart. Startup still refuses an occupied listener instead of silently disabling it. Final suite at this point:189passed,4skipped.


## Failed navigation observation repair (1 November)

The subsequent live dense27B run exposed a missing error observation: `browser.navigate` raised Playwright `net::ERR_HTTP_RESPONSE_CODE_FAILURE` and discarded the resulting page. The model never received the actual HTTP429 and kept trying navigation variants. The pinned observation patch now handles only this explicit browser HTTP-response-failure code by attaching a bounded same-tab snapshot, preserving `isError=true`, `ok=false`, requestedUrl, and the original error. Other errors and cancellation are rethrown; there is no navigation retry. The snapshot's own URL remains visible and must not be confused with a successful requested navigation.

The helper previously dropped top-level result flags when appending state; it now preserves them. The original and final bundle hashes remain pinned, with one explicit transition from the previously deployed known patch. Both tenant bundle files were verified at `13fcd103e2106de15be68c0f22550a5112f299fc45e5d37fabfb4e409dc5899d`; the current native gateway needs a supported restart to load changed modules. A real native Browser tool test opened its own example.com tab, navigated once to zepto.com, received the failed-navigation flag plus actual HTTP429 snapshot, and closed only that test tab. Evidence is in `native-navigation-error-observation.json`. This is transport/error-observation proof, not product availability.
