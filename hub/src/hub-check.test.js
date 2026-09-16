// node --test
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createHubCheck, checkAll, CHECK_FAILED_MESSAGE, NEWEST_RELEASE_MESSAGE } from './hub-check.js';

/** An `invoke` whose answer for `check_hub_update` is controlled by the test. */
function fakeInvoke() {
  let resolveWith;
  let rejectWith;
  const calls = [];
  let pending = null;

  return {
    calls,
    get callCount() {
      return calls.length;
    },
    invoke: (command, args) => {
      calls.push([command, args]);
      pending = new Promise((resolve, reject) => {
        resolveWith = resolve;
        rejectWith = reject;
      });
      return pending;
    },
    resolve: (value) => resolveWith(value),
    reject: (error) => rejectWith(error),
  };
}

test('a successful check with no update says this is the newest release', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const promise = hubCheck.check();
  fake.resolve(null);
  const result = await promise;

  assert.equal(result.result, 'current');
  assert.equal(result.message, NEWEST_RELEASE_MESSAGE);
  assert.equal(result.checking, false);
});

test('a successful check that finds a release reports it available', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const promise = hubCheck.check();
  fake.resolve({ version: '1.0.3', current_version: '1.0.2' });
  const result = await promise;

  assert.equal(result.result, 'available');
  assert.equal(result.checking, false);
});

test('a failed check is not reported as the newest release', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const promise = hubCheck.check();
  fake.reject(new Error(CHECK_FAILED_MESSAGE));
  const result = await promise;

  assert.equal(result.result, 'failed');
  assert.equal(result.message, CHECK_FAILED_MESSAGE);
  assert.notEqual(result.message, NEWEST_RELEASE_MESSAGE);
  assert.equal(result.checking, false);
});

test('a rejection with no text falls back to the generic failure message', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const promise = hubCheck.check();
  fake.reject(new Error(''));
  const result = await promise;

  assert.equal(result.message, CHECK_FAILED_MESSAGE);
});

test('the check can be run again after a failure', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const first = hubCheck.check();
  fake.reject(new Error('offline'));
  await first;
  assert.equal(hubCheck.current().checking, false);

  const second = hubCheck.check();
  fake.resolve(null);
  await second;

  assert.equal(fake.callCount, 2);
});

test('the check can be run again after a success', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const first = hubCheck.check();
  fake.resolve(null);
  await first;
  assert.equal(hubCheck.current().checking, false);

  const second = hubCheck.check();
  fake.resolve(null);
  await second;

  assert.equal(fake.callCount, 2);
});

test('a check already in flight is not started twice', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const first = hubCheck.check();
  const second = hubCheck.check();

  assert.equal(fake.callCount, 1);
  assert.equal(hubCheck.current().checking, true);

  fake.resolve(null);
  await first;
  await second;
});

test('checking is true while the request is pending', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const promise = hubCheck.check();
  assert.equal(hubCheck.current().checking, true);

  fake.resolve(null);
  await promise;
  assert.equal(hubCheck.current().checking, false);
});

/** An `invoke` that answers each command from a table, synchronously resolved. */
function tableInvoke(answers) {
  const calls = [];
  return {
    calls,
    invoke: async (command) => {
      calls.push(command);
      const answer = answers[command];
      if (answer instanceof Error) throw answer;
      return answer;
    },
  };
}

test('a failed general check replaces an earlier About success (PR #56 review)', async () => {
  const answers = { check_hub_update: null, check_for_updates: { tools: [] } };
  const fake = tableInvoke(answers);
  const hubCheck = createHubCheck({ invoke: fake.invoke });
  const toasts = [];

  await hubCheck.check(); // About's button, endpoint answering 204
  assert.equal(hubCheck.current().result, 'current');

  answers.check_hub_update = new Error(CHECK_FAILED_MESSAGE); // endpoint now 503
  await checkAll({ invoke: fake.invoke, hubCheck, notify: (kind, text) => toasts.push([kind, text]) });

  assert.equal(hubCheck.current().result, 'failed');
  assert.notEqual(hubCheck.current().message, NEWEST_RELEASE_MESSAGE);
  assert.equal(hubCheck.current().checking, false);
  assert.deepEqual(toasts, [['error', CHECK_FAILED_MESSAGE]]);
});

test('the general check still checks the hub when the catalog check fails', async () => {
  const fake = tableInvoke({ check_for_updates: new Error('catalog down'), check_hub_update: null });
  const hubCheck = createHubCheck({ invoke: fake.invoke });
  const toasts = [];

  const view = await checkAll({ invoke: fake.invoke, hubCheck, notify: (kind, text) => toasts.push([kind, text]) });

  assert.equal(view, undefined);
  assert.deepEqual(fake.calls, ['check_for_updates', 'check_hub_update']);
  assert.equal(hubCheck.current().result, 'current');
  assert.deepEqual(toasts, [['error', 'catalog down']]);
});

test('the general check returns the new view and raises no toast on success', async () => {
  const fake = tableInvoke({ check_for_updates: { tools: ['x'] }, check_hub_update: null });
  const hubCheck = createHubCheck({ invoke: fake.invoke });
  const toasts = [];

  const view = await checkAll({ invoke: fake.invoke, hubCheck, notify: (kind, text) => toasts.push([kind, text]) });

  assert.deepEqual(view, { tools: ['x'] });
  assert.deepEqual(toasts, []);
});

test('a second caller during a check shares its outcome instead of seeing it unfinished', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });

  const first = hubCheck.check();
  const second = hubCheck.check();
  fake.reject(new Error('offline'));

  assert.equal((await first).result, 'failed');
  assert.equal((await second).result, 'failed');
  assert.equal((await second).checking, false);
  assert.equal(fake.callCount, 1);
});

test('watch is notified after each change', async () => {
  const fake = fakeInvoke();
  const hubCheck = createHubCheck({ invoke: fake.invoke });
  const seen = [];
  const unsubscribe = hubCheck.watch((snapshot) => seen.push(snapshot.checking));

  const promise = hubCheck.check();
  fake.resolve(null);
  await promise;

  assert.deepEqual(seen, [true, false]);
  unsubscribe();
});
