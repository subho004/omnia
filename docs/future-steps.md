# Future steps

How Omnia can grow from a two-user prototype into an open, self-hostable personal agent that competes with Instinct, Muse, Grok's companions and similar products, and later into an agent that can do almost any task a person can do on a computer.

Research date: 2026-11-20. Findings come from three parallel research passes (competitors and forums, skills and memory, scaling and safety), checked against this repository's code. Evidence labels:

- **[V]** vendor or practitioner claim, not independently verified;
- **[S]** speculation or inference by the authors;
- unlabeled statements are about this repository and can be checked in the code.

Most sources were blogs and aggregators, and Reddit was not reachable. Re-check prices, benchmark numbers and dates before relying on them. Section 9 lists what remains unknown.

## 1. Where Omnia stands today

Verified from the code (see [Architecture](architecture.md) and the capabilities map in [API reference](api-reference.md)).

| Area | Today | Gap to a real product |
| --- | --- | --- |
| Isolation | One sandbox, volume and browser origin per user. Public-only egress proxy. Loopback-only server. | Strong base. Single host, one Docker daemon, one uvicorn worker. |
| Users | Two hard-coded demo identities, demo login. | No real accounts, no sign-up, no organizations. |
| Chat | Sessions, history, streaming, abort. | Web only. No messaging channel, no voice. |
| Proactivity | Cron-style schedules with run history. Results stay in the workspace (`delivery.mode=none`). | Nothing pushes to the user. No event triggers. |
| Browser | Managed browser, public-URL checks, first-navigation guard. | Takeover, login and credential handling are not implemented. Live checks hit rate limits (HTTP 429) on a merchant site. |
| Integrations | None. `tenant_connections`, `calendar`, `email` are `not_implemented`. | The biggest product gap. Competitors lead with these. |
| Memory | Not implemented (`memory`). | Users cannot see or fix what the agent knows. |
| Skills | Fixed tool set. Scheduled jobs run with `toolsAllow: []`. | No installable, versioned, reviewable skills. |
| Multi-agent | Not implemented. | Not needed yet (section 5). |
| Reviews | `reviews` is `disabled`. Approval plumbing exists. | Approvals are the core trust feature and should come first. |
| Models | LM Studio or OpenRouter free models. Pinned sampling. | No metering, budgets, routing or caching strategy. |
| Observability | Safe error codes, no tracing. | No traces, replay or evaluation suite. |

## 2. Market impact: what the research says

### Who the competitors are

| Product | What it is | Notable points |
| --- | --- | --- |
| Instinct | Personal agent reached by text or call, no app. Spear Street Technology. Site is instinct.com. `instinct.ai` is a parked domain for sale, so beware of invite scams there. | Invite-only. No published price. Broad data license, training on by default, and disconnecting an account does not delete the index [V]. |
| Muse (Meta) | Personal agent launched 2026-09-08 for US users on web, iOS, Android and WhatsApp. | Free, $20 and $100 tiers [V]. Runs in a "Secure VM" with a separate "Sentinel" agent. Main criticism is trust, given Meta's privacy history. |
| Grok companions | Persona characters (Ani and others) in SuperGrok, about $30 a month [V]. | Complaints include weak memory across sessions. Whether the 3D companions were retired is unconfirmed. A separate "Grok bot" agent product could not be confirmed. |
| Poke, Manus, Lindy | Text assistant, general task agent, workflow agent. | Credits burn fast, per-seat pricing, update complaints [V]. |
| ChatGPT agent, Claude | Agent modes inside paid chat plans. | Around $20 a month. No specific complaint data found. |
| Perplexity Comet | Agentic browser. | Repeated prompt-injection findings by several security teams, including action inside an authenticated session. |

`MuseAI` (a companion app) and a Chrome extension share the name "Muse". The earlier [feature research](FEATURE_RESEARCH.md) treats Muse as Meta's agent, and so does this document.

### What users say they want and what disappoints them

From Hacker News threads, reviews and security write-ups [V]:

1. **Reliable memory.** "Memory is unreliable and you don't know when it will break" is the most repeated complaint. Companion users report the same ("it forgot me").
2. **Trust over long periods.** Users ask whether the agent does exactly what it should for weeks without supervision.
3. **Privacy and security.** Raw OpenClaw is called a "security nightmare". Training on user data by default and non-deletion on disconnect drew objections.
4. **Simplicity beats autonomy.** Some users found a scheduled routine calling a personal tool server more reliable than a full agent.
5. **Predictable cost.** Credits that burn, $200 tiers and per-seat pricing.
6. **Proactivity.** The headline feature of Instinct and Muse.
7. **Action safety.** Booking and buying need approvals and spending limits.

### Where an open, self-hosted agent can win

| Opening | Why Omnia is suited |
| --- | --- |
| Verifiable privacy | Data stays in the user's own volume. Local inference means no vendor sees it. No training. Competitors ask users to trust them. |
| Hardened by default | Loopback binding, per-user sandbox and egress filtering already exist. |
| Editable, exportable memory | Answers the top complaint and also limits memory poisoning. |
| Approvals as the headline | Instinct's terms disclaim unintended actions. Omnia can make a reviewed action log its selling point. |
| Predictable cost | Bring your own key or a local model. No credits and no seats. |
| No lock-in | No waitlist, and no vendor can retire a persona or feature. |

### Honest risks

- **Onboarding friction.** "Just text it" products need no setup. Omnia needs Docker, certificates and a runtime. A messaging channel and a one-command installer matter more than any single feature.
- **Self-hosting moves patching and secrets to the user.** A local install that calls a cloud model still sends data to that provider.
- **The security bar is high.** Agents that read untrusted content and act are an active attack surface (section 6).
- **Large vendors will bundle agents.** Omnia should not try to win on model quality. Its edge is trust, control and openness.

## 3. Principles for everything below

1. **Deterministic gates outside the model.** Spend limits, allowlists and approvals run in code the model cannot edit [S].
2. **Trust before capability.** Ship the approval and audit path before powerful connectors.
3. **Narrow beats clever.** Prefer a typed adapter over raw model access, as the automations API already does.
4. **User-visible state.** Memory, skills and schedules are files or rows the user can read, edit and delete.
5. **Measure before building.** Each step below has an exit test. Add evals before multi-agent or router work.

## 4. Roadmap

Rough order [S]. Phases overlap. Effort is relative, not a calendar promise.

### Phase 0: Make it a product someone else can run (small)

- Real sign-in through an OIDC provider (Keycloak or Authentik) plus passkeys (WebAuthn), replacing demo login. Add `org_id` to the schema early [S].
- Remove the two-user hard-coding (`users` check constraint, `USERS` dict, gateway ports tied to user number).
- One-command install (`make up` or a script) and a Docker image for the control plane. Add a `LICENSE` and a CI workflow. A license choice needs research (AGPL, Apache, open-core, CLA). That research found no sources, so decide deliberately.
- Add the tracing, token metering and per-user budgets described in Phase 6 early, because later work depends on them.
- Exit test: a stranger installs it on a fresh machine and signs in with their own account.

### Phase 1: Trust layer (medium)

- Turn on `reviews`. Show the exact proposed action, bind approval to a hash of that summary, and record the outcome as an action receipt.
- Append-only audit log in PostgreSQL for every tool call, approval and external effect.
- Per-user spend caps and domain allowlists, enforced in code outside the model.
- Browser takeover: the user steers the same browser profile through a live view while the agent is paused at login, CAPTCHA, 2FA and payment steps. Keep sessions in the user's volume. Passwords never enter model context [S].
- Exit test: an injected instruction on a web page cannot cause a purchase or send without a visible approval.

### Phase 2: Connections (medium)

- A connection broker outside the sandbox holds OAuth tokens (encrypted at rest) and injects them per call. The agent never sees the raw token [V, matches the MCP authorization guidance of OAuth 2.1 with audience-bound tokens].
- Start with Google Calendar (read, then reviewed write), then email (read and draft, reviewed send). Scope each provider read and write permissions separately. The [calendar workflow](FEATURE_RESEARCH.md) already specifies the safe behavior.
- Expose connections as typed tools (an MCP-style interface) rather than as browser scripts.
- Exit test: create one calendar event, restart, confirm exactly one event exists, revoke the connection, confirm access stops.

### Phase 3: Memory (medium)

- Start simple and inspectable: Markdown or SQL entries split into facts, episode summaries and procedures, each with provenance and a timestamp [S, based on current research favoring typed memory].
- A memory page where users view, edit and truly delete entries. Add expiry or decay.
- Treat memory written from untrusted content (emails, web pages) as untrusted. A reader agent with no memory write access handles it [V, MemGhost research showed one crafted email can plant persistent false memories].
- Do not add a graph database or a memory framework until an eval shows it helps. Published benchmark claims for Mem0, Zep and Letta conflict with one another [V].
- Exit test: a fact the user corrected is never repeated wrongly, and a deleted fact is gone from storage and from the next prompt.

### Phase 4: Proactivity and channels (medium)

- A heartbeat: a periodic agent turn that reads a user-editable checklist and messages the user only when something needs attention. OpenClaw already has this mechanism [V]. Keep the existing cron schedules for exact times.
- Delivery to the user: Telegram first (simplest API), then WhatsApp and voice [S]. Each channel needs a per-sender allowlist, because an inbound message is a prompt-injection path. External sends stay behind approval.
- Event triggers (new email, calendar change), after reviews and connections exist.
- Exit test: the morning brief arrives in Telegram without the web app open.

### Phase 5: Skills (large)

- Adopt the open Agent Skills format (SKILL.md folders), which OpenClaw and several other tools already use [V].
- Ship a small curated first-party set first: calendar planning, grocery and shopping flows, research, form filling.
- User-installed skills are untrusted code. Required controls [S, informed by the ClawHub incident]:
  - pin by hash and version, and show a permission summary and diff before install;
  - run inside the user's sandbox, never with orchestrator or provider credentials;
  - block shell install steps unless approved. Most malicious skills hid commands in a "Prerequisites" section;
  - static scanning is not enough. Scanners missed some malicious skills, so keep human review for any shared registry.
- Why this matters: a campaign on ClawHub (the OpenClaw skill registry) was reported with 341 of 2,857 audited skills malicious, and later counts reached over 1,000 [V]. The counts differ by source, but the direction is consistent.
- Exit test: installing a deliberately malicious test skill is blocked or contained, with no access to credentials.

### Phase 6: Scale (large)

- **Hibernate idle users.** Stop the container, keep the volume, resume on demand. "One container per user, always on" is the main idle-cost driver [S]. Hosted sandboxes advertise resume times from about 0.1 to 2 seconds [V], but those figures vary widely by source.
- **Scheduler interface above the runtime adapter** (`runtime/base.py` already defines `provision` and `probe`). Keep Docker for single-host use. Add a second backend when user count justifies it.
- **Multi-host backends:** Kubernetes with the SIG Apps agent-sandbox project (warm pools, gVisor or Kata isolation through RuntimeClass) is the leading open option [V]. It is new, so evaluate before committing. Memory snapshots upstream currently depend on GKE-specific features [V].
- **Control plane:** move from one uvicorn worker with in-process locks to a durable job queue and stateless workers. Provisioning jobs already use leases in PostgreSQL, which helps.
- **Inference economics:** meter tokens per user, set budgets, support bring-your-own-key. Use a stable prompt prefix for caching. Measure the escalation rate before building a small-to-large model router, because per-turn escalation in long chats can cost more than it saves [V].
- **Observability:** emit OpenTelemetry GenAI spans per run and tool call (the convention is still in development [V]). Store approvals and effects in PostgreSQL. Build a replay-based regression suite that includes prompt-injection cases (AgentDojo-style).
- Exit test: 100 simulated users, 10 active at once, with measured cost and cold-start time.

### Phase 7: Delegation and learning (large)

- **Read-only research sub-agents.** Parallel workers with isolated context that return summaries. Anthropic's reported research system beat a single agent by 90% on its internal eval but used about 15 times the tokens [V], and it suits breadth-first research, not tightly coupled work. Keep a single agent that performs actions, because conflicting writes from parallel agents are a known failure.
- **Specialists** (shopping, travel, finance) only where evals show a gain over one agent with skills.
- **Learned skills.** After a successful run, propose a draft skill. The user approves before promotion. Replay it against saved tasks to verify, version it and allow rollback. Prune stale skills. Research reports "library drift" risks in self-evolving skill libraries [V, title only], so keep humans in the loop.
- Exit test: a repeated errand gets cheaper and faster after the user accepts its learned skill, with no loss in success rate.

## 5. Becoming an agent that can do almost anything

"Anything" is a direction, not a feature. Three ingredients get there, in this order:

1. **Breadth of tools:** connections (Phase 2), skills (Phase 5), and a browser that falls back to any website when no API exists. The agent should prefer an API, then a browser, then ask the user.
2. **Depth of reliability:** takeover for the steps machines cannot do (login, CAPTCHA, OTP), checkpointed tasks that survive restarts, and evals on the user's own recorded tasks. Public benchmark numbers (OSWorld, WebArena, BrowseComp) are reported at high levels [V, aggregator figures], but they avoid real credentials and payments. They say little about logged-in sites, so Omnia needs its own replay evals.
3. **Earned autonomy:** each skill or action class starts under review and graduates to automatic after a track record, with limits the user can see and change. This is how an agent can safely do more without the user watching.

Longer-term directions [S]:

- **Computer use beyond the browser:** a desktop sandbox for files, documents and apps, behind the same approvals.
- **Voice and a phone number:** calls to book or confirm things, once identity and consent are solved.
- **Agent-to-agent protocols:** let Omnia talk to businesses' agents. Payments protocols such as AP2 (moved to the FIDO Alliance in 2026 [V]) are new, with no confirmed production use found and open attacks reported, including replay and injection. A virtual card per agent does not by itself restrict merchants, so spend rules still belong in your own code.
- **A skill ecosystem** with publisher verification and signing from day one, so Omnia avoids the ClawHub outcome.
- **Household and team agents:** shared memory and approvals between people, which needs the organization model from Phase 0.

## 6. Security: the central risk

Anything that reads untrusted content and can act is exposed to prompt injection. Real incidents already exist: Perplexity Comet acting inside an authenticated session, memory poisoning through a single crafted email (MemGhost), and the malicious skill campaign [V].

Design rules for every phase [S, informed by CaMeL and the published prompt-injection design patterns]:

- After the agent ingests untrusted input, restrict which consequential actions it can still take in that run.
- Use a reader with no tools for untrusted text, and a separate actor that never sees raw untrusted text where practical.
- Require approval for sends, purchases and irreversible actions, with an immutable summary.
- Keep credentials outside the sandbox.
- Keep an append-only audit log, and test injection cases in CI.

Omnia's existing boundary (loopback only, per-user volumes, public-only egress, no host mounts, no tenant selection by the client) is a strong foundation. It protects the host and other tenants. It does not stop an injected agent from misusing its own user's accounts, which is why Phases 1 and 2 come before any capability expansion.

## 7. Technical debt to clear along the way

From reading the code, none of it blocking:

- `automations.py` holds unused PostgreSQL-backed helpers (`global_automations_view` and others) with psycopg-style parameters, an f-string SQL query and a reference to a nonexistent `cron` table. Delete them or rewrite them before use.
- Migrations 005 to 007 create tables no live route uses (`automations`, `automation_members`, `browser_connections`), and `browser_connections.py` is not imported anywhere.
- Gateway ports and sandbox naming assume two users.
- Runtime patches are pinned by hash to upstream bundles, so each upstream upgrade needs re-qualification. Prefer upstreaming the patches, or a plugin interface, over carrying them.

## 8. Suggested success metrics [S]

| Metric | Why |
| --- | --- |
| Time from clone to first working chat | Onboarding friction is the main disadvantage |
| Share of agent actions approved without edits | Shows whether approvals are useful or noisy |
| Task success rate on a recorded replay suite | The honest measure of reliability |
| Injection suite pass rate | Trust, tracked on every change |
| Median cost per active user per month | Keeps self-hosting and bring-your-own-key viable |
| Weekly memory edits and deletions by users | Shows users can see and correct what the agent knows |

## 9. What this research could not establish

- The "Grok bot" agent product, and whether the Grok 3D companions were retired. Sources conflict.
- Any licensing or plugin-ecosystem guidance for open-source sustainability. Research the options before choosing a license.
- Production cost per active user for local versus hosted inference.
- Passkey and multi-tenant organization guidance, which is covered only by general OIDC practice here.
- Replika, Character.ai, Pi and Sesame were not checked.
- Reddit threads were not retrievable. Forum evidence is mostly Hacker News.
- Funding figures for competitors conflict across sources and were left out.
- Benchmark and latency numbers come from vendor or aggregator pages. Re-measure on your own hardware.

## Sources

Competitors and users: [Instinct review](https://www.eesel.ai/blog/instinct-ai-review), [Built In on Instinct](https://builtin.com/articles/instinct-ai), [TechCrunch on Meta Muse](https://techcrunch.com/2026/09/08/meta-debuts-its-muse-ai-agent-will-consumers-trust-it/), [Meta announcement](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/), [Grok companions](https://www.layer3labs.io/guides/grok-companions-explained), [personal agent sentiment ranking](https://www.enterpret.com/guides/the-12-best-personal-ai-agents-in-2026-ranked-by-real-user-sentiment), [Brave on Comet](https://brave.com/blog/comet-prompt-injection/), [Trail of Bits on Comet](https://blog.trailofbits.com/2026/02/20/using-threat-modeling-and-prompt-injection-to-audit-comet/), [Northeastern on OpenClaw](https://news.northeastern.edu/2026/02/10/open-claw-ai-assistant/), [MemGhost](https://thehackernews.com/2026/07/new-memghost-attack-plants-persistent.html), Hacker News threads [47721955](https://news.ycombinator.com/item?id=47721955), [47479962](https://news.ycombinator.com/item?id=47479962), [47194611](https://news.ycombinator.com/item?id=47194611).

Skills, memory, agents: [OWASP Agentic Skills Top 10](https://owasp.github.io/www-project-agentic-skills-top-10/), [Snyk ToxicSkills](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/), [ClawHub attack surface](https://newclawtimes.com/articles/openclaw-agent-skills-attack-surface-infostealers-credential-exposure/), [memory systems compared](https://theaiengineer.substack.com/p/cognee-vs-zep-vs-mem0-vs-letta), [Mem0 state of memory](https://mem0.ai/blog/state-of-ai-agent-memory-2026), [when to build multi-agent systems](https://www.langchain.com/blog/how-and-when-to-build-multi-agent-systems), [browser agent leaderboards](https://steel.dev/blog/browser-agent-leaderboards-rebuilt), [browser agent survey](https://arxiv.org/pdf/2511.19477), [OpenClaw heartbeat](https://fossies.org/linux/openclaw/docs/gateway/heartbeat.md), [self-improving agents survey](https://arxiv.org/html/2607.13104v1).

Scaling and safety: [agent-sandbox releases](https://github.com/kubernetes-sigs/agent-sandbox/releases), [sandbox comparison](https://fly.io/learn/sprites-vs-e2b-vs-modal-vs-daytona/), [sandbox pricing](https://www.beri.net/article/e2b-vs-modal-vs-daytona-agent-sandbox-pricing-isolation-2026), [MCP authentication](https://securityboulevard.com/2026/05/mcp-authentication-explained-oauth-2-0-tokens-and-security-for-ai-tool-connections/), [agent credential management](https://www.descope.com/blog/post/ai-agent-credential-management), [CaMeL](https://arxiv.org/pdf/2503.18813v1), [prompt-injection design patterns](https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/), [AP2 analysis](https://arxiv.org/html/2608.23858v1), [ClawHub incident](https://airisk.mit.edu/ai-incidents/1368-malicious-openclaw-skills-reportedly-delivered-amos), [LLM cost optimization](https://www.monterail.com/blog/llm-cost-optimization), [agent replay research](https://arxiv.org/pdf/2608.13867).
