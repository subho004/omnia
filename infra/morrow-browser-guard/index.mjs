// The network/tenant security boundary remains OpenShell and the public proxy.
// This hook validates the first browser destination against one explicit host
// in the current request. It never rewrites a URL, response, or final answer.
const FILE_SUFFIXES = new Set(['md', 'txt', 'json', 'yaml', 'yml', 'py', 'js', 'mjs', 'ts', 'tsx', 'pdf', 'png', 'jpg', 'jpeg', 'html']);

export function suppliedHost(prompt) {
  if (typeof prompt !== 'string') return null;
  const hosts = new Set();
  const tokens = prompt.match(/https?:\/\/[^\s<>"'`]+|(?<![\p{L}\p{N}@/.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::\d+)?(?:\/[^\s<>"'`]*)?/giu) ?? [];
  for (const token of tokens) {
    const full = /^https?:\/\//i.test(token);
    try {
      const url = new URL((full ? token : `https://${token}`).replace(/[),.;!?]+$/, ''));
      const host = url.hostname.toLowerCase().replace(/\.$/, '');
      if (!full && FILE_SUFFIXES.has(host.split('.').at(-1))) continue;
      if (url.username || url.password) continue;
      hosts.add(host);
    } catch { /* Ambiguous text does not create a navigation constraint. */ }
  }
  return hosts.size === 1 ? [...hosts][0] : null;
}

export function createGuard() {
  const runs = new Map();
  const key = (ctx) => typeof ctx?.runId === 'string' && ctx.runId ? ctx.runId : null;
  return {
    beforePrompt(event, ctx) {
      const id = key(ctx) ?? key(event);
      if (!id || runs.has(id)) return;
      const host = suppliedHost(event.prompt);
      if (!host) return;
      if (runs.size >= 512) runs.delete(runs.keys().next().value);
      runs.set(id, {host, admitted: false});
    },
    beforeTool(event, ctx) {
      const state = runs.get(key(ctx) ?? key(event));
      if (!state || state.admitted || event.toolName !== 'browser') return;
      const params = event.params ?? {};
      if (!['open', 'navigate'].includes(params.action)) return;
      const raw = params.targetUrl ?? params.url;
      let host;
      try { host = new URL(raw).hostname.toLowerCase().replace(/\.$/, ''); }
      catch { return {block: true, blockReason: 'Browser navigation requires a valid absolute URL for the user-supplied hostname.'}; }
      if (host !== state.host) return {
        block: true,
        blockReason: `First browser navigation must use the user-supplied hostname ${state.host} exactly. The proposed hostname ${host} was not navigated. Use the supplied URL; do not substitute a remembered brand domain.`,
      };
      state.admitted = true;
    },
    end(event, ctx) { runs.delete(key(ctx) ?? key(event)); },
  };
}

export default function register(api) {
  const guard = createGuard();
  api.on('llm_input', (event, ctx) => guard.beforePrompt(event, ctx));
  api.on('before_tool_call', (event, ctx) => guard.beforeTool(event, ctx));
  api.on('agent_end', (event, ctx) => guard.end(event, ctx));
}
