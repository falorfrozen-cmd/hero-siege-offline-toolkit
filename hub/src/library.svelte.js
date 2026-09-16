// The one copy of what the hub currently knows.
//
// Every view reads this; nothing recomputes it. In particular `update_available`
// is decided in Rust and carried here as a field, so the `0.9.10` against
// `0.9.8` comparison has exactly one implementation rather than one per screen.

import { invoke, listen, native } from './bridge.js';
import { createProgressRows } from './progress-rows.js';
import { createHubCheck } from './hub-check.js';

let view = $state(null);
let loading = $state(true);
let checking = $state(false);

// The hub's own check result, and whether it failed, live in a runes-free
// module so `node --test` can execute them -- the same split as `rows` below.
// `About.svelte` reads this instead of guessing "no update" from a swallowed
// rejection, which is the bug in issue #44.
const hubCheck = createHubCheck({ invoke });
let hubCheckSnapshot = $state(hubCheck.current());
hubCheck.watch((next) => {
  hubCheckSnapshot = next;
});

/**
 * Things that went wrong, shown as toasts until dismissed.
 *
 * This was a single `error` string on a banner at the top of the scrolling
 * content, and it was wrong twice over. The banner sat above the tool grid, so
 * an error raised by the eighth card appeared somewhere the reader had scrolled
 * past -- and it was cleared by the next successful read, which back then ran
 * on a ten-second poll, so anything not read within ten seconds was gone. An
 * error nobody can see is the same as no error at all.
 *
 * So: viewport-anchored, and it stays until someone closes it. Only an action
 * the user took clears anything, and only its own entry.
 */
let notices = $state([]);
let nextNoticeId = 1;
/** Tool id -> the most recent install-progress event for it. */
let progress = $state({});

// The rows, and the single rule about when a finished one disappears, live
// in a runes-free module so `node --test` can execute them. This mirrors what
// that module decides into reactive state and does not decide anything itself.
const rows = createProgressRows();
rows.watch((next) => {
  progress = next;
});
let health = $state({});

export function library() {
  return view;
}

export function tools() {
  return view?.tools ?? [];
}

export function tool(id) {
  return tools().find((t) => t.id === id) ?? null;
}

export function settings() {
  return view?.settings ?? null;
}

export function status() {
  return { loading, checking };
}

export function allNotices() {
  return notices;
}

/**
 * Add a notice, or bring an existing identical one forward.
 *
 * The dedupe matters because the same failure arrives repeatedly: a backend
 * that has stopped answering would otherwise stack a copy of the same sentence
 * per tick of the hub's watch.
 */
export function notify(kind, text) {
  const message = String(text ?? '').trim();
  if (!message) return;
  const existing = notices.find((n) => n.text === message && n.kind === kind);
  if (existing) {
    existing.count += 1;
    existing.at = Date.now();
    return;
  }
  notices = [...notices, { id: nextNoticeId++, kind, text: message, at: Date.now(), count: 1 }];
}

export function dismissNotice(id) {
  notices = notices.filter((n) => n.id !== id);
}

export function dismissAllNotices() {
  notices = [];
}

export function progressFor(id) {
  return progress[id] ?? null;
}

export function healthFor(id) {
  return health[id] ?? null;
}

/** Everything with a newer release than the copy on disk. */
export function updates() {
  return tools().filter((t) => t.update_available);
}

/**
 * The hub's own newer release, or null.
 *
 * Decided in Rust like `update_available` is, and for the same reason: the
 * comparison against `latest.json` has one implementation, and every screen
 * that wants to mention it reads the same field.
 */
export function hubUpdate() {
  return view?.hub_update ?? null;
}

/**
 * Star or unstar a tool.
 *
 * The view comes back through `library-changed` like every other command that
 * changes what a screen shows, so nothing is re-read here and the card does not
 * keep its own copy of the flag.
 *
 * Except in the browser preview, which has no events to announce through -- the
 * one call site that pays for its own re-read, as the note on `act` says such a
 * call site should.
 */
export async function setFavorite(id, favorite) {
  const answer = await act('set_favorite', { id, favorite });
  if (!native) await refresh();
  return answer;
}

/** Downloads that finished but are waiting on the game or the tool to close. */
export function staged() {
  return tools().filter((t) => t.staged);
}

/**
 * The phases that end a progress stream.
 *
 * Exported, and the only copy, because a card counts itself busy until one of
 * these arrives: a phase missing from this list leaves that card's button
 * disabled for the rest of the session. There were three copies of it, and the
 * backend grew two terminal phases that none of them knew about.
 *
 * - `done`       installed, and the version is on the card.
 * - `failed`     nothing was installed; the button goes back to Try again.
 * - `staged`     downloaded and verified, waiting for a tool or the game to be
 *                closed. Not `done`: no version was installed.
 * - `downloaded` downloaded and nothing more was asked for (auto-download with
 *                auto-install off). Not `staged`: nothing is waiting.
 */
export const TERMINAL_PHASES = ['done', 'failed', 'staged', 'downloaded'];

export function isTerminal(phase) {
  return TERMINAL_PHASES.includes(phase);
}

/** Anything the hub is mid-way through fetching or writing. */
export function busy() {
  return Object.values(progress).filter((p) => p && !isTerminal(p.phase));
}

export async function refresh() {
  try {
    view = await invoke('library');
  } catch (e) {
    notify('error', e?.message ?? e);
  } finally {
    loading = false;
  }
}

export async function checkForUpdates() {
  checking = true;
  try {
    view = await invoke('check_for_updates');
  } catch (e) {
    notify('error', e?.message ?? e);
  }
  // Two requests to two places: the catalog for the ten tools, the release page
  // for the hub. Deliberately not one call -- a catalog that failed is no
  // reason to skip the hub's own release, and the reverse cost a release going
  // unnoticed entirely.
  try {
    await invoke('check_hub_update');
  } catch (e) {
    notify('error', e?.message ?? e);
  } finally {
    checking = false;
  }
}

/** The hub's own check: `{ checking, result: null|'current'|'available'|'failed', message }`. */
export function hubCheckState() {
  return hubCheckSnapshot;
}

/**
 * Check only the hub's own release.
 *
 * The backend announces the result on success, so the view updates through
 * `library-changed`; a failure has no view to announce, so `hubCheckState()`
 * is what a screen reads either way. No toast here: About shows the failure
 * next to the button it belongs to, and showing both would report the one
 * failure twice, the same reasoning as `awaitingInstall` above.
 */
export async function checkHubUpdate() {
  checking = true;
  try {
    return await hubCheck.check();
  } finally {
    checking = false;
  }
}

/**
 * Save the settings.
 *
 * No re-read afterwards: `set_settings` announces, so the new view is already
 * on its way through `library-changed`. Asking for it again cost a second view
 * build, and while a view build was a blocking 2.8 s that made one click on an
 * Appearance skin button freeze the window for the better part of six seconds.
 */
export async function saveSettings(next) {
  try {
    await invoke('set_settings', { settings: next });
  } catch (e) {
    notify('error', e?.message ?? e);
  }
}

/**
 * Run a command, and let the backend say what it changed.
 *
 * Nothing is re-read here. Announcing is the rule: every command that changes
 * what the library shows -- `set_settings`, `launch_tool`, `stop_tool`,
 * `uninstall_tool`, `rollback_tool`, and `install_tool` when its worker thread
 * finishes -- calls `announce`, which pushes a freshly built view through
 * `library-changed`. The rest (`verify_tool`, `open_path`, `open_url`) change
 * nothing a view could show.
 *
 * This used to refresh after everything but `install_tool`, which charged every
 * action for two view builds: the one the backend had already pushed, and the
 * one this asked for. A command that ever changes the view without announcing
 * should call `refresh()` at its own call site rather than putting the cost
 * back on all of them.
 */
/**
 * Installs this window is awaiting, by tool id.
 *
 * A failed install is now reported twice: the command rejects, and a terminal
 * `failed` event arrives on the progress stream. Both are wanted, but not for
 * the same install -- the stream's toast exists for the installs nobody
 * clicked, which have no promise to reject. So the stream stays quiet about one
 * a caller here is already awaiting and will report itself.
 */
const awaitingInstall = new Set();

export async function act(command, args) {
  const tracked = command === 'install_tool' && args?.id ? args.id : null;
  if (tracked) awaitingInstall.add(tracked);
  try {
    return await invoke(command, args);
  } catch (e) {
    notify('error', e?.message ?? e);
    throw e;
  } finally {
    if (tracked) awaitingInstall.delete(tracked);
  }
}



/** Subscribe to the backend's events. Called once, from App. */
export function connect() {
  const unsubscribes = [];
  listen('library-changed', (e) => {
    view = e.payload;
    loading = false;
  }).then((off) => unsubscribes.push(off));

  listen('install-progress', (e) => {
    const payload = e.payload;
    if (!payload?.id) return;
    // The row itself, and when it goes, are `progress-rows.js`.
    rows.receive(payload);
    if (payload.phase === 'failed' && !awaitingInstall.has(payload.id)) {
      // An install nobody clicked -- auto-install, or one staged earlier going
      // in at startup -- has no rejected promise anywhere for its failure to
      // surface through. One that *was* clicked does, and is reported there
      // instead; raising both put two differently worded toasts on screen for
      // a single failure.
      notify('error', `${payload.id}: ${payload.error}`);
    }
    if (payload.phase === 'staged') {
      // The click did not install anything, and the reason is not on the
      // Library screen the click came from. Saying so beats a card that simply
      // goes quiet.
      notify('info', `${payload.id}: ${payload.reason}`);
    }
  }).then((off) => unsubscribes.push(off));

  listen('tool-health', (e) => {
    const payload = e.payload;
    if (payload?.id) health = { ...health, [payload.id]: payload };
  }).then((off) => unsubscribes.push(off));

  refresh();
  return () => unsubscribes.forEach((off) => off?.());
}

/** "3m ago" for the status bar. */
export function ago(iso) {
  if (!iso) return 'never';
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function bytes(value) {
  if (!value && value !== 0) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
