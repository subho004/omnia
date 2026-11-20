# Native chat UI evidence (read-only, 30 October 2026)

Static investigation of the installed extracted JavaScript distribution `/tmp/claw-openclaw-dist/control-ui/assets`. This is shipped code, not latest upstream main. No package code was executed, no model was called, and no runtime event coverage is implied. Prettier's already installed executable was used only to format inert JavaScript into `/tmp/morrow-native-chat-analysis/`; the line references below refer to those formatted derivatives. The original paths and bytes identify the evidence.

## Source identity

| Original asset | SHA-256 | bytes | formatted derivative |
|---|---|---:|---|
| control-ui-boot-chat-Bia0O-uD.js | 828262ed20e88b7fa3e6a9c07363f44fd29410aa07509b9543cca1179c01cfcd | 792672 | chat.js |
| control-ui-boot-shared-CXVvK2AW.js | 64bbf20764c8531beb86982164c32933ba6afc47d9267b88128a19183f8c1958 | 461012 | shared.js |
| control-ui-boot-shared-BYq7Cchl.js | 8e83e948038a8dd753078cf3f9c432d393a16648b06e4acfabdb2ff086c2e9a6 | 394644 | shared-base.js |
| control-ui-boot-shared-DfZ39Yj9.js | 5963b26ab2738d5866691f199da1d9f30bcace3b1bb9c9b03fa2d5e0a344696e | 591843 | shared-message.js |
| control-ui-foundation-Cydpkyqa.js | e99c11e32f854e23c7e6c5fd620aeaa9d7dffda98bb4497c49f0fe8dc744c577 | 289401 | foundation.js |
| control-ui-core-YphAl4aM.js | aeeff39af05e2e2fc7cb6daa774be7bc2b5c2c06858492e2169c57c981847bee | 234570 | raw only |

Parent already retained REA evidence `ev_08feff8c6b5868c391b6d49640b3fe64be08cb692c72f4f1a940e5b94fe7fc44` for three server files and artifact identity bdf634f1fe8c90585c62464dd78cec7c3476c50b7952a2e14d350bcb31f6f9d9. It does NOT cover these UI sources. This report is independently read static source evidence, not a claim that those files were included in that REA selection.

## Native incoming events and scoping

`chat.js:27697-27805` function kR dispatches:
- `chat`: delta/final/aborted/error; validates canonical session/agent; binds run; supports deltaText and full message; reload/reconcile history on terminal and missing final payload; doesn't equate an acknowledgement with completion.
- `session.approval`: queue update.
- `session.observer`: validates selected session+agent and active run; ignores stale/redundant digest revisions.
- `agent` and `session.tool`: same activity reducer (import Dp = shared export Ti = Ny).
- `session.operation`: manual operation reducer.
- `session.message`: persisted transcript update.
- `sessions.changed`: list/activity reconciliation.
- `task`: background tasks reducer.

`foundation.js:8921-8959` message subscription uses `sessions.messages.subscribe {key,agentId?,includeApprovals?:true}`. Response `{key,approvalReplay?}` is captured; subscriptions recover carefully after a request-sent timeout. Exact shared owner/session subscriptions, not browser-supplied upstream targets.

`control-ui-core-YphAl4aM.js` byte offset ~30755: native browser connect caps are agent-kind, approvals, task-suggestions, terminal-offset-seq, terminal-session-metadata, tool-events, inline-widgets, ui-commands, usage-refreshing. Native UI does not include session-scoped-events in this literal capability list. Tool events must be advertised to receive them where native server gates them.

## Exact activity streams, fields, state semantics

`shared.js:11675-11765` function Ny is primary activity reducer; it rejects conflicting session/agent and deduplicates sequence before applying. Common envelope runId, sessionKey?, agentId?, seq, ts, stream, data.

| Stream | Data / states | Native behavior | Evidence |
|---|---|---|---|
| tool | toolCallId, name, phase=start, args | Begin pending tool; preserve assistant commentary before boundary | shared.js:11687-11735 |
| tool | phase=update, partialResult | Update output from structured/text result | shared.js:11699-11707 |
| tool | phase=input_delta, diff={added,removed} | Display live edit count, replaced by final result | shared.js:11711-11716 |
| tool | phase=result, result, isError | Mark result received even empty; result.details & integer result.exitCode captured | shared.js:11706-11755 |
| tool | phase=review, review | Merge bounded per-review records; status summary with risk/authorization/rationale | shared.js:11652-11673, chat.js:5100-5165 |
| compaction | phase=start, itemId? | active, preserve start time on matching run/item | shared.js:11168-11209 |
| compaction | phase=end, completed=true, willRetry=true | retrying (completed compaction, another model attempt pending) | shared.js:11210-11217 |
| compaction | phase=end, completed=true | complete | shared.js:11218-11222 |
| compaction | phase=end, completed!=true | remove active compaction (not a successful completion) | shared.js:11220-11222 |
| lifecycle | phase=waiting-approval, approvalId, toolCallId? | waiting approval map keyed approval, run-bound | shared.js:11282-11305 |
| lifecycle | phase=approval-resolved, approvalId | clear exactly that approval, suppress stale pending replay | shared.js:11299-11305 |
| lifecycle | phase=end/error | completes a matching compaction retry indicator; native chat/session terminal still controls run | shared.js:11223-11235 |
| lifecycle or fallback | phase=fallback/fallback_cleared (fallback stream defaults fallback), selectedProvider/Model or fromProvider/Model; activeProvider/Model or toProvider/Model; previousActiveProvider/Model; reasonSummary/reason; attemptSummaries/attempts | Show model switch or recovery badge; native temporary display expires 8sec | shared.js:11241-11280, chat.js:29240-29279 |
| item | kind=preamble, progressText, itemId or id | Public commentary/progress text; suppress NO_REPLY; replace same run/item; do not double render persisted same item | shared.js:11323-11392 |
| usage | outputTokens | Nonnegative finite integer output token count; seq dedup; bounded 50-run memory | shared.js:11574-11594 |
| notice / codex_app_server.guardian | phase=strict_review_required/warning/started/completed, status=inProgress/approved/denied/timedOut/aborted; reviewId,threadId,turnId,startedAtMs,targetItemId?,command,riskLevel,rationale,message | System warning/reviewing/approved/denied; item-targeted reviewing rendered on tool instead of duplicate transcript notice; bounded 50 notices | shared.js:11597-11651 |

Sequence semantics (`shared.js:11542-11574`): tools are keyed by [runId,toolCallId], not tool name. Per-tool result sequence floor prevents delayed updates turning a finished tool back to pending. Reviews have individual IDs and sequence floors. Compaction terminal and preamble have separate keys. Multiple tools of same name must remain distinct. UI caps live tool list at 50, syncs every80ms, flushes immediately on result; output text capped120,000 chars (`shared.js:11767-11782`).

## Other statuses actually rendered

### Startup and general working

`shared.js:11028-11072,13106-13118` startup status phases: preparing_workspace, naming_worktree, creating_worktree, running_setup, provisioning_environment, preparing_context, starting_model. They are recovered from active run snapshot `events` stream=run_status; when actual text/preamble/tool activity begins, startup status cannot regress. General working includes elapsed time and optional output token count. Native completion recap shows actual runtimeMs plus tokens only when native session done is confirmed (`shared.js:2507-2555,10394-10478`). Composer briefly shows interrupted marker (`chat.js:29228-29239`).

### Observer plan and health

`shared-base.js:15394-15417`: payload {sessionKey, agentId?, runId?, revision>=1, updatedAt>=0, headline(1..120), assessment?(1..320), health, planProgress?:{completed>=0,total>=0}}. Health enum: on-track, grinding, stuck, waiting-on-user, wrapping-up, done, failed. The UI scopes to currently active run and ignores old revision (`chat.js:27776-27782`). Don't infer these states from arbitrary model text; only render the supplied native digest. In sidebar narration this supersedes free-form chat/tool narration (`shared-message.js:4181-4256`).

### Background and subagents

`chat.js:12782-12855` native task event actions upserted/deleted/restored. Match task session/owner/child session; restored triggers reload instead of trusting stale list. Native task status enum queued/running/completed/failed/cancelled/timed_out (`chat.js:12327-12337`). Subagent activity line requires runtime=subagent and same canonical parent session; displays lastActivity/progressSummary/lastToolName or terminalSummary when terminal (`chat.js:12340-12419`). Active and recent task rail has elapsed time, status, result/details, linked child conversation (native feature; do not assume generic Morrow task list alone implements linked-session UI).

### Questions

A separate controller, outside kR, handles `question.requested` and `question.resolved` (`shared-message.js:11692-11710`). Pending question payload {id,createdAtMs,expiresAtMs,questions[1..3],agentId?,sessionKey?,runId?}; each question {questionId snake_case,header,question,options<=4,multiSelect?,isOther?,isSecret?,secretStore?,secretStoreExisting?}. Terminal states answered/cancelled/expired. Secret drafts are explicitly erased (`shared-message.js:11413-11416`). Native source supports full question submission, but Morrow's current curated APIs do not; display-only waiting-on-user from observer/lifecycle is distinct from claiming a working question form. Do not expose secret/question answers through a broad event passthrough.

## History/transcript rendering

`chat.js:2635-2700` iterates normalized messages, preserving commentary setting, compaction/reset entries, system notices, tool results, and text. Compaction custom entry kind `__openclaw.kind=compaction` or customType=openclaw.context-compaction maps to a divider; reset kind maps to context reset divider, not a user chat bubble. Live compaction matches persisted by run/item to avoid duplicates.

`chat.js:5552-5725`: normalized role assistant/user/tool, expandable tool calls, text plus media, optional native reasoning. `shared-message.js:3760-3787` reasoning extractor accepts only actual message.content items `{type:'thinking',thinking:string}` and UI uses it only when showReasoning enabled. This is provider-visible content supplied by gateway, not an instruction to fabricate hidden reasoning. Arbitrary model reasoning isn't required to represent agent status; actual pending/work/tool/compaction states cover that.

`shared-message.js:19254-19268` exact tool status: failed if explicit isError or terminal output recognized error; running only if runActive=true && live=true && completed!=true; succeeded if completed=true or non-live has actual output; otherwise unknown. Empty completed tool result is success distinct from no result. Native cards are collapsible groups with tool kinds read/search/fetch/edit/write/command, expandable input/result or diff/raw view (`chat.js:3670-3980,4937-5292,6873-6950`). Native external tool previews/widgets/file links/browser integration are separate execution/view features and should not be silently treated as implemented solely by adding statuses.

## Boundaries / unresolved

This is static source evidence for installed UI assets only. It proves implemented handlers and render shapes, not that each event is emitted under current provider/model/tool configuration. No screenshots/native UI actions or inference calls were taken. Native server event delivery, cap gating, authorization, and exact session subscription semantics must be corroborated by parent investigation and protocol tests. Cloud placement, plugin-specific rich widgets, media/file/terminal control, task suggestions and question mutation are separate product capabilities; status rendering must not silently enable unsupported external operations. Missing/unknown event kinds must remain harmless, not direct raw JSON fallback exposing configuration/secrets/vendor labels. Native UI itself contains backend branding; Morrow must use its own labels/components and neutralize supplied system labels with the project's boundary policy.
