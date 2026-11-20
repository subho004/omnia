import assert from 'node:assert/strict';
import test from 'node:test';
import {createGuard, suppliedHost} from '../infra/morrow-browser-guard/index.mjs';

test('extract one explicit hostname without treating email or filenames as destinations', () => {
  assert.equal(suppliedHost('Open zepto.com and search for Monster.'), 'zepto.com');
  assert.equal(suppliedHost('Read AGENTS.md and email a@other.org; open https://EXAMPLE.com/path.'), 'example.com');
  assert.equal(suppliedHost('Open example.com and other.org'), null);
  assert.equal(suppliedHost('Open the grocery app'), null);
  assert.equal(suppliedHost('Open https://user:password@example.com'), null);
  assert.equal(suppliedHost('Open https://bücher.example'), 'xn--bcher-kva.example');
  assert.equal(suppliedHost('Open bücher.example'), null);
});

test('reject substituted first hosts without rewriting args; allow a corrected destination', () => {
  const guard = createGuard(), ctx = {runId:'run-a'};
  guard.beforePrompt({prompt:'Open example.com'}, ctx);
  const wrong = {toolName:'browser',params:{action:'open',targetUrl:'https://other.org'}};
  const before = JSON.stringify(wrong);
  assert.equal(guard.beforeTool(wrong,ctx).block,true);
  assert.equal(JSON.stringify(wrong),before);
  assert.equal(guard.beforeTool({toolName:'browser',params:{action:'open',targetUrl:'https://www.example.com'}},ctx).block,true);
  assert.equal(guard.beforeTool({toolName:'browser',params:{action:'navigate',url:'https://example.com'}},ctx),undefined);
  // Subsequent observed links and redirects are not restricted by this guard.
  assert.equal(guard.beforeTool(wrong,ctx),undefined);
});

test('isolate runs, ignore non-navigation tools, and retire state after a turn', () => {
  const g=createGuard(),a={runId:'a'},b={runId:'b'};
  g.beforePrompt({prompt:'Open example.com'},a);
  g.beforePrompt({prompt:'Open other.org'},b);
  const nav={toolName:'browser',params:{action:'navigate',url:'https://other.org'}};
  assert.equal(g.beforeTool({toolName:'exec',params:{command:'printf marker'}},a),undefined);
  assert.equal(g.beforeTool({toolName:'tool_call',params:{id:'browser'}},a),undefined);
  assert.equal(g.beforeTool({toolName:'browser',params:{action:'snapshot'}},a),undefined);
  assert.equal(g.beforeTool(nav,a).block,true);
  assert.equal(g.beforeTool(nav,b),undefined);
  g.end({},a);
  g.beforePrompt({prompt:'Open other.org'},a);
  assert.equal(g.beforeTool(nav,a),undefined);
});

test('do not reset the constraint on repeated prompt preparation within a run', () => {
  const g=createGuard(),ctx={runId:'same'};
  g.beforePrompt({prompt:'Open example.com'},ctx);
  g.beforePrompt({prompt:'A later context mentions other.org'},ctx);
  assert.equal(g.beforeTool({toolName:'browser',params:{action:'open',targetUrl:'https://other.org'}},ctx).block,true);
});

test('bind the native llm_input run ID when hook context has no run ID', () => {
  const g=createGuard();
  g.beforePrompt({runId:'native-run',prompt:'Open example.com'}, {sessionKey:'one'});
  assert.equal(g.beforeTool({runId:'native-run',toolName:'browser',params:{action:'open',targetUrl:'https://other.org'}},{sessionKey:'one'}).block,true);
  assert.equal(g.beforeTool({runId:'native-run',toolName:'browser',params:{action:'open',targetUrl:'https://example.com'}},{sessionKey:'one'}),undefined);
  g.end({runId:'native-run'}, {});
});
