<script>
  import { onMount } from 'svelte';
  import { invoke } from './bridge.js';
  import { library, act, ago, hubUpdate, checkHubUpdate, hubCheckState, status } from './library.svelte.js';
  import { hubInstall, installHubUpdate, clearHubInstall } from './hub-update.svelte.js';
  import { art } from './skin.svelte.js';

  /**
   * The toolkit's Discord.
   *
   * Opened through `open_url`, which hands it to the system browser and refuses
   * anything that is not http(s) -- the hub never navigates its own webview
   * somewhere else, and an invite is not a reason to start.
   *
   * This must be a **never-expiring** invite. A hub release is a thing people
   * keep for months, so an invite with a `max_age` is a dead link with a
   * release date on it.
   */
  const DISCORD_URL = 'https://discord.gg/ZZRCjSN4kr';

  let discordHovered = $state(false);

  let info = $state(null);

  const view = $derived(library());
  const update = $derived(hubUpdate());
  const install = $derived(hubInstall());
  const checkState = $derived(hubCheckState());

  onMount(() => {
    invoke('hub_info').then((i) => (info = i)).catch(() => {});
  });

  /**
   * The check itself lives in Rust, where the launch check runs it too — one
   * implementation, and `work_offline` enforced in the place a hand-edited
   * settings file cannot get past. A rejection is not caught here: it comes
   * back through `hubCheckState()` as `result: 'failed'` instead, so a failed
   * check can never render as "This is the newest release" the way it did
   * before issue #44.
   */
  async function check() {
    clearHubInstall();
    await checkHubUpdate();
  }
</script>

<h2>About</h2>

<section class="facts">
  <dl>
    <div><dt>Hub version</dt><dd>{info?.version ?? '…'}</dd></div>
    <div><dt>Catalog</dt><dd>{view?.catalog_generated ?? '…'} ({view?.catalog_source})</dd></div>
    <div><dt>Last checked</dt><dd>{ago(view?.last_check)}</dd></div>
    <div class="wide"><dt>Signed as</dt><dd><code>{view?.catalog_trusted_comment}</code></dd></div>
    <div class="wide"><dt>Install root</dt><dd><code>{info?.install_root}</code></dd></div>
    <div class="wide"><dt>Log</dt><dd><code>{info?.log_path}</code></dd></div>
  </dl>
  {#if info?.log_path}
    <button type="button" onclick={() => act('open_path', { path: info.log_path })}>Open the log</button>
  {/if}
</section>

<section>
  <h3>Updating the hub itself</h3>
  <p>
    The tools update from the catalog. The hub updates from its own signed
    release — checked on launch along with the catalog, and never installed
    without you saying so.
  </p>
  <div class="row">
    <button type="button" onclick={check} disabled={status().checking}>
      {status().checking ? 'Checking…' : 'Check for a hub update'}
    </button>
    {#if update}
      <button type="button" onclick={installHubUpdate} disabled={install.phase === 'downloading'}>
        {install.phase === 'downloading' ? 'Downloading…' : `Download and install v${update.version}`}
      </button>
    {/if}
  </div>
  {#if update}
    <p class="result">v{update.version} is available. You are on v{update.current_version}.</p>
  {:else if checkState.result === 'current'}
    <p class="result">{checkState.message}</p>
  {/if}
  {#if checkState.result === 'failed'}
    <p class="result bad">{checkState.message}</p>
  {/if}
  {#if install.message}
    <p class="result" class:bad={install.phase === 'error'}>{install.message}</p>
  {/if}
</section>

<section>
  <h3>Community</h3>
  <p>
    The toolkit's Discord is where releases get announced, bugs get reported and
    the people who use these tools can be asked what they did about the thing
    you are stuck on. Opens in your browser; the hub does not sign you in to
    anything.
  </p>
  <button
    class="discord"
    type="button"
    onmouseenter={() => (discordHovered = true)}
    onmouseleave={() => (discordHovered = false)}
    onclick={() => act('open_url', { url: DISCORD_URL })}
  >
    <img src={art(discordHovered ? 'discord_hover' : 'discord')} alt="" />
    Join the Discord
  </button>
</section>

<section>
  <h3>What this is</h3>
  <p>
    The Hero Siege Offline Toolkit is ten separate projects. This hub does not
    replace any of them or change how they work — it installs them, starts them,
    and tells you when one has a new release. Each tool keeps its own settings,
    saves and backups exactly where it has always kept them, and behaves the same
    started from here or started by hand.
  </p>
  <p>
    None of the tools is code-signed, so Windows SmartScreen will warn about
    them. What the hub offers instead is a SHA-256 for every artifact, pinned in
    a catalog signed with a key built into this application: an artifact that has
    been swapped since the catalog was made fails to install rather than
    installing quietly.
  </p>
</section>

<style>
  h2 { margin: 0 0 18px; font-size: 18px; color: var(--bone-14); }
  section { max-width: 74ch; margin-bottom: 26px; }
  h3 {
    margin: 0 0 10px;
    font-size: 11px;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--bone-3);
  }
  p { margin: 0 0 12px; font-size: 12.5px; line-height: 1.65; color: var(--bone-6); }

  .facts { padding: 15px 17px; border: 1px solid var(--edge-2); border-radius: 12px; background: var(--ground-4); }
  dl { margin: 0 0 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px 20px; }
  dl > div.wide { grid-column: 1 / -1; }
  dt { font-size: 10.5px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--bone-3); }
  dd { margin: 3px 0 0; font-size: 12.5px; color: var(--bone-11); }
  code { font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: var(--arcane); word-break: break-all; }

  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  button {
    background: var(--ground-7);
    border: 1px solid var(--edge-3);
    border-radius: 9px;
    color: var(--bone-10);
    font-size: 12px;
    padding: 7px 14px;
    cursor: pointer;
  }
  button:hover:not(:disabled) { border-color: var(--edge-7); color: var(--bone-14); }
  button:disabled { opacity: 0.6; cursor: default; }
  .discord {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border-color: color-mix(in srgb, var(--arcane) 45%, var(--edge-3));
  }
  .discord img { width: 16px; height: 16px; }

  .result { margin-top: 10px; font-size: 12px; color: var(--arcane); }
  .result.bad { color: var(--rar-satanic); }
</style>
