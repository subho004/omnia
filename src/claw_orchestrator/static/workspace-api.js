const MESSAGES = {
  BROWSER_REQUEST_REJECTED: 'This website or action is blocked by workspace browser policy.',
  BROWSER_UNAVAILABLE: 'Your browser could not start. Try reconnecting.',
  BROWSER_DESTINATION_REJECTED: 'Enter a public website address beginning with http:// or https://.',
  BROWSER_NOT_CONNECTED: 'Connect your browser first.',
  SESSION_CHANGED: 'This account changed. Return to login to continue.',
  AUTH_REQUIRED: 'Sign in to continue.', INVALID_SESSION: 'Your session has ended.',
  SESSION_ENDED: 'Your session has ended.', INSTANCE_NOT_CREATED: 'Your workspace has not been created yet.',
  INSTANCE_NOT_READY: 'Your workspace needs attention before you can continue.',
  INSTANCE_UNAVAILABLE: 'Your workspace is offline. Try refreshing its status.',
  RUNTIME_NOT_CONFIGURED: 'Your workspace needs setup before it can start.',
  GATEWAY_UNAVAILABLE: 'The workspace connection was interrupted. Reconnecting automatically.',
  GATEWAY_REJECTED: 'Your workspace could not complete this request.',
  GATEWAY_PROTOCOL_ERROR: 'Your workspace returned an unexpected response. Refresh and try again.',
  CONNECTION_LIMIT: 'There are too many open connections. Close an unused workspace tab.',
  INVALID_CSRF: 'This request could not be verified. Refresh and try again.',
  INVALID_ORIGIN: 'This request could not be verified.',
  INVALID_INPUT: 'Check the fields and try again.',
  REVIEW_EXPIRED_OR_CHANGED: 'This review expired or changed. Reload the proposal and review it again.',
  APPROVAL_CHANGED: 'This action has changed or already has a decision. Reload its current state.',
  APPROVAL_EXPIRED: 'This action has expired. Reload its current state.',
  DECISION_NOT_ALLOWED: 'This decision is no longer available.',
  RECONNECT_REQUIRED: 'Live updates paused. Reconnecting before you send another message.',
  SUBSCRIPTION_UNAVAILABLE: 'Live updates are unavailable. Refresh to try again.',
  APPROVAL_REPLAY_UNAVAILABLE: 'Reviews are unavailable. Refresh to try again.',
  AUTOMATION_NOT_FOUND: 'This automation is no longer available. Refresh the list.',
  AUTOMATION_CHANGED: 'This automation changed. Reload it before saving.',
  AUTOMATION_REQUEST_CHANGED: 'The settings changed. Close this form and try again.',
  AUTOMATION_OUTCOME_UNKNOWN: 'The action was not confirmed. Check run history before trying again.',
  AUTOMATION_MANAGED: 'This automation is managed by your workspace.',
  AUTOMATION_REJECTED: 'The schedule could not be saved. Check its settings and time zone.',
};
export class APIError extends Error {
  constructor(status, code) {
    super(MESSAGES[code] || (status === 503 ? 'The service is temporarily unavailable.' : 'The request could not be completed. Try again.'));
    this.name = 'APIError'; this.status = status; this.code = code;
  }
}
export function readEvent(block) {
  let type = 'message'; const data = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  return data.length ? { type, data: JSON.parse(data.join('\n')) } : null;
}
export class WorkspaceAPI {
  constructor(session, onEnded) {
    this.session = session; this.onEnded = onEnded; this.lifetime = new AbortController();
  }
  async response(path, { body, signal, stream = false } = {}) {
    const headers = { 'X-Workspace-Session': this.session };
    if (body !== undefined) {
      const csrf = await this.request('/auth/csrf', { signal });
      headers['X-CSRF-Token'] = csrf.csrf_token; headers['Content-Type'] = 'application/json';
    }
    if (stream) headers.Accept = 'text/event-stream';
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST', headers, credentials: 'same-origin',
      cache: 'no-store', signal: signal ? AbortSignal.any([signal, this.lifetime.signal]) : this.lifetime.signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      const error = new APIError(response.status, result.error?.code || 'REQUEST_FAILED');
      if (response.status === 401 || error.code === 'SESSION_CHANGED') this.onEnded();
      throw error;
    }
    return response;
  }
  async request(path, options = {}) {
    const response = await this.response(path, options);
    return response.status === 204 ? null : response.json();
  }
  browser() { return this.request('/api/assistant/browser'); }
  connectBrowser() { return this.request('/api/assistant/browser/connect', { body: {} }); }
  disconnectBrowser() { return this.request('/api/assistant/browser/disconnect', { body: {} }); }
  openBrowserTab(url) { return this.request('/api/assistant/browser/tabs', { body: { url } }); }
  me() { return this.request('/auth/me'); }
  capabilities() { return this.request('/api/assistant/capabilities'); }
  instance() { return this.request('/api/instance'); }
  createInstance() { return this.request('/api/instance', { body: {} }); }
  sessions(offset = 0) { return this.request(`/api/assistant/sessions?limit=50&offset=${offset}`); }
  createSession(key) { return this.request('/api/assistant/sessions', { body: { idempotency_key: key } }); }
  history(key, cursor, signal) {
    return this.request(`/api/assistant/history?${new URLSearchParams({ session_key: key, ...(cursor ? { cursor } : {}) })}`, { signal });
  }
  send(key, text, id) {
    return this.request('/api/assistant/messages', { body: { session_key: key, message: text, idempotency_key: id } });
  }
  abort(key, id) { return this.request('/api/assistant/runs/abort', { body: { session_key: key, run_id: id } }); }
  tasks(status, cursor) {
    return this.request(`/api/assistant/tasks?${new URLSearchParams({ limit: '50', ...(status ? { status } : {}), ...(cursor ? { cursor } : {}) })}`);
  }
  task(id) { return this.request(`/api/assistant/tasks/${encodeURIComponent(id)}`); }
  automations(parameters) { return this.request(`/api/assistant/automations?${new URLSearchParams(parameters)}`); }
  automationRuns(parameters) { return this.request(`/api/assistant/automations/runs?${new URLSearchParams(parameters)}`); }
  automation(id) { return this.request(`/api/assistant/automations/${encodeURIComponent(id)}`); }
  saveAutomation(id, body) { return this.request(`/api/assistant/automations${id ? `/${encodeURIComponent(id)}/update` : ''}`, {body}); }
  automationAction(id, action, body) { return this.request(`/api/assistant/automations/${encodeURIComponent(id)}/${action}`, {body}); }
  cancelTask(id) { return this.request(`/api/assistant/tasks/${encodeURIComponent(id)}/cancel`, { body: {} }); }
  pending(key) { return this.request(`/api/assistant/approvals?${new URLSearchParams({ session_key: key })}`); }
  reviewHistory(cursor) { return this.request(`/api/assistant/approvals/history?${new URLSearchParams(cursor ? { cursor } : {})}`); }
  review(id) { return this.request(`/api/assistant/approvals/${encodeURIComponent(id)}`); }
  resolve(id, decision, reviewToken) {
    return this.request(`/api/assistant/approvals/${encodeURIComponent(id)}/resolve`, { body: { decision, review_token: reviewToken } });
  }
  async stream(key, signal, handler) {
    const response = await this.response(`/api/assistant/events?${new URLSearchParams({ session_key: key, include_approvals: 'true' })}`, { signal, stream: true });
    if (!response.headers.get('content-type')?.startsWith('text/event-stream') || !response.body) throw new APIError(502, 'SUBSCRIPTION_UNAVAILABLE');
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer = (buffer + decoder.decode(value, { stream: true })).replaceAll('\r\n', '\n');
        if (buffer.length > 2 * 1024 * 1024) throw new APIError(502, 'GATEWAY_PROTOCOL_ERROR');
        let index;
        while ((index = buffer.indexOf('\n\n')) !== -1) {
          const event = readEvent(buffer.slice(0, index)); buffer = buffer.slice(index + 2);
          if (!event) continue;
          if (event.type === 'error') {
            if (event.data.code === 'SESSION_ENDED') this.onEnded();
            throw new APIError(event.data.code === 'SESSION_ENDED' ? 401 : 503, event.data.code);
          }
          if (['ready', 'chat', 'activity', 'session.message', 'session.approval', 'approval.replay'].includes(event.type)) await handler(event.type, event.data);
        }
      }
      if (!signal.aborted && !this.lifetime.signal.aborted) throw new APIError(503, 'RECONNECT_REQUIRED');
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
  stop() { this.lifetime.abort(); }
}
