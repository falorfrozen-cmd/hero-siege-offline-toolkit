import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { identity, selectTools, quickTools, presentation, terminalPhases } from './tool-presentation.js';
import { createActionGate, operationKey, ToolBusyError } from './action-gate.js';
const catalog = JSON.parse(readFileSync(new URL('../../catalog/catalog.json', import.meta.url))).tools;
const base = { ...catalog[0], installed_version: null, update_available: false, running_pid: null, running_elsewhere: false, favorite: false };
test('known icons stay distinct and catalog-only tools survive the default view exactly once', () => {
  // Remote catalog additions must work before a new Toolkit binary supplies an icon.
  const branded = catalog.filter(t => identity(t).category !== 'other');
  assert.equal(new Set(branded.map(t => identity(t).icon)).size, branded.length);
  for (const tool of catalog.filter(t => identity(t).category === 'other')) {
    assert.equal(identity(tool).icon, 'cube');
    assert.equal(identity(tool).title, tool.name);
    assert.equal(identity(tool).summary, tool.summary);
  }
  const shown = selectTools(catalog);
  assert.deepEqual(new Set(shown.map(t => t.id)), new Set(catalog.map(t => t.id)));
  const future = { ...base, id: 'new-tool', name: 'A future tool' };
  assert.ok(selectTools([...catalog, future]).includes(future));
});
test('search uses full names, aliases, descriptions, and intersects category and installed filters', () => {
  const tools = catalog.map(t => ({ ...t, installed_version: t.id === 'hero-siege-item-editor' ? '2.0' : null }));
  assert.equal(selectTools(tools, { query: '  ITEM  editor ', category: 'editors', availability: 'installed' })[0].id, 'hero-siege-item-editor');
  assert.equal(selectTools(tools, { query: 'cube', category: 'gameplay' }).length, 0);
  assert.equal(selectTools(tools, { query: 'nonexistent' }).length, 0);
  assert.equal(selectTools(tools, { availability: 'available' }).length, tools.length - 1);
});
test('quick launch honors filters, shows all favorites, and falls back only to installed/running tools', () => {
  const tools = catalog.map((t,i) => ({ ...t, favorite: i < 5, installed_version: i === 6 ? '1.0' : null }));
  assert.equal(quickTools(selectTools(tools)).length, 5);
  assert.equal(quickTools(selectTools(tools, { query: 'nonexistent' })).length, 0);
  assert.equal(quickTools(tools.map(t => ({ ...t, favorite: false }))).length, 1);
  assert.deepEqual(quickTools(catalog), []);
});
test('backend update flag drives action; installed HTML opens, external NSIS gets release page', () => {
  assert.equal(presentation(base).primary.command, 'install_tool');
  assert.equal(presentation({ ...base, installed_version: '2.0' }).primary.label, 'Launch');
  assert.equal(presentation({ ...base, installed_version: '2.0', update_available: true }).primary.label, 'Update');
  assert.equal(presentation({ ...base, installed_version: '1', artifact: { kind: 'html' } }).primary.label, 'Open');
  assert.equal(presentation({ ...base, artifact: { kind: 'nsis' } }).primary.command, 'open_release');
});
test('an outdated installed copy (e.g. right after a rollback) offers a secondary launch beside Update', () => {
  const outdated = { ...base, installed_version: '1.0', update_available: true };
  const { primary, secondary } = presentation(outdated);
  assert.equal(primary.command, 'install_tool');
  assert.equal(primary.label, 'Update');
  assert.equal(secondary.command, 'launch_tool');
  assert.equal(secondary.label, 'Launch installed');
  assert.equal(secondary.aria, 'Launch installed ForgePact');
  assert.ok(secondary.why.includes('1.0'));
  assert.ok(secondary.why.includes(base.version));
});
test('secondary launch stays hidden whenever a second action would duplicate or fight the primary', () => {
  assert.equal(presentation(base).secondary, null);
  assert.equal(presentation({ ...base, installed_version: '2.0' }).secondary, null);
  assert.equal(presentation({ ...base, installed_version: '1.0', update_available: true, running_pid: 42, can_stop: true }).secondary, null);
  assert.equal(presentation({ ...base, installed_version: '1.0', update_available: true, running_elsewhere: true }).secondary, null);
  assert.equal(presentation({ ...base, installed_version: '1.0', update_available: true }, { phase: 'downloading' }).secondary, null);
  const done = presentation({ ...base, update_available: true }, { phase: 'done', version: '3.0' });
  assert.equal(done.secondary, null);
});
test('secondary launch mirrors the installed action label for HTML tools, and survives a staged update', () => {
  const html = presentation({ ...base, installed_version: '1.0', update_available: true, artifact: { kind: 'html' } });
  assert.equal(html.secondary.label, 'Open installed');
  const staged = presentation({ ...base, installed_version: '1.0', update_available: true, staged: { version: '9.9' } });
  assert.equal(staged.secondary.command, 'launch_tool');
});
test('running copy only offers Stop with a PID the backend can stop', () => {
  assert.equal(presentation({ ...base, running_pid: 42, can_stop: true, update_available: true }).primary.command, 'stop_tool');
  assert.equal(presentation({ ...base, running_pid: 42, can_stop: false }).primary.command, null);
  assert.equal(presentation({ ...base, running_elsewhere: true }).primary.command, null);
  assert.equal(presentation({ ...base, running_pid: 42, running_elsewhere: true, can_stop: true }).primary.command, 'stop_tool');
});
test('install transitions disable actions, clamp progress and close the done-event gap', () => {
  for (const phase of ['started', 'downloading', 'verifying', 'extracting', 'activating']) {
    assert.equal(presentation(base, { phase }).primary.command, null);
  }
  assert.equal(presentation(base, { phase: 'downloading', total: 10, received: 11 }).chip.text, 'Downloading 100%');
  const done = presentation({ ...base, update_available: true }, { phase: 'done', version: '3.0' });
  assert.equal(done.installed, '3.0');
  assert.equal(done.primary.label, 'Launch');
  assert.equal(done.chip.text, 'Installed');
});
test('failed installs retry; terminal staged/downloaded events do not masquerade as installed', () => {
  assert.equal(presentation(base, { phase: 'failed' }).primary.label, 'Try again');
  for (const phase of terminalPhases) assert.equal(presentation(base, { phase }).inFlight, false);
  for (const phase of ['staged', 'downloaded']) assert.equal(presentation(base, { phase, version: '3.0' }).installed, null);
  assert.equal(presentation({ ...base, staged: { version: '3.0' } }).chip.text, 'Update staged');
});
test('duplicate launch/card clicks invoke a command once, independent tools can proceed', async () => {
  const changes = [];
  const gate = createActionGate(ids => changes.push(ids));
  let calls = 0;
  let finish;
  const task = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
  const first = gate.run('tool', 'launch', task);
  const second = gate.run('tool', 'launch', task);
  assert.equal(first, second);
  await gate.run('other', 'launch', async () => 123);
  assert.equal(calls, 1);
  finish('done');
  assert.equal(await first, 'done');
  assert.deepEqual(changes.at(-1), []);
  await gate.run('tool', 'launch', async () => { calls++; });
  assert.equal(calls, 2);
});
test('failed commands unlock both surfaces and allow retry', async () => {
  let active;
  const gate = createActionGate(ids => { active = ids; });
  await assert.rejects(gate.run('tool', 'launch', () => { throw new Error('Refused'); }), /Refused/);
  assert.deepEqual(active, []);
  assert.equal(await gate.run('tool', 'launch', async () => 'retry'), 'retry');
});

test('rollback during an install is refused, keeps the install locked, and works after it settles', async () => {
  let active, finish;
  const calls = [];
  const gate = createActionGate(ids => { active = ids; });
  const install = gate.run('tool', 'install_tool', () => {
    calls.push('install');
    return new Promise(resolve => { finish = resolve; });
  });
  const rollback = () => { calls.push('rollback'); return 'rolled back'; };
  await assert.rejects(gate.run('tool', 'rollback_tool', rollback), ToolBusyError);
  assert.deepEqual(calls, ['install']);
  assert.deepEqual(active, ['tool']);
  assert.equal(gate.run('tool', 'install_tool', () => assert.fail('duplicate install')), install);
  finish('installed');
  assert.equal(await install, 'installed');
  assert.deepEqual(active, []);
  assert.equal(await gate.run('tool', 'rollback_tool', rollback), 'rolled back');
  assert.deepEqual(calls, ['install', 'rollback']);
});

test('same command with different launch arguments is not reported as the pending launch', async () => {
  const gate = createActionGate();
  const key = operationKey('launch_tool', { id: 'tool', fromSource: false });
  const launch = gate.run('tool', key, () => 'launched installed copy');
  await assert.rejects(gate.run('tool', operationKey('launch_tool', { id: 'tool', fromSource: true }),
    () => assert.fail('source launch must wait')), ToolBusyError);
  assert.equal(await launch, 'launched installed copy');
});

test('identical IPC arguments coalesce regardless of property order', async () => {
  const gate = createActionGate();
  const a = operationKey('launch_tool', { id: 'tool', fromSource: true });
  const b = operationKey('launch_tool', { fromSource: true, id: 'tool' });
  const first = gate.run('tool', a, () => 'launched');
  assert.equal(gate.run('tool', b, () => assert.fail('duplicate launch')), first);
  assert.equal(await first, 'launched');
});
