// The hub's own update check, and what became of the last one.
//
// Deliberately free of runes so it can be run under `node --test`: the same
// reasoning as `progress-rows.js`. `library.svelte.js` owns the reactive copy
// and subscribes to this.
//
// The bug this exists to fix (issue #44): a rejected `check_hub_update` used
// to be swallowed -- `checkHubUpdate()` caught it, showed a toast, and
// returned `null`, which is exactly what a successful check that found
// nothing newer also returns. About then said "This is the newest release"
// after a check that never actually completed. `result` now distinguishes
// the three outcomes so a caller cannot make that mistake again.

/** Shown for a failed check when the rejection carried no text of its own. */
export const CHECK_FAILED_MESSAGE = 'Could not check for updates. Please try again.';

/** Shown after a successful check that found nothing newer. */
export const NEWEST_RELEASE_MESSAGE = 'This is the newest release.';

/**
 * @param invoke  injectable, so a test never needs `@tauri-apps/api` or a
 *                real backend -- the same pattern as `library.svelte.js`
 *                itself, one level down.
 */
export function createHubCheck({ invoke }) {
  let state = { checking: false, result: null, message: '' };
  const watchers = new Set();
  let inflight = null;

  const announce = () => watchers.forEach((watch) => watch(state));

  return {
    /** Called with the new snapshot whenever it changes. */
    watch(fn) {
      watchers.add(fn);
      return () => watchers.delete(fn);
    },

    current() {
      return state;
    },

    /**
     * Ask the backend, and never reject: every caller reads the outcome from
     * the returned (and broadcast) snapshot instead of a catch block, so a
     * failure cannot end up rendered as "current" by a caller that forgot to
     * handle a rejection -- which is exactly how this bug shipped the first
     * time.
     */
    async check() {
      // A second caller waits for the check already running rather than
      // reading its half-finished snapshot as an answer.
      if (inflight) return inflight;

      state = { checking: true, result: null, message: '' };
      announce();

      inflight = (async () => {
        try {
          const update = await invoke('check_hub_update');
          state =
            update == null
              ? { checking: true, result: 'current', message: NEWEST_RELEASE_MESSAGE }
              : { checking: true, result: 'available', message: '' };
        } catch (e) {
          const text = e?.message ?? String(e ?? '');
          state = { checking: true, result: 'failed', message: text || CHECK_FAILED_MESSAGE };
        } finally {
          state = { ...state, checking: false };
          inflight = null;
          announce();
        }
        return state;
      })();

      return inflight;
    },
  };
}

/**
 * The general "check for updates" (Library's and Updates' buttons): the
 * catalog for the tools, then the hub's own release.
 *
 * The hub half goes through `hubCheck` like About's button does, so whichever
 * screen ran the latest check, About shows its outcome -- a check that failed
 * from Updates used to leave About saying "This is the newest release" from an
 * earlier success (PR #56 review). Outside About a failure has nowhere inline
 * to appear, so it is also raised through `notify`.
 *
 * Two requests, deliberately not one: a catalog that failed is no reason to
 * skip the hub's own release, and the reverse cost a release going unnoticed
 * entirely.
 *
 * @returns the refreshed library view, or `undefined` if the catalog check failed.
 */
export async function checkAll({ invoke, hubCheck, notify }) {
  let view;
  try {
    view = await invoke('check_for_updates');
  } catch (e) {
    notify('error', e?.message ?? e);
  }

  const hub = await hubCheck.check();
  if (hub.result === 'failed') notify('error', hub.message);

  return view;
}
