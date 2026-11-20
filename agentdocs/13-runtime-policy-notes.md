# Tenant execution and browser runtime policy — 30 October 2026

Owner explicitly requested full access without the Reviews page. This supersedes the earlier tool-free automation/review-flow milestone; tenant ownership, volumes, ingress and OpenShell network isolation remain mandatory.

`NemoClawRuntime.prepare_workspace_access` verifies native ID/mount ownership, privately backs up configuration and execution policy, and applies global/existing-agent full tool profiles with gateway execution security full and ask off. Native execution approval policy is changed through the pinned transactional SDK, running as sandbox UID 998 with explicit HOME=/sandbox and OPENCLAW_STATE_DIR=/sandbox/.openclaw. Existing unrelated state is preserved. Atomic configuration replacement retains native volume-owner UID/GID and mode0600. The provisioning worker also applies this policy; no API exposes arbitrary native configuration.

Heartbeat target none selects internal execution rather than an absent external delivery route. Native empty/no-work/quiet-hours skips may still be legitimate; internal target is not an external delivery integration. Morrow consumes owner-bound native scheduler history separately.

Browser configuration is enabled/headless with executablePath /usr/bin/chromium, defaultProfile openclaw, noSandbox true, and SSRF private-network access disabled. Both current tenant root filesystems have Debian Chromium156.0.8078.73-1~deb13u1 installed. Browser control in trusted-proxy mode needs a separate native gateway.auth.password; the runtime preserves it or generates it before the first browser call. This private credential never leaves the selected tenant configuration or its private backups, and does not change trusted-proxy ingress authentication.

## Container replacement prerequisite

Chromium is currently an additive rootfs installation, not baked into the pinned parent digest. A replacement image needs a reviewed reproducible build layer before browser capability can be claimed automatically available. The current matching package recipe is `apt-get update` followed by `apt-get install --no-install-recommends chromium=156.0.8078.73-1~deb13u1 chromium-common=156.0.8078.73-1~deb13u1 chromium-sandbox=156.0.8078.73-1~deb13u1`. Pin the Debian repository snapshot as well when producing the image, record the resulting digest, and validate sandbox startup with the documented inner-sandbox exception and both-owner browser isolation. Do not silently download a browser during a user HTTP request or pretend the parent image already contains this layer.

Actual policy readback succeeded for both tenants; native healthz returned200 through supported native sandbox exec. Browser RPC/navigation proof is tracked by the browser adapter validation, not established by this configuration alone.

## Chromium inner sandbox compatibility

Actual native browser startup rejected both user-namespace and setuid Chromium sandbox modes under the existing OpenShell NoNewPrivs1/Seccomp2 boundary. The owner authorized browser.noSandbox=true for inner Chromium only. OpenShell tenant/network/filesystem isolation, private ingress, volume ownership and API authentication remain unchanged; no privileged container, host network or Docker socket was introduced. Browser public-network validation must use the existing OpenShell egress proxy, not bypass it.
