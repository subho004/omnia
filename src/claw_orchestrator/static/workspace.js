import { renderMessageText } from './workspace-markdown.js';
import { WorkspaceAPI, APIError } from './workspace-api.js';
import { AutomationPage } from './workspace-automations.js';
import { ChatActivity, activityHistory } from './workspace-activity.js';
import { displayText } from './workspace-text.js';
import { $, node, button, message, empty, sessions, connections } from './workspace-views.js';

const viewSession = document.querySelector('meta[name="workspace-session"]').content;
const pageUser = document.body.dataset.userId;
const state = {
  ended: false, view: 'chat', online: false, streamReady: false, capabilities: null,
  sessions: [], selected: null, history: [], historyCursor: null, sessionOffset: 0,
  run: null, streamText: '', streamMessage: null, pendingSend: null, sending: false,
  newSessionKey: null, booting: false,
};
let browserEpoch = 0, recentEpoch = 0, recentTimer;
let streamController, historyController, pollTimer, identityTimer, reconnectTimer, chatEpoch = 0, historyVersion = 0;
let recoveryAttempts = 0;
const finishedRuns = new Set();
const chatSequences = new Map();
const api = new WorkspaceAPI(viewSession, endSession);
const activity = new ChatActivity($('chat-activity'), $('agent-status'));
const automationPage = new AutomationPage(api, {online: () => state.online, report, announce});
const channel = (() => { try { return new BroadcastChannel('claw-auth'); } catch { return null; } })();
if (channel) channel.onmessage = event => {
  if (event.data?.type === 'session-changed' && event.data.marker !== viewSession) endSession();
};

function announce(text = '', error = false) {
  if (state.ended) return;
  $('announcement').hidden = !text; $('announcement').textContent = displayText(text);
  $('announcement').classList.toggle('error', error);
}
function endSession() {
  if (state.ended) return;
  state.ended = true; activity.clear(); chatSequences.clear(); finishedRuns.clear(); automationPage.clear(); api.stop(); streamController?.abort(); historyController?.abort();
  clearTimeout(pollTimer); clearTimeout(reconnectTimer); clearInterval(identityTimer); clearInterval(recentTimer); recentEpoch++; chatEpoch++; browserEpoch++;
  state.history = []; state.sessions = []; state.browser = null; state.browserDraft = '';
  state.pendingSend = null; state.streamText = ''; state.selected = null;
  for (const id of ['messages','sessions','recent-activity','connections-list','browser-connection']) $(id).replaceChildren();
  $('message').value = ''; $('account-name').textContent = ''; document.querySelector('.avatar').textContent = '';
  document.body.classList.add('session-locked'); document.body.classList.remove('nav-open');
  for (const element of document.querySelectorAll('.view,.workspace-header,.workspace-notice,.announcement,.test-runtime-notice,.context-rail')) element.hidden = true;
  $('session-ended').hidden = false; $('session-ended-title').tabIndex = -1; $('session-ended-title').focus();
}
function controls() {
  const ready = state.online && state.streamReady && !state.ended && !state.booting;
  $('send').disabled = !ready || state.sending || Boolean(state.run) || !$('message').value.trim() || Boolean(state.pendingSend);
  $('new-chat').disabled = !state.online || state.sending || state.ended || state.booting;
  $('new-chat').hidden = !state.online;
  $('message').readOnly = Boolean(state.pendingSend);
  $('stop-run').hidden = !state.run; $('stop-run').disabled = !state.online;
  $('retry-send').hidden = !state.pendingSend || state.pendingSend.accepted;
  $('retry-send').disabled = !ready || state.sending;
  $('composer-help').textContent = !state.online ? 'Messages are available when your workspace is online.' : !state.streamReady ? 'Connecting live updates before you send…' : state.run ? 'Your assistant is responding. You can stop this response.' : 'Enter to send · Shift + Enter for a new line';
}
function runtime(status) {
  state.online = status === 'ready';
  $('runtime-label').textContent = state.online ? 'Online' : status === 'reconnecting' ? 'Reconnecting' : ['pending','provisioning'].includes(status) ? 'Preparing' : 'Offline';
  $('runtime-dot').classList.toggle('online', state.online);
  $('workspace-notice').hidden = state.online;
  $('notice-title').textContent = status === 'reconnecting' ? 'Reconnecting your workspace…' : ['pending','provisioning'].includes(status) ? 'Preparing your workspace…' : 'Your workspace is offline.';
  $('notice-detail').textContent = status === 'reconnecting' ? 'Checking the connection automatically. Your conversation and draft are retained.' : ['pending','provisioning'].includes(status) ? 'You can explore while your workspace is being prepared.' : 'Reconnect your workspace to send messages.';
  if (state.online && !$('recent-activity').childNodes.length) $('activity-summary').textContent = 'Checking automation activity…';
  if (!state.online) {
    activity.pause?.();
    $('recent-activity').replaceChildren();
    state.streamReady = false; streamController?.abort();
    $('activity-summary').textContent = 'Activity will appear when your workspace reconnects.';
  }
  controls();
}
function errorMessage(error) {
  return error instanceof APIError ? error.message : 'Unable to reach your workspace. Try refreshing.';
}
function scheduleRecovery() {
  if (state.ended) return;
  clearTimeout(pollTimer);
  const delay = Math.min(30000, 2000 * 2 ** Math.min(recoveryAttempts++, 4));
  // Reconcile the authenticated workspace; never repeat a message submission.
  pollTimer = setTimeout(() => { if (!state.ended) act(bootstrap)(); }, delay);
}
function report(error) {
  if (state.ended || error?.name === 'AbortError') return;
  if (error instanceof TypeError || (error instanceof APIError && error.status >= 500 && error.code !== 'RECONNECT_REQUIRED')) {
    runtime('reconnecting'); scheduleRecovery();
  }
  announce(errorMessage(error), true);
}
function act(operation) { return (...args) => Promise.resolve().then(() => { if (!state.ended) return operation(...args); }).catch(report); }
function renderSessions() {
  sessions(state.sessions, state.selected, key => act(async () => { navigate('chat'); await selectSession(key); })());
}
function navigate(view) {
  if (view === 'tasks') view = 'automations';
  if (view === 'reviews') view = 'chat';
  if (state.ended || !['chat','automations','connections'].includes(view)) return;
  const drawerWasOpen = document.body.classList.contains('nav-open');
  state.view = view; history.replaceState(null, '', `${location.pathname}#${view}`);
  document.body.classList.remove('nav-open'); $('open-nav').setAttribute('aria-expanded', 'false');
  for (const id of ['chat','automations','connections']) $(`${id}-view`).hidden = id !== view;
  for (const item of document.querySelectorAll('[data-view]')) {
    if (item.dataset.view === view) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current');
  }
  $('view-name').textContent = view[0].toUpperCase() + view.slice(1);
  if (drawerWasOpen) $('main').focus();
  automationPage.route(view === 'automations');
  if (view === 'connections') { connections(state.capabilities); act(loadBrowser)(); }
}
function renderHistory() {
  const scroll = $('chat-scroll'); const follow = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 80;
  const resultIds = new Set(state.history.flatMap(item => (item.activities || []).filter(a => a.phase === 'result').map(a => a.item_id)));
  const content = state.history.flatMap(item => {
    const parts = [];
    if (item.text?.trim() && item.role !== 'activity') parts.push(message(item.role, item.text));
    const steps = (item.activities || []).filter(a => a.phase !== 'recorded' || !resultIds.has(a.item_id));
    if (steps.length) parts.push(activityHistory(steps));
    return parts;
  });
  const activityRoot = activity.root;
  $('messages').replaceChildren(...content, activityRoot);
  $('chat-welcome').hidden = state.history.length > 0 || Boolean(state.pendingSend) || Boolean(state.run);
  $('more-history').hidden = !state.historyCursor;
  if (state.pendingSend && !state.pendingSend.accepted) $('messages').append(message('user', state.pendingSend.text, true));
  if (state.streamText) { state.streamMessage = message('assistant', state.streamText); $('messages').append(state.streamMessage); }
  else state.streamMessage = null;
  if (follow) scroll.scrollTop = scroll.scrollHeight;
}
async function loadHistory(earlier = false, epoch = chatEpoch) {
  if (!state.selected || !state.online) return;
  const version = ++historyVersion;
  const result = await api.history(state.selected, earlier ? state.historyCursor : null, historyController.signal);
  if (state.ended || epoch !== chatEpoch || version !== historyVersion) return;
  state.history = earlier ? [...result.messages, ...state.history] : result.messages;
  activity.reconcileHistory?.(state.history.flatMap(item => item.activities || []));
  if (result.in_flight && !finishedRuns.has(result.in_flight.run_id)) {
    state.run = result.in_flight.run_id; activity.restore(result.in_flight);
    if (result.in_flight.text) state.streamText = result.in_flight.text;
  }
  state.historyCursor = result.next_cursor; renderHistory();
}
async function selectSession(key, preserve = false) {
  if (state.ended) return;
  clearTimeout(reconnectTimer);
  const saved = preserve && key === state.selected ? { draft: $('message').value, pending: state.pendingSend, run: state.run } : null;
  const epoch = ++chatEpoch; streamController?.abort(); historyController?.abort(); historyController = new AbortController();
  state.selected = key; state.history = []; state.historyCursor = null; state.streamReady = false;
  if (!saved) { activity.clear(); chatSequences.clear(); }
  state.run = null; state.streamText = ''; state.pendingSend = null; state.sending = false;
  $('message').value = saved?.draft || '';
  if (saved) { state.pendingSend = saved.pending; state.run = saved.run; }
  renderSessions(); renderHistory(); controls();
  if (!state.online) return;
  const controller = new AbortController(); streamController = controller;
  api.stream(key, controller.signal, async (type, data) => {
    if (state.ended || epoch !== chatEpoch || controller.signal.aborted) return;
    if (type === 'ready') {
      await loadHistory(false, epoch);
      if (epoch !== chatEpoch || state.ended) return;
      state.streamReady = true; controls();
      activity.resume();
    } else if (type === 'chat') {
      if (data.session_key !== key || (state.run && state.run !== data.run_id)) return;
      if (finishedRuns.has(data.run_id)) return;
      if (Number.isSafeInteger(data.sequence) && data.run_id) {
        if ((chatSequences.get(data.run_id) ?? -1) >= data.sequence) return;
        chatSequences.set(data.run_id, data.sequence);
        if (chatSequences.size > 100) chatSequences.delete(chatSequences.keys().next().value);
      }
      if (data.run_id) state.run = data.run_id;
      if (data.run_id && data.state !== 'delta') activity.begin(data.run_id);
      if (data.activity) activity.accept(data.activity);
      if (data.run_id && data.state === 'delta') activity.begin(data.run_id, 'Writing response');
      if (data.message?.role === 'assistant' && typeof data.message.text === 'string') state.streamText = data.message.text;
      else if (typeof data.delta_text === 'string') state.streamText = data.replace ? data.delta_text : state.streamText + data.delta_text;
      if (state.streamText) {
        if (!state.streamMessage) { state.streamMessage = message('assistant', ''); $('messages').append(state.streamMessage); }
        renderMessageText(state.streamMessage.querySelector('.message-text'), state.streamText);
        $('chat-welcome').hidden = true;
      }
      controls();
      if (['final','error','aborted'].includes(data.state)) {
        activity.finish(data.run_id, data.state, data.yielded === true);
        if (data.run_id && !data.yielded) { finishedRuns.add(data.run_id); if (finishedRuns.size > 100) finishedRuns.delete(finishedRuns.values().next().value); }
        state.run = null; state.streamText = ''; state.pendingSend = null;
        await loadHistory(false, epoch); controls();
        if (data.state === 'error') announce(data.error?.message || 'Your assistant could not finish this response. Check the conversation before trying again.', true);
        if (data.state === 'aborted') announce('Response stopped.');
        if (state.view === 'automations') await automationPage.load();
      }
    } else if (type === 'activity' && data.session_key === key) {
      activity.accept(data); $('chat-welcome').hidden = true;
      if (data.kind === 'recovery') {
        activity.pause?.(); clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => { if (epoch === chatEpoch && !state.ended) act(loadSessions)(); }, 250);
      }
    } else if (type === 'session.message' && !state.run && !state.sending) {
      await loadHistory(false, epoch);
    }
  }).catch(error => {
    if (epoch !== chatEpoch || controller.signal.aborted || state.ended) return;
    state.streamReady = false; controls();
    activity.pause?.();
    if (error instanceof APIError && error.code === 'RECONNECT_REQUIRED') {
      // A bounded stream ending is not a workspace outage. Reconcile history
      // and active runs before a fresh subscription; never resend a message.
      reconnectTimer = setTimeout(() => {
        if (epoch === chatEpoch && !state.ended && state.online) act(loadSessions)();
      }, 1000);
    } else report(error);
  });
}
async function loadSessions(more = false) {
  if (!state.online) return;
  const offset = more ? state.sessionOffset + 50 : 0;
  const result = await api.sessions(offset);
  if (state.ended || !state.online) return;
  state.sessionOffset = offset; state.sessions = more ? [...state.sessions, ...result.sessions] : result.sessions;
  $('more-sessions').hidden = result.sessions.length < 50 || offset >= 9950; renderSessions();
  if (!more) {
    if (!state.sessions.length) await newConversation();
    else {
      const selected = state.sessions.find(item => item.session_key === state.selected);
      if (selected && !selected.has_active_run && state.pendingSend?.accepted) { state.pendingSend = null; state.run = null; }
      await selectSession(selected ? selected.session_key : state.sessions[0].session_key, Boolean(selected));
    }
  }
}
async function newConversation() {
  if (!state.online) return;
  $('new-chat').disabled = true;
  state.newSessionKey ||= crypto.randomUUID();
  try {
    const result = await api.createSession(state.newSessionKey);
    if (state.ended) return;
    state.newSessionKey = null;
    if (!state.sessions.some(item => item.session_key === result.session_key)) state.sessions.unshift({ session_key: result.session_key, title: 'New conversation' });
    navigate('chat'); await selectSession(result.session_key); $('message').focus();
  } finally { controls(); }
}
async function submit(retry = false) {
  if (!state.online || !state.streamReady || state.booting || state.sending || state.run || !state.selected) return;
  if (!retry) {
    if (state.pendingSend) return;
    const text = $('message').value.trim(); if (!text) return;
    state.pendingSend = { key: state.selected, text, id: crypto.randomUUID(), accepted: false };
  }
  const submission = state.pendingSend; if (!submission || submission.accepted) return;
  const epoch = chatEpoch; state.sending = true; renderHistory(); controls(); announce();
  try {
    const result = await api.send(submission.key, submission.text, submission.id);
    if (state.ended || epoch !== chatEpoch) return;
    submission.accepted = true; state.run = finishedRuns.has(result.run_id) ? null : result.run_id;
    if (state.run) activity.begin(state.run);
    if (!state.run) state.pendingSend = null;
    $('message').value = '';
    // Reload the persisted user turn. Acceptance alone is not an assistant reply.
    await loadHistory(false, epoch);
  } catch (error) {
    if (!state.ended && epoch === chatEpoch && error?.name !== 'AbortError') {
      announce('The message was not confirmed. Retry uses the same submission, so check the conversation before starting another one.', true);
      if (error instanceof APIError && error.status === 503) runtime('unavailable');
    }
  } finally {
    if (epoch === chatEpoch) { state.sending = false; controls(); }
  }
}


async function loadRecentActivity() {
  if (state.ended || !state.online || document.hidden) return;
  const epoch = ++recentEpoch;
  try {
    const result = await api.automationRuns({limit: '8', offset: '0'});
    if (state.ended || !state.online || epoch !== recentEpoch) return;
    const runs = Array.isArray(result.runs) ? result.runs : [];
    $('activity-summary').textContent = runs.length ? 'Latest automation runs across your workspace.' : 'Automation results will appear here automatically.';
    $('recent-activity').replaceChildren(...runs.map(run => {
      const row = button('', () => {
        navigate('automations');
        document.querySelector('[data-automation-tab="history"]')?.click();
      }, 'recent-run');
      row.append(node('strong', '', run.name || 'Automation'), node('span', `recent-run-status ${run.status || ''}`, String(run.status || 'Unknown').replaceAll('_', ' ')));
      if (run.summary) row.append(node('span', 'recent-run-summary', run.summary));
      if (run.error) row.append(node('span', 'recent-run-summary', run.error));
      if (typeof run.started_at === 'number') row.append(node('time', '', new Date(run.started_at).toLocaleString()));
      return row;
    }));
  } catch (error) {
    if (!state.ended && state.online && epoch === recentEpoch && error?.name !== 'AbortError') $('activity-summary').textContent = 'Automation activity is temporarily unavailable. It will reconnect automatically.';
  }
}

async function loadBrowser() {
  const epoch = ++browserEpoch;
  const container = $('browser-connection');
  if (!state.online) { container.replaceChildren(node('p', 'muted', 'Connect your workspace to use its browser.')); return; }
  container.replaceChildren(node('p', 'muted', 'Checking browser…'));
  try {
    const result = await api.browser();
    if (state.ended || epoch !== browserEpoch) return;
    state.browser = result.browser || result;
    drawBrowser();
  } catch (error) {
    if (state.ended || epoch !== browserEpoch) return;
    container.replaceChildren(node('p', 'muted', 'Browser status is unavailable.'), button('Try again', act(loadBrowser)));
    announce(errorMessage(error), true);
  }
}
function drawBrowser() {
  const container = $('browser-connection'), browser = state.browser || {};
  const connected = browser.connected === true || browser.running === true;
  $('browser-state').textContent = connected ? 'Running in workspace' : 'Starts automatically';
  container.replaceChildren(node('span', 'state-label', connected ? 'Running in workspace' : 'Starts automatically'));
  container.append(node('p', 'muted', 'Your assistant starts its private browser inside your workspace when needed. No connection or browser extension is required. Website access follows workspace network policy.'));
  const actions = node('div', 'detail-actions');
  actions.append(button('Refresh browser status', act(loadBrowser)));
  container.append(actions);
  const tabs = Array.isArray(browser.tabs) ? browser.tabs : [];
  if (connected) {
    const form = node('form', 'browser-open-form');
    const label = node('label', '', 'Website address'); label.htmlFor = 'browser-url';
    const input = node('input'); input.id = 'browser-url'; input.type = 'url'; input.required = true; input.maxLength = 2048; input.autocomplete = 'off'; input.placeholder = 'https://example.com'; input.value = state.browserDraft || '';
    input.addEventListener('input', () => { state.browserDraft = input.value; });
    const open = node('button', 'button primary', 'Open website'); open.type = 'submit';
    open.disabled = false; input.disabled = false;
    open.title = 'Open public website';
    form.append(label, input, open);
    form.addEventListener('submit', event => {
      event.preventDefault();
      act(async () => {
        open.disabled = true;
        try { await api.openBrowserTab(input.value.trim()); if (!state.ended) { state.browserDraft = ''; await loadBrowser(); } }
        catch (error) { if (!state.ended) { open.disabled = false; announce(errorMessage(error), true); } }
      })();
    });
    container.append(form);
    const list = node('div', 'browser-tabs');
    list.append(node('h3', '', 'Open tabs'));
    if (!tabs.length) list.append(node('p', 'muted', 'No browser tabs are open.'));
    for (const tab of tabs) {
      const row = node('article', 'browser-tab');
      row.append(node('strong', '', tab.title || 'Untitled tab'), node('span', 'muted', tab.url || ''));
      list.append(row);
    }
    container.append(list);
  }
}

async function bootstrap() {
  if (state.booting || state.ended) return;
  state.booting = true; controls(); $('refresh').disabled = true; clearTimeout(pollTimer); announce();
  try {
    const identity = await api.me(); if (identity.user.id !== pageUser) return endSession();
    let instance;
    try { instance = await api.instance(); }
    catch (error) {
      if (error.code !== 'INSTANCE_NOT_CREATED') throw error;
      instance = await api.createInstance();
    }
    const capabilities = await api.capabilities(); if (state.ended) return;
    state.capabilities = capabilities;
    $('test-runtime-notice').hidden = capabilities.runtime_validation !== 'controlled_test_runtime';
    connections(capabilities); runtime(instance.instance.status);
    if (state.online) {
      await loadSessions();
      act(loadRecentActivity)();
      recentTimer ||= setInterval(() => act(loadRecentActivity)(), 10000);
    }
    if (state.view === 'automations') await automationPage.load();
    if (state.view === 'connections') await loadBrowser();
    if (state.online) recoveryAttempts = 0;
    else if (['pending','provisioning'].includes(instance.instance.status)) pollTimer = setTimeout(() => act(bootstrap)(), 2000);
    else scheduleRecovery();
  } catch (error) {
    runtime('unavailable'); report(error);
  }
  finally { state.booting = false; $('refresh').disabled = false; controls(); }
}

for (const item of document.querySelectorAll('[data-view]')) item.addEventListener('click', event => { event.preventDefault(); navigate(item.dataset.view); });
$('refresh').addEventListener('click', act(bootstrap)); $('retry-runtime').addEventListener('click', act(bootstrap));
$('new-chat').addEventListener('click', act(newConversation)); $('more-sessions').addEventListener('click', act(() => loadSessions(true)));
$('more-history').addEventListener('click', act(() => loadHistory(true)));
$('composer').addEventListener('submit', event => { event.preventDefault(); act(() => submit())(); });
$('message').addEventListener('input', controls);
$('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); act(() => submit())(); } });
$('retry-send').addEventListener('click', act(() => submit(true)));
$('stop-run').addEventListener('click', act(async () => { if (state.run && state.selected) { await api.abort(state.selected, state.run); announce('Stop requested. Waiting for the response to finish.'); } }));
for (const element of document.querySelectorAll('[data-suggestion]')) element.addEventListener('click', () => {
  if (element.dataset.suggestion === 'browser') {
    const input = $('message');
    input.value = 'Use the browser to ';
    controls();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    return;
  }
  navigate('connections');
  const id = { day: 'calendar', browser: 'browser_workflows' }[element.dataset.suggestion];
  const heading = element.dataset.suggestion === 'browser' ? $('browser-connection-title') : document.querySelector(`#feature-${id} h2`); heading?.focus(); heading?.scrollIntoView({ block: 'center' });
});
function closeNav() { document.body.classList.remove('nav-open'); $('open-nav').setAttribute('aria-expanded', 'false'); $('open-nav').focus(); }
$('open-nav').addEventListener('click', () => { document.body.classList.add('nav-open'); $('open-nav').setAttribute('aria-expanded', 'true'); requestAnimationFrame(() => $('close-nav').focus()); });
$('close-nav').addEventListener('click', closeNav); $('nav-overlay').addEventListener('click', closeNav);
document.addEventListener('keydown', event => {
  if (!document.body.classList.contains('nav-open')) return;
  if (event.key === 'Escape') closeNav();
  if (event.key === 'Tab') {
    const items = [...$('sidebar').querySelectorAll('a,button:not(:disabled)')].filter(item => item.offsetParent !== null);
    const index = items.indexOf(document.activeElement);
    if (index === -1) { event.preventDefault(); (event.shiftKey ? items.at(-1) : items[0])?.focus(); }
    else if (event.shiftKey && index === 0) { event.preventDefault(); items.at(-1)?.focus(); }
    else if (!event.shiftKey && index === items.length - 1) { event.preventDefault(); items[0]?.focus(); }
  }
});
async function checkIdentity() {
  if (state.ended || document.hidden) return;
  try { const result = await api.me(); if (result.user.id !== pageUser) endSession(); }
  catch (error) { if (!state.ended && error.name !== 'AbortError') report(error); }
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkIdentity(); });
window.addEventListener('focus', checkIdentity);
window.addEventListener('pagehide', endSession);
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
window.addEventListener('hashchange', () => navigate(location.hash.slice(1)));
identityTimer = setInterval(checkIdentity, 10000);
navigate(location.hash.slice(1) === 'tasks' ? 'automations' : ['chat','automations','connections'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'chat');
act(bootstrap)();
