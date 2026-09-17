<script>
  import { tools, checkForUpdates, status, library, ago } from './library.svelte.js';
  import { recall, remember } from './bridge.js';
  import { selectTools, quickTools, categories } from './tool-presentation.js';
  import ToolCard from './ToolCard.svelte';
  import Icon from './Icon.svelte';
  let { onopen } = $props();
  let query = $state('');
  let category = $state('all');
  let availability = $state('all');
  let layout = $state(recall('library-layout') === 'list' ? 'list' : 'grid');
  let searchInput;
  const shown = $derived(selectTools(tools(), { query, category, availability }));
  const quick = $derived(quickTools(shown));
  const filtering = $derived(!!query.trim() || category !== 'all' || availability !== 'all');
  function setLayout(value) { layout = value; remember('library-layout', value); }
  function clear() { query = ''; category = 'all'; availability = 'all'; searchInput?.focus(); }
  function shortcut(e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); searchInput?.focus(); }
  }
</script>

<svelte:window onkeydown={shortcut}/>
<header class="head">
  <div><h1>Library</h1><p class="sub">Your offline workshop</p></div>
  <div class="head-actions">
    <div class="search">
      <Icon name="search" size={17}/>
      <input bind:this={searchInput} bind:value={query} type="search" placeholder="Search tools…" aria-label="Search tools" onkeydown={(e) => { if (e.key === 'Escape') query = ''; }}/>
      <kbd>Ctrl K</kbd>
    </div>
    <button class="check hub-button" type="button" disabled={status().checking} onclick={checkForUpdates}
      aria-label="Check for updates" title={status().checking ? 'Checking for updates…' : 'Check for updates'}>
      <span class:checking={status().checking}><Icon name="updates" size={19}/></span>
    </button>
  </div>
</header>

{#if quick.length}
  <section class="quick-section" aria-label="Quick launch">
    <div class="section-label"><h2>Quick launch</h2><span>{quick.some((t) => t.favorite) ? 'Your starred tools' : 'Ready when you are · Star a tool to pin it'}</span></div>
    <div class="grid" class:rows={layout === 'list'}>
      {#each quick as tool (tool.id)}<ToolCard {tool} {onopen} list={layout === 'list'}/>{/each}
    </div>
  </section>
{/if}

<div class="toolbar">
  <div class="library-label"><h2>All tools</h2><span class="total" aria-live="polite">{shown.length}{#if filtering}<span class="of"> / {tools().length}</span>{/if}</span></div>
  <div class="filters" role="group" aria-label="Tool category">
    {#each categories as [id, label]}
      <button type="button" class:on={category === id} aria-pressed={category === id} onclick={() => (category = id)}>{label}</button>
    {/each}
  </div>
  <div class="view-options">
    <label><span class="sr-only">Installation status</span>
      <select bind:value={availability} aria-label="Installation status">
        <option value="all">Any status</option><option value="installed">Installed</option>
        <option value="updates">Updates</option><option value="available">Not installed</option>
      </select>
    </label>
    <div class="views" role="group" aria-label="Library layout">
      <button type="button" class:on={layout === 'grid'} aria-pressed={layout === 'grid'} aria-label="Grid view" title="Grid view" onclick={() => setLayout('grid')}><Icon name="library" size={15}/></button>
      <button type="button" class:on={layout === 'list'} aria-pressed={layout === 'list'} aria-label="List view" title="List view" onclick={() => setLayout('list')}><Icon name="list" size={17}/></button>
    </div>
  </div>
</div>
{#if shown.length === 0}
  <div class="empty"><Icon name="search" size={30}/><h3>No tools found</h3><p>Try another name, category or installation status.</p><button class="hub-button" type="button" onclick={clear}>Clear filters</button></div>
{:else}
  <div class="grid" class:rows={layout === 'list'} role="group" aria-label="All tools">
    {#each shown as tool (tool.id)}<ToolCard {tool} {onopen} list={layout === 'list'}/>{/each}
  </div>
{/if}
<p class="catalog-note">Catalog updated {ago(library()?.catalog_generated)} <span>·</span> {tools().length} tools in your workshop</p>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
  h1 { margin: 0; font-size: clamp(27px, 2.7vw, 38px); line-height: 1.15; letter-spacing: -.035em; color: var(--bone-14); font-weight: 700; }
  .sub { margin: 6px 0 0; font-size: 13px; color: var(--bone-5); }
  .head-actions { display: flex; align-items: center; gap: 10px; }
  .search { display: flex; align-items: center; gap: 10px; background: var(--ground-4); border: 1px solid var(--edge-3); border-radius: 8px; padding: 0 12px; color: var(--bone-5); height: 39px; width: clamp(205px, 27vw, 360px); }
  .search:focus-within { border-color: var(--accent); }
  .search input { background: none; border: 0; outline: 0; width: 100%; min-width: 0; color: var(--bone-13); font-size: 12px; }
  .search input::placeholder { color: var(--bone-3); }
  kbd { font-size: 9px; white-space: nowrap; padding: 2px 4px; border: 1px solid var(--edge-3); border-radius: 3px; color: var(--bone-3); }
  .check { width: 39px; height: 39px; padding: 0; background: transparent; color: var(--bone-6); }
  .check span { display: flex; }
  .checking { animation: spin 1.5s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .quick-section { margin-bottom: 22px; }
  .section-label { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
  .section-label h2 { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .18em; color: var(--bone-7); margin: 0; }
  .section-label > span { font-size: 10px; color: var(--bone-3); }
  .toolbar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
  .library-label { display: flex; align-items: center; gap: 9px; }
  .library-label h2 { font-size: 17px; font-weight: 600; margin: 0; white-space: nowrap; }
  .total { background: var(--ground-7); border-radius: 6px; padding: 3px 7px; font-size: 11px; color: var(--bone-9); white-space: nowrap; }
  .of { color: var(--bone-3); }
  .filters { display: flex; gap: 5px; flex-wrap: wrap; }
  .filters button { color: var(--bone-5); background: transparent; border: 1px solid transparent; padding: 7px 10px; font-size: 11px; border-radius: 6px; cursor: pointer; }
  .filters button:hover { background: var(--ground-6); color: var(--bone-12); }
  .filters button.on { color: var(--gold-2); background: var(--accent-soft); border-color: var(--edge-7); }
  .view-options { display: flex; gap: 8px; align-items: center; margin-left: auto; }
  select { color: var(--bone-5); background: var(--ground-3); border: 1px solid var(--edge-2); border-radius: 6px; padding: 6px 7px; font-size: 11px; max-width: 130px; }
  .views { display: flex; border: 1px solid var(--edge-3); border-radius: 6px; overflow: visible; }
  .views button { display: grid; place-items: center; width: 31px; height: 29px; padding: 0; border: 0; background: transparent; color: var(--bone-3); border-radius: 5px; cursor: pointer; }
  .views button.on { color: var(--accent); background: var(--ground-7); }
  .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  .grid.rows { grid-template-columns: 1fr; gap: 8px; }
  .empty { display: flex; flex-direction: column; align-items: center; padding: 50px 20px; border: 1px dashed var(--edge-3); border-radius: 10px; color: var(--bone-4); text-align: center; }
  .empty h3 { color: var(--bone-12); margin: 14px 0 0; font-size: 17px; }
  .empty p { font-size: 12px; margin-bottom: 20px; }
  .catalog-note { color: var(--bone-3); font-size: 10px; margin: 20px 0 0; }
  .catalog-note span { margin: 0 5px; }
  @media (max-width: 1190px) {
    .toolbar { gap: 10px; } .filters button { padding: 7px 8px; }
  }
  @media (max-width: 1040px) {
    .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 700px) {
    .head { flex-direction: column; align-items: stretch; gap: 15px; }
    .head-actions, .search { width: 100%; } .search { flex: 1; }
    .grid { grid-template-columns: 1fr; }
    .section-label > span { display: none; } .view-options { margin-left: 0; }
  }
</style>
