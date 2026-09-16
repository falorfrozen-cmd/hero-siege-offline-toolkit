// node --test
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createHubCheck, CHECK_FAILED_MESSAGE, NEWEST_RELEASE_MESSAGE } from './hub-check.js';

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
