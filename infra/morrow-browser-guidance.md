## Managed browser: required execution rules

Before choosing any tool, follow these rules for live website tasks:

- When the user supplies a URL or hostname, copy that hostname exactly into the
  first navigation. Add `https://` if needed. Do not substitute a remembered brand
  domain, add `www`, invent a search URL, or guess another domain.
- Use the managed `browser` tool. Shell launchers, echo statements, curl requests,
  guessed APIs and search snippets do not perform a website search in its UI.
- An observed HTTP 429 ends this attempt. Stop making tool calls for that task.
  Report the observed URL and status and which requested facts remain unverified.
  Do not reload, wait and retry, change domains, guess APIs, or switch tools.
- A 429 alone does not establish its cause, duration, account/IP/session scope, or
  whether another browser will work. Do not state or speculate about those facts.
- Product names, sizes, prices and availability require observations from the
  actual results page. Never fill a failed search with likely or remembered items.

The private managed browser is available inside this workspace. No host browser,
extension, or shared profile is required. Call `browser` directly when exposed.
If it is available only through the native catalog, use
`tool_search` with `{"query":"browser","limit":1}`, then `tool_describe` if
its schema is needed, and `tool_call` with the exact returned id and an `args`
object. The executed output is under `result`; inspect that output. Do not print
tool-call markup as a reply.

1. Open the supplied URL with `{"action":"open","targetUrl":"https://user-supplied-host.example"}`.
   Keep the returned targetId/tabId for subsequent actions.
2. Read a snapshot using `{"action":"snapshot","targetId":"returned-id","refs":"aria"}`.
   A created tab or an empty snapshot does not prove the page has loaded.
3. Interact only with observed current controls/refs. A supported input action is
   `{"action":"act","targetId":"returned-id","kind":"type","ref":"observed-ref","text":"requested search","submit":true}`.
   Use `kind` for the action; the separate `type` field is an image format.
4. Read a fresh snapshot after navigation or input. Distinguish real page text,
   HTTP errors, proxy/DNS failures, and extraction failures. Tool metadata and a
   successful transport call alone do not prove that the requested task succeeded.

If a delivery location or sign-in is required, ask for the needed user action
without requesting passwords or one-time codes in chat. A product search does
not authorize checkout, purchases, messages or unrelated third-party submissions.
