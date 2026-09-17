<script>
  // Everything about one tool that does not fit on a card: what the release
  // said, what it needs, where it is on disk, and exactly which bytes were
  // verified.
  import { art } from './skin.svelte.js';
  import ToolIcon from './ToolIcon.svelte';
  import ToolAction from './ToolAction.svelte';
  import { identity } from './tool-presentation.js';
  import { tool as findTool, act, bytes } from './library.svelte.js';

  let { id, action = null, onback } = $props();

  let report = $state(null);
  let verifying = $state(false);

  const tool = $derived(findTool(id));

  async function verify() {
    verifying = true;
    report = null;
    try {
      report = await act('verify_tool', { id });
    } finally {
      verifying = false;
    }
  }

  // The overflow menu can open this view straight into a verification.
  $effect(() => {
    if (action === 'verify' && tool?.installed_version && !report && !verifying) verify();
  });

  const requirements = $derived.by(() => {
    if (!tool) return [];
    const list = [];
    if (tool.requires.admin) {
      list.push(['Administrator', 'Windows asks for elevation each time this runs. The hub itself stays unelevated.']);
    }
    if (tool.requires.game_closed) {
      list.push(['Close the game first', 'This writes to save files, and the game holds them while it runs.']);
    }
    if (tool.requires.game_running) {
      list.push(['Hero Siege must be running', 'This attaches to the running game to read and write its memory.']);
    }
    if (tool.requires.windows_only) list.push(['Windows only', '']);
    return list;
  });
</script>

{#if !tool}
  <p class="empty">That tool is not in the catalog.</p>
{:else}
  <button class="back" type="button" onclick={onback}>← Library</button>

  <header>
    <ToolIcon name={identity(tool).icon} size={68}/>
    <div>
      <h2>{tool.name}</h2>
      <p class="sub">{tool.summary}</p>
    </div>
    <span class="version">v{tool.version}</span>
    <ToolAction {tool}/>
  </header>

  {#if requirements.length}
    <ul class="requirements">
      {#each requirements as [label, why] (label)}
        <li>
          <img src={art('shield_gold')} alt="" />
          <div>
            <b>{label}</b>
            {#if why}<span>{why}</span>{/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}

  <section class="facts skin skin-chip" style="--skin-src:url({art('chip_dark')})">
    <dl>
      <div><dt>Installed</dt><dd>{tool.installed_version ? `v${tool.installed_version}` : 'no'}</dd></div>
      {#if tool.installed_at}
        <div><dt>Installed on</dt><dd>{tool.installed_at.replace('T', ' ').replace('Z', ' UTC')}</dd></div>
      {/if}
      <div><dt>Licence</dt><dd>{tool.license === 'NOASSERTION' ? 'none declared' : tool.license}</dd></div>
      <div><dt>Download</dt><dd>{tool.artifact.name} · {bytes(tool.artifact.size)}</dd></div>
      <div><dt>Published</dt><dd>{(tool.published || '').slice(0, 10) || 'unknown'}</dd></div>
      {#if tool.install_path}
        <div class="wide"><dt>Install path</dt><dd><code>{tool.install_path}</code></dd></div>
      {/if}
      <div class="wide">
        <dt>Pinned SHA-256</dt>
        <dd><code class="hash">{tool.artifact.sha256}</code></dd>
      </div>
      {#if tool.installed_sha256 && tool.installed_sha256 !== tool.artifact.sha256}
        <div class="wide">
          <!-- Not an error: the installed copy predates the catalog's current
               release. Saying so beats showing one hash and implying it is both. -->
          <dt>Installed from</dt>
          <dd><code class="hash">{tool.installed_sha256}</code></dd>
        </div>
      {/if}
    </dl>
  </section>

  <div class="row">
    {#if tool.installed_version}
      <button type="button" onclick={verify} disabled={verifying}>
        {verifying ? 'Checking…' : 'Verify files'}
      </button>
      <button type="button" onclick={() => act('open_path', { path: tool.install_path })}>Open folder</button>
    {/if}
    {#if tool.can_roll_back}
      <button type="button" onclick={() => act('rollback_tool', { id })}>Roll back</button>
    {/if}
    <button type="button" onclick={() => act('open_url', { url: tool.notes_url })}>Release page</button>
  </div>

  {#if report}
    <p class="report" class:bad={!report.ok}>
      {report.ok ? '✔' : '✕'} {report.message}
      {#if report.changed.length}<br />changed: {report.changed.join(', ')}{/if}
      {#if report.missing.length}<br />missing: {report.missing.join(', ')}{/if}
    </p>
  {/if}

  {#if tool.staged}
    <section class="staged">
      <b>v{tool.staged.version} is downloaded and waiting.</b>
      <span>{tool.staged.blocked_by}</span>
    </section>
  {/if}

  {#if tool.notes}
    <section class="notes">
      <h3>What changed in v{tool.version}</h3>
      <pre>{tool.notes}</pre>
    </section>
  {/if}
{/if}

<style>
  .back {
    background: none;
    border: none;
    color: var(--bone-5);
    font-size: 12px;
    padding: 0 0 12px;
    cursor: pointer;
  }
  .back:hover { color: var(--bone-10); }

  header { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
  header > div { flex: 1; min-width: 180px; }
  h2 { margin: 0; font-size: 19px; color: var(--bone-14); }
  .sub { margin: 4px 0 0; font-size: 12.5px; color: var(--bone-5); }
  .version { font-size: 13px; color: var(--gold-2); }

  .requirements { list-style: none; margin: 16px 0 0; padding: 0; display: grid; gap: 8px; }
  .requirements li { display: flex; gap: 10px; align-items: flex-start; font-size: 12px; }
  .requirements img { width: 18px; height: 18px; flex: 0 0 auto; margin-top: 1px; }
  .requirements b { display: block; color: var(--gold-2); font-weight: 600; }
  .requirements span { color: var(--bone-5); }

  .facts { margin: 18px 0 14px; padding: 4px 6px; }
  dl { margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px 20px; }
  dl > div.wide { grid-column: 1 / -1; }
  dt { font-size: 10.5px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--bone-3); }
  dd { margin: 3px 0 0; font-size: 12.5px; color: var(--bone-11); }
  code { font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: var(--bone-9); }
  .hash { word-break: break-all; color: var(--arcane); }

  .row { display: flex; flex-wrap: wrap; gap: 8px; }
  .row button {
    background: var(--ground-7);
    border: 1px solid var(--edge-3);
    border-radius: 9px;
    color: var(--bone-10);
    font-size: 12px;
    padding: 7px 14px;
    cursor: pointer;
  }
  .row button:hover:not(:disabled) { border-color: var(--edge-7); color: var(--bone-14); }
  .row button:disabled { opacity: 0.55; cursor: default; }

  .report {
    margin: 12px 0 0;
    font-size: 12px;
    color: var(--arcane);
    line-height: 1.6;
  }
  .report.bad { color: var(--rar-satanic); }

  .staged {
    margin-top: 16px;
    padding: 11px 14px;
    border-radius: 10px;
    border: 1px dashed var(--edge-2b);
    font-size: 12.5px;
    display: grid;
    gap: 3px;
  }
  .staged b { color: var(--rar-angelic); font-weight: 600; }
  .staged span { color: var(--bone-5); }

  .notes { margin-top: 22px; }
  .notes h3 { margin: 0 0 8px; font-size: 13px; color: var(--bone-11); }
  .notes pre {
    margin: 0;
    padding: 13px 15px;
    border-radius: 10px;
    background: var(--ground-3);
    border: 1px solid var(--edge-2);
    font-size: 11.5px;
    line-height: 1.6;
    color: var(--bone-8);
    white-space: pre-wrap;
    max-height: 340px;
    overflow: auto;
  }
  .empty { color: var(--bone-4); }
</style>
