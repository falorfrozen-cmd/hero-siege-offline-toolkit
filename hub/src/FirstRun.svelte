<script>
  // Before the hub contacts anything, it says what it would contact and lets the
  // answer be no.
  //
  // HS-Offline-Tracker's About panel states the toolkit's value plainly: the
  // update check is "never something the app does on its own... the only request
  // the app ever makes". A hub whose job is distribution cannot keep that
  // literally, but it can keep the part that matters — nothing happens before
  // this screen is answered, and Work offline is one click away on it.
  import { settings, saveSettings } from './library.svelte.js';
  import { art } from './skin.svelte.js';

  const current = $derived(settings());

  let checkOnLaunch = $state(false);
  let autoDownload = $state(false);

  function begin(workOffline) {
    saveSettings({
      ...current,
      work_offline: workOffline,
      check_on_launch: workOffline ? false : checkOnLaunch,
      auto_download: workOffline ? false : autoDownload,
      auto_install: false,
      first_run_done: true,
    });
  }
</script>

<main>
  <div class="panel skin skin-panel" style="--skin-src:url({art('panel')})">
    <img class="mark" src={art('app_mark')} alt="" />
    <h1>Hero Siege Toolkit</h1>
    <p class="lede">
      One window for the ten offline tools. It downloads them, checks every file
      against a SHA-256 pinned in a signed catalog, and keeps track of which
      version you have.
    </p>

    <h2>What it contacts, and nothing else</h2>
    <ul class="hosts">
      <li><code>github.com</code> — the signed catalog and the hub's own release, both on release tags</li>
      <li><code>objects.githubusercontent.com</code> — the release files themselves</li>
    </ul>
    <p class="fine">
      No analytics, no account, no telemetry. Your saves, settings and backups
      stay exactly where each tool puts them: the hub manages program files only,
      and never moves or deletes anything a tool wrote.
    </p>

    <div class="choices">
      <label>
        <input type="checkbox" bind:checked={checkOnLaunch} />
        <span>Check for updates when the hub starts <em>the catalog, and the hub's own release</em></span>
      </label>
      <label>
        <input type="checkbox" bind:checked={autoDownload} />
        <span>Download updates in the background <em>nothing is installed without asking</em></span>
      </label>
    </div>

    <div class="row">
      <button class="go skin skin-button" type="button" onclick={() => begin(false)} style="--skin-src:url({art('button')})">
        Start
      </button>
      <button class="offline" type="button" onclick={() => begin(true)}>
        Work offline instead
      </button>
    </div>
    <p class="fine centred">Either choice can be changed in Settings at any time.</p>
  </div>
</main>

<style>
  main { flex: 1; display: grid; place-items: center; padding: 22px; overflow: auto; }
  /* 17px of inset is already drawn by the sprite's own corner treatment, so
     the panel only pads the rest of the way in. */
  .panel { padding: 14px 18px; max-width: 620px; }
  .mark { width: 44px; height: 44px; }
  h1 { margin: 10px 0 6px; font-size: 21px; color: var(--bone-14); letter-spacing: 0.02em; }
  .lede { margin: 0 0 22px; font-size: 13px; line-height: 1.65; color: var(--bone-7); }
  h2 {
    margin: 0 0 8px;
    font-size: 11px;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--bone-3);
  }
  .hosts { margin: 0 0 10px; padding-left: 18px; font-size: 12.5px; color: var(--bone-8); line-height: 1.8; }
  code { font-family: ui-monospace, Consolas, monospace; color: var(--arcane); }
  .fine { margin: 0; font-size: 11.5px; line-height: 1.6; color: var(--bone-4); }
  .fine.centred { text-align: center; margin-top: 14px; }

  .choices { margin: 22px 0; display: grid; gap: 12px; }
  .choices label { display: flex; gap: 10px; align-items: flex-start; cursor: pointer; }
  .choices input { margin-top: 2px; width: 15px; height: 15px; accent-color: var(--gold-1); }
  .choices span { font-size: 12.5px; color: var(--bone-11); }
  .choices em { display: block; font-style: normal; font-size: 11.5px; color: var(--bone-4); margin-top: 2px; }

  .row { display: flex; gap: 10px; align-items: center; justify-content: center; }
  .go {
    color: var(--bone-13);
    font-size: 13px;
    letter-spacing: 0.04em;
    padding: 0 28px;
    min-height: 46px;
    cursor: pointer;
  }
  .offline {
    background: none;
    border: 1px solid var(--edge-3);
    border-radius: 9px;
    color: var(--bone-6);
    font-size: 12.5px;
    padding: 11px 20px;
    cursor: pointer;
  }
  .offline:hover { border-color: var(--edge-7); color: var(--bone-11); }
</style>
