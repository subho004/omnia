# Prototype frontend implementation brief

29 October 2026. The owner explicitly requested the prototype frontend behind Visit OpenClaw, with authenticated feature requests. This supersedes the previous note that no frontend design was requested.

## Design spec before implementation

Selected built-in Image Gen concept: `/Users/subhajithait/.codex/generated_images/01a17b10-6c7f-7191-bb88-984f12ebbb91/exec-150a8c52-a46d-47cb-bfc7-b70564ed8169.png`, native 1505×1045. Brand corrected to Morrow at the owner’s request. Full primary offline screen, not a production image asset. No generated raster is embedded in the app; all text and controls are native HTML/CSS.

- Forest sidebar #1c2d25, off-white main #f7f8f5, ink #20362b, lime #b9efb6, borders #dce3da. Preserve the off-white, no gradient hero.
- At reference dimensions: sidebar 274px, contextual right rail 309px, fluid center. Main header 87px, notice about 90px. Chat composer 30px from horizontal edges and bottom. Collapse right rail below 1180px; mobile uses a compact header and accessible sidebar drawer.
- Serif Georgia heading 58px at the desktop reference size; humanist Avenir Next sans body and chrome, base 16px, labels 13px, strong native focus styles.
- Brand M / Morrow. Essential nav Chat, Tasks, Reviews, Connections. Sidebar Conversations list and account footer with Back to login. Selected nav uses a soft sage fill; consistent 20–24px outline icons, stroke ~1.7.
- Primary visible copy: Workspace / Chat; Refresh; Your workspace is offline.; Reconnect your workspace to send messages.; Retry; What can I help with?; Talk to your assistant, follow tasks, and review actions in one place.; Plan my day; Find movie tickets; Make a grocery list; Ask your assistant…; Messages are available when your workspace is online.; Send.
- Right rail: Workspace; Offline; Recent activity; Activity will appear when your workspace reconnects.; Connections; Calendar / Not available; Browser / In validation; Shopping / Not available.
- State extensions required for functional flows: session list, new-conversation button when ready, chat messages/streaming/cancellation/retry, task filters and detail/cancel, review pending/history/exact-proposal/allow-once/deny, feature readiness details, unavailable/loading/error/session-ended views. Extend the same tokens and row/panel system, not a new visual direction. No fake production chats, tasks, receipts or connected accounts.

## Architecture and safety

Use the existing FastAPI/server-rendered HTML and plain JavaScript ES modules, as required by this repo. No frontend framework or build dependency. `/workspace` authenticates the control session and renders the shell even if the native workload is down. Visit navigates there; first-use creation occurs via a CSRF-protected POST from the shell. Existing unavailable instances are never recreated.

All API and stream requests carry same-origin cookies plus a non-secret per-page session marker derived from the live session. The server rejects marker mismatch before dispatch. The marker is not a credential or session JWT. Session IDs, JWTs and provider keys remain inaccessible to browser JavaScript.

Use fetch streaming for SSE so the page marker is in a header, not a URL. Abort and discard old work on navigation/session change. BroadcastChannel is a UI invalidation hint; server session/ownership checks remain authority. Clear private DOM, drafts, in-memory review tokens and stream buffers on logout/switch/expiry and BFCache exit. No localStorage/sessionStorage, offline cache, or service worker for private data.

Required QA: real HTTPS login → Visit → frontend; navigation and offline states; controlled API/WS browser fixture for authenticated chat/tasks/reviews (explicit test data only); same-browser switch and stale-tab requests; desktop/reference size and 390px mobile. No model or merchant operation.

The customer frontend is **Morrow**. All visible names, titles and feature request paths are product-neutral; the frontend uses `/api/assistant/*`. The legacy `/api/openclaw/*` aliases remain for developer compatibility and are absent from the customer UI. The expected-session header is `X-Workspace-Session`.

## Final fidelity and interaction ledger

Compared the Morrow concept above and the rendered real-service desktop using `view_image`, at the reference's native 1505×1045. Captured final evidence outside the repository: `/tmp/morrow-qa/morrow-desktop.png` and `/tmp/morrow-qa/morrow-mobile.png`. In-app browser validation also covered the normal browser viewport and 390×844 mobile; temporary sizing was reset afterward.

| Comparison | Render evidence and disposition |
| --- | --- |
| Layout and container model | Preserved 274px forest sidebar, fluid center, 309px right rail, 87px header, amber notice and bottom composer. No extra card grid or metrics. |
| Palette and imagery | Forest/off-white/ink/sage/amber match the concept. Flat code-native surfaces, no raster screenshot UI or invented hero artwork. |
| Typography | Georgia 58px primary heading, Avenir Next chrome and explicit control typography. Corrected heading scale and control size during comparison. |
| Copy and hierarchy | Above-fold offline copy, navigation, prompt suggestions and rail labels match the Morrow reference. No backend product name visible. Account initials U1 replace the generic avatar intentionally to make identity clear. |
| Spacing and icons | Corrected rail top position, 48px navigation rows and welcome balance; consistent outline SVG metaphors for chat, tasks, reviews, connections, calendar, search, list and refresh. |
| Responsive behavior | Rail collapses and mobile navigation becomes a drawer with focus management. At 390px, document width equals viewport width, prompts wrap cleanly and composer remains visible. |
| Functional extensions | Online conversation list/new action, messages, task detail and review panels extend the same visual system. These required workflow states intentionally add controls absent from the offline reference. |

The implementation was faithfully verified against the selected concept; no material visual mismatch remained in the checked viewports. The generated reference has minor synthetic texture; the implementation uses clean flat surfaces as specified. No fake activity or connected-account claims were added.

Core path verified: real login → Visit Morrow → authenticated workspace; Chat/Tasks/Connections navigation and accurate offline gates. Controlled fixture path: history → send → streamed terminal reply; task inspect → confirm cancellation; review inspect exact proposal → allow once → history; switch to User2 → prior page locked and private content cleared → User2's own conversation. All fixture work was explicitly simulated, used a separate disposable database and no provider/model action. Final real-service browser console had no warnings/errors. Automated suite 37 passed; Ruff, JS syntax and strict TypeScript checks passed. The native restart recovery gate in 08 remains unresolved.


## Live recovery QA — 30 October 2026

Supersedes the historical offline runtime limitation above. The actual native service now negotiates gateway protocol 4, passes the real control frontend Origin, and uses separate per-owner chat/reviewer signing keys. Chat/session, task and review APIs now connect to restored native instances. Native token/trusted-proxy startup conflict is repaired by the hash-pinned compatibility patch in the runtime adapter.

Verified in installed Chrome, 1280×720, through Playwright CLI after in-app browser control failed with `browser.user is unavailable`: actual demo login → Visit Morrow → Online, new session → real streamed Nemotron exact marker for User1 and User2, retained history, Tasks, empty pending Reviews. Same-browser user switch clears and locks a stale page including its unsent draft; User2 does not see User1 messages. Separate authenticated HTTP verification with User1's real session key under User2 returned no User1 content. No mock/model replay was used for these successes.

Evidence outside the repo: `/tmp/claw-orchestrator-qa/user1-online.png`, `user2-online.png`, `stale-tab-locked.png`. Automated suite: 49 passing; Ruff passing. Current native tests do not establish calendar/shopping/browser execution, a daemon/host restart, or a version-changing upgrade. Live task cancellation and approval resolution were not fabricated merely to fill the empty review screen; controlled tests still cover those operations.


## Current Automations replacement — 30 October 2026

The Tasks navigation/page has been replaced with Automations, following the owner's screenshot: dark schedule table, enabled states, next/last runs, search, All/Active/Paused/Run history tabs, schedule editor and confirmed run/delete actions. Native task APIs remain. See 11-automations.md for the API/security contract and final real-browser evidence. Desktop 1280×720 and mobile 390×844 pass; unsaved editor data clears on account switching. Exactly one tiny synthetic scheduled run was used; temporary schedules were removed and original managed jobs retained. Final suite: 63 passing; Ruff/JS syntax passing.
