// The one place that knows whether Tauri is underneath.
//
// `npm run dev` opens the frontend in a plain browser, where `invoke` does not
// exist. Rather than let every component guard for that, the bridge answers with
// the embedded catalog and an empty install set -- so the Library grid, the
// cards, the detail view and the settings screen can all be worked on without
// starting the Rust side at all. That is the "build the fast loop first" rule
// from AGENTS.md applied to this app's own development.

import { invoke as tauriInvoke } from '@tauri-apps/api/core';
import { listen as tauriListen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import fallbackCatalog from '../../catalog/catalog.json';

// Only for the browser preview. The desktop build gets this from Rust's
// HUB_REPO, which a release build overrides to whichever repository published
// it; the preview has no build-time value to read, so it assumes the canonical
// one and says so.
const PREVIEW_REPO = 'falorfrozen-cmd/hero-siege-offline-toolkit';

export const native = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

const DEFAULT_SETTINGS = {
  work_offline: false,
  check_on_launch: true,
  auto_download: false,
  auto_install: false,
  theme: 'obsidian',
  install_root: null,
  developer_mode: false,
  first_run_done: false,
};

let browserSettings = { ...DEFAULT_SETTINGS };
/** Starred tools, for as long as the preview tab is open. */
const browserFavorites = new Set();

/** The shape `library` returns, assembled from the catalog with nothing installed. */
function browserLibrary() {
  return {
    tools: fallbackCatalog.tools.map((tool) => ({
      ...tool,
      installed_version: null,
      installed_at: null,
      installed_sha256: null,
      install_path: null,
      can_roll_back: false,
      update_available: false,
      running_pid: null,
      running_elsewhere: false,
      staged: null,
      favorite: browserFavorites.has(tool.id),
      source_available: false,
      guide_url: tool.guide ? `https://github.com/${PREVIEW_REPO}/blob/main/${tool.guide}` : null,
    })),
    catalog_generated: fallbackCatalog.generated,
    catalog_source: 'embedded',
    catalog_trusted_comment: 'browser preview — no signature was checked',
    last_check: null,
    settings: browserSettings,
    game: { running: false, pid: null, exe_path: null, eac_running: false },
    hub_repo: PREVIEW_REPO,
    // The preview has no updater endpoint to ask, and an invented answer here
    // would put a banner on the Updates screen that can never be acted on.
    hub_update: null,
  };
}

const browserAnswers = {
  hub_info: () => ({
    version: '0.1.0 (browser preview)',
    install_root: '(not installed)',
    log_path: '(none)',
    repo_root: null,
    catalog_url: '(not fetched in the browser)',
    hub_repo: PREVIEW_REPO,
    elevated: false,
  }),
  library: browserLibrary,
  get_settings: () => browserSettings,
  set_settings: ({ settings }) => {
    browserSettings = { ...browserSettings, ...settings };
    return browserSettings;
  },
  set_favorite: ({ id, favorite }) => {
    if (favorite) browserFavorites.add(id);
    else browserFavorites.delete(id);
  },
  game_status: () => ({ running: false, pid: null, exe_path: null, eac_running: false }),
  report: () => {},
};

export async function invoke(command, args) {
  if (native) return tauriInvoke(command, args);
  const answer = browserAnswers[command];
  if (!answer) {
    // Anything that would touch the disk or the network. Saying so beats a
    // silent no-op that looks like a bug in the component.
    throw new Error(`"${command}" needs the desktop app; run \`npm start\`.`);
  }
  return answer(args ?? {});
}

export async function listen(event, handler) {
  if (native) return tauriListen(event, handler);
  return () => {};
}

export const chrome = {
  minimize: () => native && getCurrentWindow().minimize(),
  toggleMaximize: () => native && getCurrentWindow().toggleMaximize(),
  close: () => native && getCurrentWindow().close(),
  // `close` is a request the window may refuse; `destroy` is not. The bail-out
  // panel in main.js needs the second one -- a window with nothing drawn in it
  // has no other way out.
  destroy: () => (native ? getCurrentWindow().destroy() : Promise.resolve(window.close())),
};

/** Per-viewer scratch, for things it would be silly to round-trip to Rust for. */
export function recall(key, fallback = null) {
  try {
    const raw = localStorage.getItem(`hub:${key}`);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function remember(key, value) {
  try {
    localStorage.setItem(`hub:${key}`, JSON.stringify(value));
  } catch {
    // A private window, or site data turned off. Not worth a message.
  }
}
