import { renderMessageText } from './workspace-markdown.js';
import { displayText } from './workspace-text.js';
export const $ = id => document.getElementById(id);
export const node = (tag, className = '', text = '') => {
  const element = document.createElement(tag); element.className = className; element.textContent = displayText(text); return element;
};
export const button = (text, action, className = 'button') => {
  const element = node('button', className, text); element.type = 'button'; element.addEventListener('click', action); return element;
};
export const friendly = value => String(value || '').replaceAll('_', ' ').replace(/^./, first => first.toUpperCase());
export function empty(container, title, detail) {
  const block = node('div', 'empty-state'); block.append(node('h2', '', title), node('p', '', detail)); container.replaceChildren(block);
}
export function message(role, text, pending = false) {
  const element = node('article', `message ${role}${pending ? ' pending' : ''}`);
  const body = node('div', 'message-text');
  renderMessageText(body, text, role !== 'user');
  element.append(node('span', 'message-label', role === 'user' ? 'You' : 'Morrow'), body);
  return element;
}
export function sessions(rows, selected, inspect) {
  $('sessions').replaceChildren(...rows.map(row => {
    const item = button(row.title || 'New conversation', () => inspect(row.session_key), row.session_key === selected ? 'selected' : '');
    item.title = displayText(row.title || 'New conversation'); item.setAttribute('aria-pressed', String(row.session_key === selected)); return item;
  }));
  $('session-empty').hidden = rows.length > 0;
}
export function tasks(rows, inspect, online) {
  if (!online) return empty($('tasks-list'), 'Your workspace is offline.', 'Tasks will be available when your workspace reconnects.');
  if (!rows.length) return empty($('tasks-list'), 'No tasks to show.', 'Tasks will appear here as your assistant works.');
  $('tasks-list').replaceChildren(...rows.map(task => {
    const row = node('article', 'collection-row'); const content = node('div');
    content.append(node('span', 'row-title', task.title || 'Untitled task'), node('span', 'row-meta', task.progress || 'Open the task to see its result.'));
    const actions = node('div', 'detail-actions'); actions.append(node('span', 'state-label', friendly(task.status)), button('View', () => inspect(task.id), 'text-button'));
    row.append(content, actions); return row;
  }));
}
export function taskDetail(task, cancel) {
  const container = $('task-detail'); container.hidden = false;
  container.replaceChildren(node('h2', '', task.title || 'Task details'), node('span', 'state-label', friendly(task.status)));
  if (task.progress) container.append(node('h3', '', 'Progress'), node('p', '', task.progress));
  if (task.result) container.append(node('h3', '', 'Result'), node('p', '', task.result));
  if (task.error) container.append(node('p', 'review-warning', task.error));
  if (['running', 'queued'].includes(task.status)) {
    const actions = node('div', 'detail-actions');
    actions.append(button('Cancel task', () => {
      actions.replaceChildren(node('p', '', 'Cancel this task?'), button('Confirm cancellation', () => cancel(task.id), 'button danger'), button('Keep running', () => taskDetail(task, cancel)));
    }, 'button danger')); container.append(actions);
  }
  container.scrollIntoView({ block: 'nearest' });
}
export const FEATURES = [
  ['calendar', 'Calendar', 'Read events and find free time.', 'Connect calendar'],
  ['email', 'Email', 'Connect a selected mailbox to work with email.', 'Connect email'],
  ['schedules', 'Reminders', 'Schedule a brief or a reminder with a time zone and clear pause control.', 'Create reminder'],
  ['memory', 'Preferences', 'Inspect and edit the preferences your assistant remembers.', 'Edit preferences'],
];
export function featureState(feature) {
  if (feature?.state === 'requires_validation') return 'In validation';
  if (feature?.state === 'implemented') return 'Available';
  return 'Not available';
}
export function connections(capabilities) {
  if (!capabilities) return empty($('connections-list'), 'Connection status is unavailable.', 'Refresh to check which features are available.');
  $('connections-list').replaceChildren(...FEATURES.map(([key, title, detail, action]) => {
    const feature = capabilities.features[key]; const row = node('article', 'feature-row'); row.id = `feature-${key}`;
    const heading = node('h2', '', title); heading.tabIndex = -1;
    row.append(heading, node('span', 'state-label', featureState(feature)), node('p', '', detail));
    const scheduled = key === 'schedules' && feature?.state === 'implemented';
    const control = button(action, () => { if (scheduled) location.hash = 'automations'; }, 'button'); control.disabled = !scheduled;
    control.title = scheduled ? 'Open Automations to create a schedule.' : feature?.state === 'requires_validation' ? 'This feature is still being validated.' : 'This connection is not available in the prototype.';
    row.append(control, node('p', 'feature-note', control.title)); return row;
  }));
  if ($('calendar-state')) $('calendar-state').textContent = featureState(capabilities.features.calendar);
  $('browser-state').textContent = featureState(capabilities.features.browser_workflows);
}
