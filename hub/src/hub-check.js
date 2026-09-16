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
      if (state.checking) return state;

      state = { checking: true, result: null, message: '' };
      announce();

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
        announce();
      }

      return state;
    },
  };
}
