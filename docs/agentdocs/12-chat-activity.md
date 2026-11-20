# Morrow chat activity — 30 October 2026

Implemented from the installed 2026.9.2 shipped JavaScript, using reverse-engineer-anything and REA. Native wire protocol remains 4. The native session subscription and UI asset SHA256 were checked against the running User1 container and match the extracted distribution.

REA parent: ev_08feff8c6b5868c391b6d49640b3fe64be08cb692c72f4f1a940e5b94fe7fc44. Artifact digest bdf634f1fe8c90585c62464dd78cec7c3476c50b7952a2e14d350bcb31f6f9d9. Selected files: gateway-chat-DJ7Ob6nF.js, sessions-subscriptions-WFPjDUb7.js, client-info-B1bPgeKr.js. Module inspection ev_1558e248e9e9f9fafd16d73788f927112a0c0f9f505d1f7f12befa6b392a32bd. This is partial static coverage, not whole-application or runtime proof. Additional targeted source report copied beside this document.

## Delivery and safety

SSE now subscribes to sessions.subscribe as well as selected sessions.messages.subscribe: native visible tools otherwise target the short-lived POST sender connection. Advertise session-scoped-events/tool-events/agent-kind. Backend still requires exact selected session equality; task envelopes use task.sessionKey. Never adopt spawnedBy as ownership.

Activity projects startup, thinking status without reasoning/signatures, tools and safe text results, streamed edit counts, plans, public preambles, notices/guardian reviews, usage, compaction/retry, model fallback, observer health, delegated tasks, lifecycle and input/review waiting. Unknown streams and raw arguments/configuration are dropped. Native question status uses a separate host activity identity with read/questions and optionally approvals; existing chat/reviewer keys are not upgraded. No question resolution RPC is exposed. Native requested IDs/replay bind sessionless resolution events; unknown IDs and all question/answer/secret-store contents are dropped. Interactive question forms remain unavailable and the UI says so.

History includes safe tool cards and known compaction/reset markers; in_flight projects native startedAt and bounded progress events for the exact run/session. Live updates are not gap-free or a permanent audit log. Native transient events can disappear after a completed run and browser reload.

Frontend uses forest/paper Morrow disclosures, elapsed status, output token count, sequence/result protection, independent tool IDs, unknown outcome for unfinished tools, replay reconciliation, and clears private activity on account/session changes. Refresh disables sending until reconciliation completes. Public narrative copies neutralize runtime branding and credential patterns; original inputs/stored instructions remain unchanged. Exact branded approval proposals are blocked with no Allow/token rather than displaying altered commands or recipients. Canonical supported review fingerprints are unchanged.

## Validation

145 tests passed; Ruff and JavaScript syntax checks passed. Tests include event scope, question replay/secret suppression, revocation, proposal integrity and source-derived event catalogue. Real User1 browser run called session_status once and returned MORROW_ACTIVITY_CHECK_7531; observed native startup, lifecycle, tools, item progress, usage, streamed reply and terminal completion. Question status subscription paired and connected successfully without model calls. Rare states are source-contract/controlled-fixture coverage, not claims of live provider emission. Browser fixture is isolated at port8444 with a disposable database, no model or external actions. Browser plugin unavailable; used authorized Chrome Playwright fallback.

## 31 October exec status correction

Native exec can return `isError=false` with `details.exitCode` nonzero. History safely retains only that numeric exit status, and both history/live activity project it as failed with a bounded command-exit summary. Exit-zero warnings remain completed. Other tools do not inherit exec-specific interpretation. Regression tests cover all three cases; this does not infer success of external work from command exit zero.


## Native interactive deadline qualification, 1 November 2026

The completed 35B non-thinking exact Zepto prompt produced95 transcript events over roughly eight minutes, repeatedly retried429, guessed endpoints, and ended with unobserved product suggestions. This is a failed agent qualification despite a working browser and supported calls on the positive Wikipedia test.

A proposed server-owned `chat.send.timeoutMs` limit was tested against the installed protocol4 schema and real native gateway. The schema accepted1000ms, but the actual native run executed sleep10 and continued tool polling before returning a final answer. It did not enforce the requested deadline. The public API/config change was therefore removed, rather than presenting an unqualified limit as protection. Native deadline enforcement remains unresolved; no durable execution-budget claim is made. The small diagnostic turns were stopped/settled and did not change schedules or user data.


## Availability is not session revocation (1 November)

The live availability fault revealed that Guard.watch collapsed all failures into a generic event and Guard.run always returned401. A503 native outage therefore cleared Morrow's private page as if the login had ended. Guard now retains transient failure/reconnect reasons, while cookie revocation, expiry and ownership loss still terminate with401. Before a stored transient failure is emitted, cookie liveness is checked again so concurrent revocation takes precedence. An upstream change still closes the old stream; reconnection creates a fresh owner-authorized connection rather than retargeting it.

A real User1 control-plane availability interruption now recovered through actual worker/native checks while the browser retained its draft and sent zero message POSTs. Native identity, mount, volume and upstream were unchanged. Identity polling also had a catch-all endSession path; it now routes network/5xx errors through recovery, preserving authoritative401/account-change cleanup. An injected auth/me network failure recovered to a usable Send button with draft retained and zero message POSTs. Screenshots were visually inspected in `/tmp/claw-orchestrator-qa/identity-recovery-20261101.png`; this is recovery evidence, not merchant inventory proof. Full suite:192passed,4skipped.
