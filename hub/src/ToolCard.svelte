<script>
  import { tick } from 'svelte';
  import { act, progressFor, bytes, setFavorite, pendingFor } from './library.svelte.js';
  import { identity, presentation } from './tool-presentation.js';
  import ToolIcon from './ToolIcon.svelte';
  import ToolAction from './ToolAction.svelte';
  import Icon from './Icon.svelte';
  let { tool, onopen, list = false } = $props();
  let menuOpen = $state(false);
  let menuPosition = $state({ left: 0, top: 0 });
  let starWorking = $state(false);
  let menuAnchor;
  let menuButton;
  let menuPanel = $state();
  const meta = $derived(identity(tool));
  const progress = $derived(progressFor(tool.id));
  const state = $derived(presentation(tool, progress));
  const pending = $derived(pendingFor(tool.id));
  const requirements = $derived([
    tool.requires.admin ? 'Requires Administrator' : '',
    tool.requires.game_closed ? 'Requires game closed' : '',
    tool.requires.game_running ? 'Requires game running' : '',
  ].filter(Boolean));
  async function toggleStar() {
    if (starWorking) return;
    starWorking = true;
    try { await setFavorite(tool.id, !tool.favorite); } catch { /* shared toast */ }
    finally { starWorking = false; }
  }
  async function toggleMenu() {
    menuOpen = !menuOpen;
    if (menuOpen) {
      const button = menuButton.getBoundingClientRect();
      menuPosition = { left: Math.max(8, button.right - 190), top: button.bottom + 5 };
      await tick();
      if (!menuOpen || !menuPanel) return;
      const height = menuPanel.getBoundingClientRect().height;
      menuPosition = { left: Math.min(menuPosition.left, innerWidth - 198),
        top: button.bottom + height + 12 > innerHeight ? Math.max(8, button.top - height - 5) : button.bottom + 5 };
      menuPanel.querySelector('button')?.focus({ preventScroll: true });
    }
  }
  function closeMenu(restore = false) {
    menuOpen = false;
    if (restore) menuButton?.focus();
  }
  function menuKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const buttons = [...menuPanel.querySelectorAll('button:not(:disabled)')];
      const index = buttons.indexOf(document.activeElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    }
  }
  async function overflow(command, args = {}) {
    closeMenu(true);
    try { await act(command, { id: tool.id, ...args }); } catch { /* shared toast */ }
  }
  function details(action = null) { closeMenu(); onopen?.(tool.id, action); }
</script>

<svelte:window onclick={(e) => { if (menuOpen && !menuAnchor?.contains(e.target)) closeMenu(); }}
  onkeydown={(e) => { if (menuOpen && e.key === 'Escape') closeMenu(true); }} onresize={() => closeMenu()} />

<article class="card" class:list class:starred={tool.favorite} data-tool-id={tool.id}>
  <div class="corner">
    <button class="glyph star" type="button" aria-pressed={tool.favorite} disabled={starWorking}
      aria-label={tool.favorite ? `Unstar ${tool.name}` : `Star ${tool.name}`}
      title={tool.favorite ? 'Remove from quick launch' : 'Add to quick launch'} onclick={toggleStar}>
      <Icon name="star" size={15}/>
    </button>
    <div class="menu-anchor" bind:this={menuAnchor}
      onfocusout={(e) => { if (!menuAnchor?.contains(e.relatedTarget)) closeMenu(); }}>
      <button class="glyph" type="button" bind:this={menuButton}
        aria-label="More actions for {tool.name}" aria-expanded={menuOpen} aria-haspopup="menu"
        onclick={toggleMenu}><Icon name="more" size={18}/></button>
      {#if menuOpen}
        <div class="menu" role="menu" aria-label="Actions for {tool.name}" tabindex="-1" bind:this={menuPanel} onkeydown={menuKey} style="left:{menuPosition.left}px;top:{menuPosition.top}px">
          <button role="menuitem" onclick={() => details()}>Tool details</button>
          <button role="menuitem" onclick={() => overflow('open_url', { url: tool.notes_url })}>Release notes</button>
          {#if tool.guide_url}<button role="menuitem" onclick={() => overflow('open_url', { url: tool.guide_url })}>Developer guide</button>{/if}
          {#if tool.install_path}
            <button role="menuitem" onclick={() => overflow('open_path', { path: tool.install_path })}>Open folder</button>
            <button role="menuitem" onclick={() => details('verify')}>Verify files</button>
          {/if}
          {#if tool.can_roll_back}<button role="menuitem" disabled={pending} onclick={() => overflow('rollback_tool')}>Roll back</button>{/if}
          {#if tool.source_available}<button role="menuitem" disabled={pending} onclick={() => overflow('launch_tool', { fromSource: true })}>Run from source</button>{/if}
          {#if tool.installed_version}<button role="menuitem" class="danger" disabled={pending} onclick={() => overflow('uninstall_tool')}>Uninstall</button>{/if}
        </div>
      {/if}
    </div>
  </div>
  <button class="body" type="button" onclick={() => details()} aria-label="Details for {tool.name}">
    <ToolIcon name={meta.icon} size={52}/>
    <span class="copy">
      <strong title={tool.name}>{meta.title}</strong>
      <span class="summary" title={tool.summary}>{meta.summary}</span>
    </span>
  </button>
  {#if requirements.length}
    <p class="requirements" title={requirements.join(' · ')}>{requirements.join(' · ')}</p>
  {/if}
  <footer>
    <span class="status {state.chip.tone}" title={state.installed ? `Installed v${state.installed}${tool.update_available ? ' · Latest v' + tool.version : ''}` : state.chip.text}>
      <i aria-hidden="true"></i><span class="status-label">{state.chip.text}</span>
      <small class="version">{state.installed ? `v${state.installed}` : ''}</small>
    </span>
    <ToolAction {tool} compact={list}/>
  </footer>
  {#if state.inFlight}
    <div class="progress">
      {#if progress?.phase === 'downloading' && progress.total}
        <progress max={progress.total} value={Math.min(progress.received, progress.total)} aria-label="Downloading {tool.name}"></progress>
        <span>{bytes(progress.received)} / {bytes(progress.total)}</span>
      {:else}<span>{state.chip.text}{progress?.phase === 'verifying' ? ' · Checking SHA-256' : '…'}</span>{/if}
    </div>
  {/if}
</article>

<style>
  .card { position: relative; min-width: 0; display: flex; flex-direction: column; padding: 14px; border: 1px solid var(--edge-2); background: linear-gradient(125deg, var(--surface), var(--ground-4)); border-radius: 10px; transition: border-color 150ms; }
  .card:hover, .card:focus-within { border-color: var(--edge-4); }
  .corner { position: absolute; right: 9px; top: 9px; display: flex; gap: 1px; }
  .glyph { display: grid; place-items: center; width: 26px; height: 26px; border: none; background: transparent; color: var(--bone-4); border-radius: 5px; cursor: pointer; }
  .glyph:hover, .glyph[aria-expanded='true'] { background: var(--ground-8); color: var(--bone-14); }
  .starred .star { color: var(--accent); }
  .starred .star :global(svg) { fill: var(--accent-soft); }
  .body { display: flex; align-items: center; gap: 13px; min-width: 0; flex: 1; padding: 12px 0 0; margin: 0; background: none; border: 0; text-align: left; color: inherit; cursor: pointer; border-radius: 5px; }
  .copy { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  strong { color: var(--bone-13); font-size: 14px; font-weight: 600; line-height: 1.35; }
  .summary { font-size: 11.5px; color: var(--bone-5); line-height: 1.5; }
  .requirements { font-size: 10px; line-height: 1.4; color: var(--bone-3); margin: 9px 0 0; }
  footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 11px; }
  .status { display: grid; grid-template-columns: 7px minmax(0, 1fr); column-gap: 7px; row-gap: 3px; color: var(--bone-5); font-size: 11px; line-height: 1.3; min-width: 0; }
  .status i { grid-column: 1; grid-row: 1; align-self: start; margin-top: calc((1.3em - 7px) / 2); width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .status-label { grid-column: 2; grid-row: 1; }
  /* Reserve the version line even when absent, so status labels never jump. */
  .status .version { grid-column: 2; grid-row: 2; min-height: 1.3em; font-size: 9.5px; line-height: 1.3; color: var(--bone-3); }
  .status.running { color: var(--success); }
  .status.update, .status.staged { color: var(--gold-2); }
  .status.failed { color: var(--rar-satanic); }
  .status.busy { color: var(--arcane); }
  .progress { margin-top: 10px; font-size: 10px; color: var(--bone-5); }
  progress { width: 100%; height: 4px; display: block; margin-bottom: 4px; accent-color: var(--accent); }
  .menu-anchor { position: relative; }
  .menu { position: fixed; width: 190px; max-height: calc(100dvh - 16px); overflow-y: auto; padding: 5px; z-index: 20; background: var(--ground-7); border: 1px solid var(--edge-4); box-shadow: 0 12px 30px #0008; border-radius: 8px; }
  .menu button { display: block; width: 100%; text-align: left; border: 0; background: none; color: var(--bone-10); padding: 8px 10px; border-radius: 4px; font-size: 12px; cursor: pointer; }
  .menu button:hover, .menu button:focus-visible { background: var(--ground-9); color: var(--bone-14); }
  .menu button:disabled { opacity: .5; }
  .menu .danger { color: var(--rar-satanic); }
  .list { display: grid; grid-template-columns: minmax(190px, 1fr) minmax(240px, .7fr); gap: 0 24px; padding: 12px 76px 12px 16px; }
  .list .body { padding: 0; grid-row: span 2; }
  .list .body :global(svg) { width: 45px; height: 45px; }
  .list .corner { top: calc(50% - 13px); }
  .list footer { margin: 0; }
  .list .requirements { grid-column: 2; grid-row: 2; margin-top: 5px; }
  .list .progress { grid-column: 1 / -1; }
  @media (max-width: 700px) { .list { display: flex; padding: 16px; } .list .corner { top: 8px; } .list footer { margin-top: 12px; } }
</style>
