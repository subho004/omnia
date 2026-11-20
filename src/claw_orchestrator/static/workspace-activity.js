import { displayText } from './workspace-text.js';

const LIMIT = 150;
const WAITING_PHASES = new Set(['waiting-approval', 'waiting-question', 'requested', 'waiting-on-user']);
const FAILED_PHASES = new Set(['error', 'failed', 'cancelled', 'timed_out', 'aborted']);
const safe = (value, limit = 12000) => displayText(typeof value === 'string' ? value.slice(0, limit) : '');
const identifier = value => typeof value === 'string' && value.length > 0 && value.length <= 600 ? value : null;
const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const element = (tag, className = '', text = '') => {
  const result = document.createElement(tag);
  result.className = className;
  result.textContent = text;
  return result;
};
const elapsed = startedAt => {
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
};

function normalize(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const kind = safe(value.kind, 50) || 'status';
  const phase = safe(value.phase, 64) || 'running';
  const run = identifier(value.run_id);
  const item = identifier(value.item_id);
  const id = identifier(value.id) || [run || 'workspace', kind, item || 'status'].join(':');
  const result = {
    id, kind, phase, run_id: run, item_id: item,
    label: safe(value.label, 250) || 'Workspace activity',
    detail: safe(value.detail), terminal: value.terminal === true,
    outcome: safe(value.outcome, 50), sequence: number(value.sequence),
    timestamp: number(value.timestamp), approval_id: identifier(value.approval_id),
    output_tokens: number(value.output_tokens),
  };
  if (value.changes && typeof value.changes === 'object') {
    const added = number(value.changes.added), removed = number(value.changes.removed);
    if (added !== null || removed !== null) result.changes = { added, removed };
  }
  if (Array.isArray(value.steps)) {
    result.steps = value.steps.slice(0, 30).filter(step => step && typeof step === 'object').map(step => ({
      text: safe(step.text, 500),
      status: ['pending', 'in_progress', 'completed'].includes(step.status) ? step.status : 'pending',
    }));
  }
  return result;
}

function stateOf(entry) {
  if (entry.outcome === 'unknown' || entry.kind === 'tool' && entry.phase === 'recorded') return 'unknown';
  if (FAILED_PHASES.has(entry.phase) || ['failed', 'blocked', 'denied', 'aborted', 'timed out'].includes(entry.outcome)) return 'failed';
  if (WAITING_PHASES.has(entry.phase)) return 'waiting';
  if (entry.terminal) return 'completed';
  return 'running';
}

function stateLabel(entry) {
  const state = stateOf(entry);
  if (state === 'unknown') return entry.phase === 'recorded' ? 'Recorded action' : 'Result not confirmed';
  if (state === 'failed') {
    if (entry.outcome === 'blocked') return 'Blocked';
    if (entry.outcome === 'denied') return 'Denied';
    return entry.phase === 'cancelled' || entry.phase === 'aborted' ? 'Stopped' : 'Failed';
  }
  if (state === 'waiting') return entry.kind === 'question' || entry.phase === 'waiting-question' || entry.phase === 'waiting-on-user' ? 'Your input needed' : 'Review needed';
  if (state === 'completed') return entry.kind === 'tool' || entry.kind === 'task' ? 'Completed' : 'Recorded';
  return entry.phase === 'queued' ? 'Queued' : entry.phase === 'review' ? 'Under review' : 'In progress';
}

function disclosure(key, className, expanded, remember) {
  const details = element('details', className);
  details.open = expanded;
  details.addEventListener('toggle', () => { if (details.isConnected) remember?.(key, details.open); });
  return details;
}

function entryCard(entry, { expanded = false, remember, onReview } = {}) {
  const state = stateOf(entry), details = disclosure(entry.key || entry.id, `activity-item activity-item--${state}`, expanded, remember);
  details.dataset.activityKey = entry.key || entry.id;
  const summary = element('summary', 'activity-item-summary');
  const mark = element('span', 'activity-mark', state === 'completed' ? '✓' : state === 'failed' ? '!' : state === 'unknown' ? '–' : '●');
  mark.setAttribute('aria-hidden', 'true');
  summary.append(mark, element('span', 'activity-label', entry.label), element('span', 'activity-state', stateLabel(entry)), element('span', 'activity-chevron', '›'));
  details.dataset.kind = entry.kind;
  details.append(summary);
  const body = element('div', 'activity-item-body');
  if (entry.detail) body.append(element('pre', 'activity-output', entry.detail));
  else if (entry.kind === 'tool') body.append(element('p', 'activity-empty', state === 'completed' ? 'Action finished without text output.' : state === 'unknown' ? 'No final result was received for this action.' : 'The result will appear here when this action finishes.'));
  if (entry.changes) {
    const changes = [];
    if (entry.changes.added !== null) changes.push(`+${entry.changes.added} added`);
    if (entry.changes.removed !== null) changes.push(`−${entry.changes.removed} removed`);
    body.append(element('p', 'activity-changes', changes.join(' · ')));
  }
  if (entry.steps?.length) {
    const list = element('ol', 'activity-plan');
    for (const step of entry.steps) {
      const row = element('li', `activity-plan-step activity-plan-step--${step.status}`);
      row.append(element('span', '', step.text), element('span', 'activity-step-state', { pending: 'Pending', in_progress: 'In progress', completed: 'Completed' }[step.status]));
      list.append(row);
    }
    body.append(list);
  }
  if (entry.approval_id && state === 'waiting' && typeof onReview === 'function') {
    const button = element('button', 'text-button', 'Review action');
    button.type = 'button';
    button.dataset.activityAction = 'review';
    button.addEventListener('click', () => onReview(entry.approval_id));
    body.append(button);
  }
  if (body.childNodes.length) details.append(body);
  return details;
}

function keyOf(entry) {
  // Native tool-call IDs can repeat across runs. Never key by a tool label.
  return JSON.stringify([entry.run_id || 'workspace', entry.kind, entry.item_id || entry.id]);
}

export function activityHistory(activities) {
  const wrapper = element('div', 'activity-history');
  const rows = new Map();
  for (const value of Array.isArray(activities) ? activities.slice(0, LIMIT) : []) {
    const entry = normalize(value);
    if (!entry) continue;
    entry.key = keyOf(entry);
    const previous = rows.get(entry.key);
    if (previous?.phase === 'result' && entry.phase !== 'result') continue;
    // A transcript tool-call is a record of an attempt, not completion proof.
    if (!entry.terminal) {
      entry.terminal = true; entry.outcome = entry.kind === 'tool' ? 'unknown' : 'recorded';
      if (entry.kind !== 'tool') entry.phase = 'recorded';
    }
    rows.set(entry.key, { ...previous, ...entry });
  }
  if (!rows.size) return wrapper;
  for (const entry of rows.values()) wrapper.append(entryCard(entry));
  return wrapper;
}

export class ChatActivity {
  constructor(root, statusNode, { onReview } = {}) {
    this.root = root; this.statusNode = statusNode; this.onReview = onReview;
    this.entries = new Map(); this.groups = new Map(); this.expanded = new Map();
    this.current = null; this.timer = null; this.lastStatus = ''; this.paused = false;
    this.statusClassName = statusNode?.className || '';
    if (root) { root.setAttribute('aria-label', 'Assistant activity'); root.setAttribute('role', 'region'); }
    if (statusNode) { statusNode.setAttribute('role', 'status'); statusNode.setAttribute('aria-live', 'polite'); statusNode.setAttribute('aria-atomic', 'true'); }
  }
  clear() {
    clearInterval(this.timer); this.timer = null;
    this.entries.clear(); this.groups.clear(); this.expanded.clear();
    this.current = null; this.lastStatus = ''; this.paused = false;
    this.root?.replaceChildren(); if (this.root) this.root.hidden = true;
    this.statusNode?.replaceChildren(); if (this.statusNode) this.statusNode.hidden = true;
  }
  begin(runId, label = 'Thinking') {
    const run = identifier(runId);
    if (!run) return;
    this.paused = false;
    const previous = this.groups.get(run);
    if (previous?.terminal) { this.render(); return; }
    this.current = run;
    this.groups.set(run, { startedAt: previous?.startedAt || Date.now(), ...previous, label: safe(label, 250) || 'Thinking', active: true, terminal: false });
    this.render();
  }
  pause() {
    this.paused = true;
    clearInterval(this.timer); this.timer = null;
    this.render();
  }
  resume() { this.paused = false; this.render(); }
  accept(data) {
    const entry = normalize(data);
    if (!entry) return false;
    entry.key = keyOf(entry);
    const old = this.entries.get(entry.key);
    if (old) {
      if (old.sequence !== null && entry.sequence !== null && entry.sequence <= old.sequence) return false;
      if (old.terminal && !entry.terminal) return false;
      if (old.phase === 'result' && entry.phase !== 'result') return false;
      if (old.sequence === entry.sequence && old.phase === entry.phase && old.detail === entry.detail && old.outcome === entry.outcome) return false;
    }
    const groupKey = entry.run_id || 'workspace';
    let group = this.groups.get(groupKey);
    if (!group) {
      group = { startedAt: Date.now(), label: 'Background activity', active: false, terminal: false };
      this.groups.set(groupKey, group);
    }
    if (group.terminal && !entry.terminal) {
      entry.terminal = true;
      entry.outcome = entry.kind === 'tool' ? 'unknown' : 'recorded';
      if (entry.kind !== 'tool') entry.phase = 'recorded';
    }
    if (!entry.terminal && ['thinking', 'progress', 'tool'].includes(entry.kind) || entry.kind === 'lifecycle' && entry.phase === 'start') group.yielded = false;
    if (old && !entry.detail && old.detail) entry.detail = old.detail;
    if (old && entry.kind === 'tool' && entry.label === 'Use workspace action' && old.label !== entry.label) entry.label = old.label;
    if (old?.persisted) entry.persisted = true;
    this.entries.set(entry.key, entry);
    if (entry.phase === 'approval-resolved' || entry.kind === 'approval' && entry.phase === 'resolved') {
      const approval = entry.approval_id || entry.item_id;
      for (const previous of this.entries.values()) {
        if (approval && previous.run_id === entry.run_id && (previous.approval_id || previous.item_id) === approval && WAITING_PHASES.has(previous.phase)) {
          previous.terminal = true; previous.phase = 'approval-resolved'; previous.label = 'Review decision received';
        }
      }
    }
    if (entry.output_tokens !== null) group.outputTokens = entry.output_tokens;
    while (this.entries.size > LIMIT) {
      const key = this.entries.keys().next().value;
      this.entries.delete(key); this.expanded.delete(key);
    }
    const retained = new Set([...this.entries.values()].map(item => item.run_id || 'workspace'));
    for (const key of this.groups.keys()) {
      if (key !== this.current && !retained.has(key)) { this.groups.delete(key); this.expanded.delete(`group:${key}`); }
    }
    this.render(); return true;
  }
  restore(inFlight) {
    if (!inFlight || typeof inFlight !== 'object' || !identifier(inFlight.run_id)) return;
    this.begin(inFlight.run_id, 'Working');
    const started = number(inFlight.started_at);
    if (started !== null && started > 0 && started <= Date.now()) this.groups.get(inFlight.run_id).startedAt = started;
    for (const entry of Array.isArray(inFlight.activities) ? inFlight.activities.slice(0, LIMIT) : []) {
      if (!entry?.run_id || entry.run_id === inFlight.run_id) this.accept({ ...entry, run_id: inFlight.run_id });
    }
    this.render();
  }
  reconcileHistory(activities) {
    const tools = new Set();
    for (const value of Array.isArray(activities) ? activities : []) {
      const entry = normalize(value);
      if (!entry || entry.kind !== 'tool' || !entry.item_id) continue;
      tools.add(JSON.stringify([entry.run_id, entry.item_id]));
      // Some native transcript tool results omit runId. Within this one selected
      // conversation, a persisted tool-call ID still replaces its live card.
      if (!entry.run_id) tools.add(JSON.stringify([null, entry.item_id]));
    }
    for (const entry of this.entries.values()) {
      if (entry.kind === 'tool' && entry.item_id && (tools.has(JSON.stringify([entry.run_id, entry.item_id])) || tools.has(JSON.stringify([null, entry.item_id])))) entry.persisted = true;
    }
    // Retain entries and sequence floors to reject a delayed duplicate event.
    this.render();
  }
  finish(runId, state = 'final', yielded = false) {
    const run = identifier(runId), group = run ? this.groups.get(run) : null;
    if (!group) return;
    if (yielded) {
      group.active = true; group.label = 'Waiting for delegated work'; group.yielded = true;
      this.render(); return;
    }
    if (group.terminal) return;
    group.active = false; group.terminal = true; group.endedAt = Date.now(); group.state = state;
    group.label = state === 'final' ? 'Response complete' : state === 'aborted' ? 'Response stopped' : 'Response interrupted';
    for (const entry of this.entries.values()) {
      if (entry.run_id === run && !entry.terminal) {
        entry.terminal = true;
        entry.outcome = entry.kind === 'tool' ? 'unknown' : 'recorded';
        if (entry.kind !== 'tool') entry.phase = 'recorded';
      }
    }
    this.render();
  }
  historyCard(activities) { return activityHistory(activities); }
  status() {
    const group = this.current ? this.groups.get(this.current) : null;
    if (this.paused) return { group: group || { active: false }, text: 'Reconnecting live activity', state: 'paused' };
    if (!group) return null;
    const rows = [...this.entries.values()].filter(entry => entry.run_id === this.current);
    if (!group.active) return { group, text: group.label, state: group.state === 'final' ? 'completed' : 'failed' };
    const waiting = rows.findLast(entry => !entry.terminal && (WAITING_PHASES.has(entry.phase) || entry.kind === 'approval' && entry.phase === 'requested'));
    const compacting = rows.findLast(entry => entry.kind === 'compaction' && !entry.terminal);
    const latest = rows.findLast(entry => entry.kind !== 'usage' && entry.kind !== 'output' && entry.kind !== 'plan' && entry.kind !== 'patch');
    if (waiting) return { group, text: waiting.label, state: 'waiting' };
    if (compacting) return { group, text: compacting.label, state: 'running' };
    if (group.yielded) return { group, text: group.label, state: 'waiting' };
    if (latest?.kind === 'lifecycle' && latest.terminal) return { group, text: latest.phase === 'error' ? 'Response interrupted' : 'Finishing response', state: latest.phase === 'error' ? 'failed' : 'running' };
    if (latest?.kind === 'tool' && latest.terminal) return { group, text: 'Continuing response', state: 'running' };
    return { group, text: latest?.label || group.label, state: latest?.kind === 'observer' && latest.phase === 'failed' ? 'failed' : 'running' };
  }
  renderStatus() {
    if (!this.statusNode) return;
    const current = this.status();
    this.statusNode.hidden = !current;
    if (!current) { this.statusNode.replaceChildren(); this.lastStatus = ''; return; }
    const { group, text, state } = current;
    const signature = JSON.stringify([text, state, group.active, group.outputTokens]);
    if (signature !== this.lastStatus) {
      this.lastStatus = signature;
      this.statusNode.className = `${this.statusClassName} activity-live activity-live--${state}`.trim();
      const mark = element('span', 'activity-live-mark', state === 'completed' ? '✓' : state === 'failed' ? '!' : '●');
      mark.setAttribute('aria-hidden', 'true');
      this.statusNode.replaceChildren(mark, element('span', 'activity-live-label', text));
      if (group.active && !this.paused) {
        const duration = element('span', 'activity-elapsed', elapsed(group.startedAt));
        duration.setAttribute('aria-hidden', 'true'); this.statusNode.append(duration);
      }
      if (group.outputTokens !== undefined) this.statusNode.append(element('span', 'activity-token-count', `${Math.floor(group.outputTokens).toLocaleString()} output tokens`));
    }
    const duration = this.statusNode.querySelector('.activity-elapsed');
    if (duration) duration.textContent = elapsed(group.startedAt);
  }
  render() {
    const scroll = this.root?.closest('.chat-scroll');
    const follow = scroll && scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 80;
    const retained = new Set([...this.entries.values()].map(entry => entry.run_id || 'workspace'));
    for (const key of this.groups.keys()) {
      if (key !== this.current && !retained.has(key)) { this.groups.delete(key); this.expanded.delete(`group:${key}`); }
    }
    if (this.root) {
      const focused = this.root.contains(document.activeElement) ? document.activeElement : null;
      const focusKey = focused?.closest('[data-activity-key]')?.dataset.activityKey;
      const focusAction = focused?.dataset.activityAction;
      const focusedSummary = focused?.tagName === 'SUMMARY';
      const cards = [];
      for (const [run, group] of this.groups) {
        const rows = [...this.entries.values()].filter(entry => (entry.run_id || 'workspace') === run && entry.kind !== 'usage' && !entry.persisted);
        if (!rows.length) continue;
        // Native-style inline tool cards; routine transport/progress events remain
        // represented by the single live status instead of becoming a debug log.
        for (const entry of rows) {
          if (!['tool', 'plan', 'patch', 'task', 'approval', 'question', 'notice', 'compaction', 'fallback', 'observer'].includes(entry.kind) && stateOf(entry) !== 'failed') continue;
          cards.push(entryCard(entry, { expanded: this.expanded.get(entry.key) ?? false, remember: (id, open) => this.expanded.set(id, open), onReview: this.onReview }));
        }
      }
      this.root.replaceChildren(...cards); this.root.hidden = cards.length === 0;
      if (focused && focusKey && (focusedSummary || focusAction)) {
        const owner = [...this.root.querySelectorAll('[data-activity-key]')].find(node => node.dataset.activityKey === focusKey);
        const target = focusedSummary ? owner?.querySelector(':scope > summary') : [...(owner?.querySelectorAll('[data-activity-action]') || [])].find(node => node.dataset.activityAction === focusAction);
        target?.focus({ preventScroll: true });
      }
    }
    this.renderStatus();
    if (follow) scroll.scrollTop = scroll.scrollHeight;
    const active = !this.paused && this.current && this.groups.get(this.current)?.active;
    if (active && !this.timer) this.timer = setInterval(() => this.renderStatus(), 1000);
    if (!active && this.timer) { clearInterval(this.timer); this.timer = null; }
  }
}
