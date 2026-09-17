import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { identity, selectTools, quickTools, presentation, terminalPhases } from './tool-presentation.js';
import { createActionGate } from './action-gate.js';
const catalog = JSON.parse(readFileSync(new URL('../../catalog/catalog.json', import.meta.url))).tools;
const base = { ...catalog[0], installed_version: null, update_available: false, running_pid: null, running_elsewhere: false, favorite: false };
test('every catalog tool has a distinct icon and survives the default view exactly once', () => {
  assert.equal(new Set(catalog.map((t) => identity(t).icon)).size, catalog.length);
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
  const first = gate.run('tool', task);
  const second = gate.run('tool', task);
  assert.equal(first, second);
  await gate.run('other', async () => 123);
  assert.equal(calls, 1);
  finish('done');
  assert.equal(await first, 'done');
  assert.deepEqual(changes.at(-1), []);
  await gate.run('tool', async () => { calls++; });
  assert.equal(calls, 2);
});
test('failed commands unlock both surfaces and allow retry', async () => {
  let active;
  const gate = createActionGate(ids => { active = ids; });
  await assert.rejects(gate.run('tool', () => { throw new Error('Refused'); }), /Refused/);
  assert.deepEqual(active, []);
  assert.equal(await gate.run('tool', async () => 'retry'), 'retry');
});