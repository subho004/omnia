# Frontend

The UI is server-rendered Jinja2 plus plain ES modules and CSS. There is no build step, so `uv run --locked scripts/serve.py` serves everything.

## Files

| Path | Role |
| --- | --- |
| `templates/index.html` | Login page (user picker, CSRF) and, when signed in, the instance control panel |
| `templates/workspace.html` | The `/workspace` shell. It renders even when the runtime is unavailable. |
| `templates/launch.html` | Auto-submitting form that carries the launch ticket to the instance origin |
| `static/app.js` | Login-page glue. Submits the native-UI handoff form for compatibility. |
| `static/workspace.js` | Workspace controller: sessions, chat, streaming, review dialogs, session fence |
| `static/workspace-api.js` | Fetch wrapper (CSRF, `X-Workspace-Session`, error code to message mapping) |
| `static/workspace-views.js` | DOM helpers and view builders |
| `static/workspace-activity.js` | Activity timeline rendering (bounded list) |
| `static/workspace-automations.js` | Automations page |
| `static/workspace-markdown.js` | Small Markdown subset rendered with DOM nodes, never model-supplied HTML |
| `static/workspace-text.js` | Display-only text cleanup. Original text, stored instructions and review proposals stay intact. |
| `static/style.css`, `static/workspace.css` | Styles |

Static files are served by `GET /assets/{name}` with a content type per extension.

## Session boundary

- Every page and API or stream request carries the non-secret `X-Workspace-Session` marker for the current login. If another tab switched users, the server answers `409 SESSION_CHANGED`. The client then clears messages, drafts, review tokens and automation state, and locks the old page.
- No JWT or private content is stored in `localStorage` or `sessionStorage`. Authentication is only the `HttpOnly` cookies.
- Mutating requests use CSRF. Streams use cookie-authenticated `fetch` with the same fence.
- Features that are not implemented are visibly disabled, based on `/api/assistant/capabilities`.
- Ordinary stream expiry (`RECONNECT_REQUIRED`) reloads history and resubscribes without resending the message.

## Presentation layer

Native runtime text passes through `presentation.public_text` and `chat_activity.py` before reaching the browser. They scrub internal product and runtime names (`OpenClaw`, `NemoClaw`, `OpenShell`) and credential-shaped strings (matched before truncation, so a cut cannot expose a prefix). Activity kinds are mapped to customer wording, for example "Preparing workspace". This is a presentation projection only. Canonical review data is never rewritten.

## TypeScript client

`clients/assistant.ts` is for a separate frontend served from the same origin. It fetches CSRF tokens and uses same-origin cookies. `assistant` covers login, sessions, history, messages and streaming. `product` covers capabilities, tasks and reviews. It exposes typed `Session`, `Message`, `ChatEvent`, `Task`, `Approval` and `APIError`. `clients/openclaw.ts` keeps legacy exports for developer use.

## UI fixture for browser QA

```sh
uv run --locked python tests/serve_ui_fixture.py
```

Serves `https://app.localhost:8444` against a unique disposable PostgreSQL database and a simulated gateway, with a visible "simulated results" notice. It never creates tenant containers, touches working tenant data, calls a model or performs an external action. Ctrl+C drops only its own database. Cookies are shared across ports on the same hostname, so use a separate browser profile if you also need a normal login open.
