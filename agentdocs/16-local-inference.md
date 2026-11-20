# Local authenticated inference — 31 October 2026

The owner selected LM Studio `qwen/qwen3.5-9b`, then supplied a token, superseding the earlier no-auth requirement and OpenRouter default. `.env` stores `LMSTUDIO_API_KEY` with mode 0600 and is ignored. Runtime command environments strip this secret unless explicitly performing credential setup; command output and public presentations redact colon-shaped LM Studio credentials.

Both retained native workspaces now use a 200000-token context configuration and 4096-token output cap, with no model fallback. LM Studio reported a loaded context of 262144. That accommodates the configured limit; no full-context workload or performance qualification was run.

## Native boundary

`infra/lmstudio-provider.json` defines an endpoint-limited OpenShell provider profile. It permits only the managed host bridge on port 1234, GET `/v1/models` and POST `/v1/chat/completions`, for the listed native executables. Its private address rules apply to that qualified endpoint, not general browsing. Browser egress policy remains unchanged.

Run `uv run --locked python scripts/setup_local_inference.py` as an operator with the private environment. It backs up the host native provider database, validates/imports the profile, creates or refreshes each owner's provider credential, attaches that provider to the authoritative sandbox, backs up and updates the native model configuration, and requests a gateway restart with SIGUSR1. Tenant configuration contains only a scoped native credential handle; the real token stays in the host provider credential store and private `.env`. Never replace this handle with the raw key.

The scoped handle must match the current provider injection namespace. A generic unscoped placeholder caused `credential_unavailable` and is not used. Gateway reload after configuration change is necessary to replace its cached model route.

## Compatibility limits and evidence

The legacy cluster `inference.local` route returned 503 for the local compatible endpoint. The installed NemoClaw inference helper committed its configuration but failed its gateway restart check under our trusted-proxy authentication. A custom local provider profile through supported OpenShell import/create/attach operations is the verified route used here; it is not a claim that legacy NemoClaw onboarding/replacement automatically recreates this setup. Reapply and revalidate this operator setup after provisioning or replacement until integrated into that lifecycle.

Verified: authenticated host model discovery and a small direct completion; native provider model discovery inside both isolated sandboxes; real owner-authenticated Morrow chat completion in both workspaces, each with a distinct expected marker and no tools or approval requests. Python suite: 158 passed, 4 existing review-related skips. Ruff passed. Original instance UUIDs, data volumes, and private ingress remain retained. This verifies local inference wiring, not the entire 200K context or external browser actions.

The owner's existing Test automation was manually run once through its authenticated, revision-checked Morrow API. Its new run completed successfully with no reported error, confirming that scheduled execution now also reaches the local model. Its definition and enabled state were preserved.


Recovery setup now accepts `uv run --locked python scripts/setup_local_inference.py --user user1` (or user2) to avoid touching the other owner. Provider attachment is asynchronous: the script waits for a scoped handle before writing the route. Configuration ownership is taken from the tenant volume directory rather than potentially incorrect ownership of an existing config file. The 31 October User1 native rebuild needed its selected endpoint-limited provider reattached and its current scoped handle rebound; authenticated Morrow chat then returned the exact recovery marker. No raw provider key was placed in the tenant configuration.

The 31 October browser investigation found that tool-search compaction and provider defaults need explicit local-model settings. Native tools use supported tool-search mode `tools` with a default search limit of two, retaining the full catalog without exposing all schemas on every turn; its model params carry an explicit LM Studio `reasoning_effort=none` payload and temperature 0.2. The tried `chat_template_kwargs.enable_thinking=false` and `reasoning=off` payloads were ignored by the compatible endpoint and were removed. Native rendered-prompt logging confirmed that `reasoning_effort=none` closes the initial think block, and an identical post-tool replay then emitted a structured snapshot call. A native `thinkingDefault=off` label alone did not disable provider reasoning. Qualification must inspect provider packets and actual subsequent structured tool calls; a successful first call or a fabricated final answer is insufficient.

## Stronger-model canary authorized — 31 October

The owner explicitly authorized downloading and testing a stronger local model after raw 9B traces still showed unsupported browser actions and retries following an observed HTTP429. The candidate is `qwen/qwen3.6-35b-a3b`, LM Studio's approximately 20.4GB 4-bit MLX variant. This Mac reports an M4 Pro and 48GiB unified memory. Candidate download, memory estimate, direct-provider checks and a per-session native canary precede any default change. The existing 9B files and both native defaults remain retained at this stage. See the final qualification section for the eventual result; a download or model-card claim is not live browser proof.

Primary references: [LM Studio candidate](https://lmstudio.ai/models/qwen/qwen3.6-35b-a3b), [Qwen model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B). The model card documents tool use and 262144 native context; its non-thinking sampling recommendation is temperature0.7/top_p0.8/top_k20/presence_penalty1.5. The existing native model/tool result format is used for local preflight; actual native transcript verification remains required afterward. No cloud inference or paid fallback is selected.


## Restart and stronger-model evidence, 31 October late run

The stronger 4-bit MLX model finished downloading and loaded at 200000 context, one parallel request. All four safetensors hashes matched their published LFS hashes at pinned revision `0c4a20a6437ae5985ddc9eb1a3f122ee6c151c3b`; private local evidence is in `.state/backups/user1-recovery-20261031/candidate-ranges/all-weights-verified.json`. A successful download/load is not behavioral qualification. Direct first-call preflight produced valid browser calls, but the post-429 stop criterion failed. The first live 35B canary (`658919d8-0ce5-487f-bfa7-9b4c6688f652`) observed Zepto's HTTP429 and retried through multiple read-only tools; it was stopped and did not establish inventory. Do not promote this candidate on that evidence.

The native `sessions.patch` model selection uses the default selection scope unless configured otherwise. An initial canary inadvertently changed User1's default; that was restored to 9B. Both owners and configuration/setup paths now set `agents.defaults.modelSelectionScope=session`. Later canary session records show explicit provider/model overrides while User1's primary remains 9B. Candidate registration does not authorize changing User2's default.

A supported User1 sandbox stop/start exposed a stale scoped provider reference. The saved literal namespace can become invalid after a native start, returning `500 credential_unavailable` before any tool executes. The local setup now writes native environment SecretRefs to both provider apiKey and the existing inference auth profile keyRef, using the native transactional auth store. The real credential remains on the host. It resolves the current sandbox-injected handle at gateway startup. Setup uses supported stop/start instead of SIGUSR1, verifies original identity/mount and re-ensures the browser bridge. A second supported start reached gateway ready and subsequent LM Studio requests, replacing the prior credential failure. Full replacement provisioning remains a separate qualification.


The positive35B canary `d671bd6c-e215-4c51-9854-faff9774a94c` passed actual Morrow execution: exec returned the requested marker and exit7, browser opened Wikipedia, typed Monster into observed ref e53 with submit, and read the resulting `/wiki/Monster` page. Final text matched the native results. Raw transcript and machine-checked evidence are retained in `stronger-model-positive-qualification.json` and `browser-run-d671bd6c-e215-4c51-9854-faff9774a94c.json`.

Exact Zepto prompts in both low-thinking (`062515c4-f0b4-4274-a376-7f38a86e6aca`) and deterministic non-thinking (`160b84a9-5963-46d6-b53a-1a27d64e152e`) still retried after429. The completed non-thinking run ended with unobserved suggestions including cables, so it failed grounding. The managed browser/429 instructions were confirmed present in the actual system request; this was not a missing-guidance assumption. Its raw trace includes unsupported action wait as well as valid calls and genuine HTTP errors. The 35B model is not promoted; it was unloaded after its run completed. Both default primaries remain9B.

Owner authorization covers testing stronger local models. A second candidate, OpenAI GPT-OSS20B, is downloading via LM Studio's MLX resolver. Its native advertised131072 context is lower than the current9B route's200000; any future promotion must state that change and must not pretend the candidate supports200K. It has not yet passed native Morrow qualification. No cloud or paid fallback has been added.


GPT-OSS20B MLX download/load and all3 published LFS weight hashes were verified at revision `773a7da77e569019bb0fd17a554b263738d669a3`. Its initial catalog discovery was valid; the early direct-preflight assertion incorrectly assumed browser-open must be the first call. Actual Morrow session `8353af5a-7684-41f3-b1ed-e59a8f003460` corrected a batch-limit discovery error, then failed with native `Provider returned an incomplete or malformed tool call` and emitted Harmony control text as a final reply. A non-streaming replay also produced no usable call. This candidate is not promoted and was unloaded. This is not evidence that the browser itself failed.

The next authorized local candidate is dense `qwen/qwen3.6-27b`, using the same supported Qwen engine family while avoiding the35B-A3B candidate's smaller active parameter path. Download is in progress; no behavioral claim or default replacement is made yet.
