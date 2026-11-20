import { $, node, button, empty, friendly } from './workspace-views.js';

const date = value => value ? new Date(value).toLocaleString(undefined, {dateStyle:'medium',timeStyle:'short'}) : 'Not yet';
function relative(value) {
  if (!value) return '—';
  const minutes = Math.round((value - Date.now()) / 60000);
  if (Math.abs(minutes) < 1) return 'Now';
  const unit = Math.abs(minutes) < 60 ? 'minute' : Math.abs(minutes) < 1440 ? 'hour' : 'day';
  return new Intl.RelativeTimeFormat(undefined, {numeric:'auto'}).format(Math.round(minutes / ({minute:1,hour:60,day:1440}[unit])), unit);
}
function scheduleLabel(schedule) {
  if (schedule.kind === 'every') {
    const m = schedule.everyMs / 60000;
    return `Every ${m % 1440 === 0 ? `${m / 1440}d` : m % 60 === 0 ? `${m / 60}h` : `${m}m`}`;
  }
  if (schedule.kind === 'cron') return `Cron ${schedule.expr}`;
  if (schedule.kind === 'at') return `Once · ${date(schedule.at)}`;
  return 'Managed schedule';
}

export class AutomationPage {
  constructor(api, options) {
    this.api = api; this.options = options; this.tab = 'all'; this.rows = []; this.version = 0;
    this.active = false; this.ended = false; this.busy = false; this.next = null; this.jobFilter = null;
    for (const tab of document.querySelectorAll('[data-automation-tab]')) tab.addEventListener('click', () => {
      this.tab = tab.dataset.automationTab; this.jobFilter = null; this.load();
    });
    $('automation-search').addEventListener('input', () => {
      clearTimeout(this.searchTimer); this.version++;
      this.searchTimer = setTimeout(() => this.load(), 250);
    });
    $('new-automation').addEventListener('click', () => this.edit());
    $('more-automations').addEventListener('click', () => this.load(true));
    for (const id of ['close-automation-editor','cancel-automation-editor']) $(id).addEventListener('click', () => $('automation-editor').close());
    $('automation-schedule').addEventListener('change', () => this.scheduleFields());
    $('automation-form').addEventListener('submit', event => { event.preventDefault(); this.save(); });
    $('cancel-automation-action').addEventListener('click', () => $('automation-confirm').close());
    $('confirm-automation-action').addEventListener('click', () => this.performAction());
    for (const id of ['automation-editor','automation-confirm']) $(id).addEventListener('close', () => {
      if (this.active && !this.ended && !this.busy) this.load();
    });
    const tabs = [...document.querySelectorAll('[data-automation-tab]')];
    tabs.forEach((tab, index) => tab.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus(); tabs[next].click();
    }));
  }
  clear() {
    this.ended = true; this.version++; this.rows = []; this.editing = null; this.action = null;
    document.body.classList.remove('automations-mode');
    clearTimeout(this.searchTimer); clearTimeout(this.pollTimer);
    for (const id of ['automations-list','automation-detail','automation-scope']) $(id).replaceChildren();
    $('automation-form').reset(); $('automation-form-error').textContent = ''; $('automation-search').value = '';
    for (const id of ['automation-editor','automation-confirm']) { if ($(id).open) $(id).close(); }
    $('automation-confirm-title').textContent = ''; $('automation-confirm-detail').textContent = '';
  }
  route(active) {
    this.active = active; this.version++; clearTimeout(this.pollTimer);
    document.body.classList.toggle('automations-mode', active);
    if (active) this.load();
  }
  async load(more = false) {
    if (this.ended || !this.active) return;
    const version = ++this.version; clearTimeout(this.pollTimer);
    $('new-automation').disabled = !this.options.online() || this.busy;
    for (const tab of document.querySelectorAll('[data-automation-tab]')) {
      const selected = this.tab === tab.dataset.automationTab;
      tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
    }
    $('more-automations').hidden = true;
    $('automation-detail').hidden = true;
    if (!this.options.online()) return empty($('automations-list'), 'Your workspace is offline.', 'Schedules and run history will appear when it reconnects.');
    if (!more) $('automations-list').replaceChildren(node('p', 'automation-loading', 'Loading automations…'));
    try {
      const params = {limit:'50',offset:String(more ? this.next : 0),query:$('automation-search').value};
      if (this.tab !== 'history') params.enabled = {active:'enabled',paused:'disabled'}[this.tab] || 'all';
      if (this.jobFilter && this.tab === 'history') params.job_id = this.jobFilter.id;
      const result = await (this.tab === 'history' ? this.api.automationRuns(params) : this.api.automations(params));
      if (this.ended || !this.active || version !== this.version) return;
      this.rows = more ? [...this.rows, ...(result.automations || result.runs)] : (result.automations || result.runs);
      this.next = result.next_offset; this.total = result.total;
      this.render(); $('more-automations').hidden = this.next === null || this.next === undefined;
      this.pollTimer = setTimeout(() => { if (!$('automation-editor').open && !$('automation-confirm').open && $('automation-detail').hidden && !this.busy) this.load(); }, 30000);
    } catch (error) {
      if (this.ended || version !== this.version || error.name === 'AbortError') return;
      empty($('automations-list'), 'Automations could not be loaded.', error.message);
      this.options.report(error);
    }
  }
  render() {
    const scope = $('automation-scope'); scope.hidden = !this.jobFilter;
    if (this.jobFilter) scope.replaceChildren(node('span','',`Runs for ${this.jobFilter.name}`),button('Show all runs',()=>{this.jobFilter=null;this.load();},'text-button'));
    if (!this.rows.length) return empty($('automations-list'), this.tab === 'history' ? 'No runs to show.' : this.tab === 'paused' ? 'No paused automations.' : 'No automations to show.', this.tab === 'history' ? 'Run history appears after a scheduled or manual run.' : 'Create an automation to give a recurring task a schedule.');
    const wrapper = node('div', 'automation-table-wrap'); const table = node('table', `automation-table ${this.tab === 'history' ? 'run-table' : ''}`);
    const caption = node('caption','sr-only', this.tab === 'history' ? 'Automation run history' : 'Automation schedules'); table.append(caption);
    const head = node('thead'); const tr = node('tr');
    for (const label of (this.tab === 'history' ? ['Name','Status','Started','Duration',''] : ['Name','Schedule','Next run','Last run',''])) { const th=node('th','',label);th.scope='col';tr.append(th); }
    head.append(tr); const body = node('tbody');
    for (const item of this.rows) body.append(this.tab === 'history' ? this.runRow(item) : this.jobRow(item));
    table.append(head,body); wrapper.append(table,node('p','automation-count',`${this.rows.length} of ${this.total}`)); $('automations-list').replaceChildren(wrapper);
  }
  cell(label) { const td=node('td'); if(label) td.dataset.label=label; return td; }
  jobRow(job) {
    const tr=node('tr'); const name=this.cell(); const main=node('div','automation-job-name');
    main.append(node('span',`automation-dot ${job.enabled ? 'active' : ''}`));
    main.append(button(job.name,()=>this.details(job),'automation-name')); name.append(main);
    const subtitle=node('div','automation-job-description'); subtitle.append(node('span','automation-assistant','M'),node('span','','Assistant'),...(job.managed?[node('span','automation-managed','Managed')]:[]));
    name.append(subtitle,node('p','automation-description',job.description));
    const schedule=this.cell('Schedule'); schedule.append(node('span','',scheduleLabel(job.schedule)));
    if(job.schedule.kind==='cron') schedule.append(node('small','automation-timezone',job.schedule.tz));
    const next=this.cell('Next run'); next.append(node('span','',job.enabled ? relative(job.next_run_at) : 'Paused')); next.title=job.enabled?date(job.next_run_at):'The schedule is paused';
    const last=this.cell('Last run'); last.title=date(job.last_run_at); last.append(node('span','',relative(job.last_run_at)));
    if(job.last_status) last.append(node('span',`automation-outcome ${job.last_status}`,friendly(job.running?'running':job.last_status)));
    const actions=this.cell(); actions.className='automation-actions';
    if(job.permissions.run) { const run=button('▷',()=>this.confirm(job,'run'),'automation-icon');run.title='Run now';run.setAttribute('aria-label',`Run ${job.name} now`);run.disabled=this.busy||job.running;actions.append(run); }
    if(job.permissions.toggle) { const toggle=button('',()=>this.toggle(job),'automation-toggle'); toggle.setAttribute('role','switch');toggle.setAttribute('aria-checked',String(job.enabled));toggle.setAttribute('aria-label',`${job.enabled?'Pause':'Enable'} ${job.name}`); toggle.disabled=this.busy;actions.append(toggle); }
    const menu=node('details','automation-menu');const summary=node('summary','','···');summary.setAttribute('aria-label',`More actions for ${job.name}`);menu.append(summary);
    const choices=node('div','automation-menu-items');choices.append(button('Details',()=>{menu.open=false;this.details(job);}),button('Run history',()=>{menu.open=false;this.history(job);}));
    if(job.permissions.edit) choices.append(button('Edit',()=>{menu.open=false;this.edit(job);}));
    if(job.permissions.delete) choices.append(button('Delete',()=>{menu.open=false;this.confirm(job,'remove');},'button danger'));
    menu.append(choices);actions.append(menu);tr.append(name,schedule,next,last,actions); return tr;
  }
  runRow(run) {
    const tr=node('tr');const name=this.cell();name.append(node('strong','automation-name',run.name));
    const outcome=this.cell('Status');outcome.append(node('span',`automation-outcome ${run.status}`,friendly(run.status||'unknown')));
    const started=this.cell('Started');started.textContent=date(run.started_at);
    const duration=this.cell('Duration');duration.textContent=typeof run.duration_ms==='number'?`${(run.duration_ms/1000).toFixed(1)}s`:'—';
    const actions=this.cell();actions.className='automation-actions';actions.append(button('View',()=>{
      const panel=$('automation-detail');panel.hidden=false;panel.replaceChildren(node('h2','',run.name),node('p','',friendly(run.status||'unknown')),node('p','',date(run.started_at)),node('p','',run.error||run.summary||'No summary was recorded for this run.'));panel.scrollIntoView({block:'nearest'});
    },'text-button'));tr.append(name,outcome,started,duration,actions);return tr;
  }
  details(job) {
    const panel=$('automation-detail');panel.hidden=false;
    panel.replaceChildren(node('h2','',job.name),node('p','',job.description),node('p','',`${scheduleLabel(job.schedule)}${job.schedule.tz ? ` · ${job.schedule.tz}` : ''}`),node('p','',`Next run: ${job.enabled?date(job.next_run_at):'Paused'}`),node('p','',`Last run: ${date(job.last_run_at)}${job.last_status?` · ${friendly(job.last_status)}`:''}`));
    if(job.last_error) panel.append(node('p','review-warning',job.last_error));
    if(job.managed) panel.append(node('p','form-help','Managed by your workspace. Its definition is not editable here.'));
    panel.append(button('Run history',()=>this.history(job)));panel.scrollIntoView({block:'nearest'});
  }
  history(job) { this.jobFilter=job;this.tab='history';this.load(); }
  async toggle(job) { await this.write(async()=>{await this.api.saveAutomation(job.id,{enabled:!job.enabled,expected_revision:job.revision,idempotency_key:crypto.randomUUID()});this.options.announce(job.enabled?'Automation paused.':'Automation enabled.');}); }
  confirm(job,action) {
    this.action={job,action,key:crypto.randomUUID()};
    $('automation-confirm-title').textContent=action==='run'?`Run ${job.name} now?`:`Delete ${job.name}?`;
    $('automation-confirm-detail').textContent=action==='run'?`This starts a run now. The schedule stays ${job.enabled?'active':'paused'}.`:'This removes the schedule. Its previous runs stay in run history.';
    $('confirm-automation-action').textContent=action==='run'?'Run now':'Delete automation';$('automation-confirm').showModal();
  }
  async performAction() {
    if(!this.action)return;
    const {job,action,key}=this.action;
    await this.write(async()=>{
      const result=await this.api.automationAction(job.id,action,{expected_revision:job.revision,idempotency_key:key});
      if(this.ended)return;
      $('automation-confirm').close();this.options.announce(action==='run'?(result.accepted?'Run requested. Open run history to follow it.':'No new run was started. Check run history.'):'Automation deleted.');
    });
  }
  async write(operation) {
    if(this.busy||this.ended)return;this.busy=true;this.render();$('confirm-automation-action').disabled=true;
    try { await operation();if(!this.ended)await this.load(); } catch(error) { if(!this.ended)this.options.report(error); }
    finally {this.busy=false;$('confirm-automation-action').disabled=false;if(!this.ended){this.render();$('new-automation').disabled=!this.options.online();}}
  }
  scheduleFields() {
    const kind=$('automation-schedule').value;
    for(const current of ['every','cron','at']) $(`automation-${current}-fields`).hidden=current!==kind;
    $('automation-minutes').required=kind==='every';$('automation-expression').required=kind==='cron';$('automation-timezone').required=kind==='cron';$('automation-at').required=kind==='at';
  }
  async edit(job=null) {
    if(this.ended||!this.options.online()||this.busy)return;
    try {
      if(job) job=(await this.api.automation(job.id)).automation;
      if(this.ended)return;
      this.editing=job;this.formKey=crypto.randomUUID();$('automation-form').reset();$('automation-form-error').hidden=true;
      $('automation-editor-title').textContent=job?'Edit automation':'New automation';
      $('automation-name').value=job?.name||'';$('automation-message').value=job?.message||'';$('automation-enabled').checked=job?.enabled||false;
      const s=job?.schedule||{kind:'every',everyMs:3600000};$('automation-schedule').value=s.kind;$('automation-minutes').value=s.everyMs ? s.everyMs/60000 : 60;$('automation-expression').value=s.expr||'0 9 * * *';
      const zone=Intl.DateTimeFormat().resolvedOptions().timeZone;$('automation-timezone').value=s.tz||zone;$('automation-local-zone').textContent=`Time zone: ${zone}.`;
      if(s.at){const d=new Date(s.at);$('automation-at').value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
      this.scheduleFields();$('automation-editor').showModal();$('automation-name').focus();
    } catch(error){this.options.report(error);}
  }
  async save() {
    if(this.busy||this.ended)return;
    const kind=$('automation-schedule').value;
    const schedule=kind==='every'?{kind,every_minutes:Number($('automation-minutes').value)}:kind==='cron'?{kind,expression:$('automation-expression').value.trim(),timezone:$('automation-timezone').value.trim()}:{kind,at:new Date($('automation-at').value).toISOString()};
    const body={name:$('automation-name').value.trim(),message:$('automation-message').value.trim(),enabled:$('automation-enabled').checked,schedule,idempotency_key:this.formKey};
    if(this.editing) body.expected_revision=this.editing.revision;
    this.busy=true;$('save-automation').disabled=true;$('automation-form-error').hidden=true;
    try {
      await this.api.saveAutomation(this.editing?.id,body);if(this.ended)return;
      $('automation-editor').close();this.options.announce(body.enabled?'Automation saved and active.':'Automation saved as paused.');await this.load();
    } catch(error) {if(!this.ended){if(error.code==='INVALID_INPUT')this.formKey=crypto.randomUUID();$('automation-form-error').textContent=error.message;$('automation-form-error').hidden=false;}}
    finally{this.busy=false;$('save-automation').disabled=false;if(!this.ended)$('new-automation').disabled=!this.options.online();}
  }
}
