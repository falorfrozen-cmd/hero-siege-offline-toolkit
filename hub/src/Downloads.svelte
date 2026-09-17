<script>
  // Every file in flight, with Verifying as a step of its own. The hash check is
  // the reason any of this can be trusted, and a progress bar that hides it
  // implies it did not happen.
  import { busy, bytes, tool as findTool } from './library.svelte.js';

  let { onclose } = $props();

  const rows = $derived(busy());

  const phaseLabel = {
    started: 'Starting',
    downloading: 'Downloading',
    verifying: 'Verifying SHA-256',
    extracting: 'Extracting',
    activating: 'Making it live',
  };
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') onclose?.(); }}/>
<aside aria-label="Downloads">
  <header>
    <h3>Downloads</h3>
    <button type="button" onclick={onclose} aria-label="Close">×</button>
  </header>

  {#if rows.length === 0}
    <p class="empty">Nothing in flight.</p>
  {:else}
    <ul>
      {#each rows as row (row.id)}
        <li>
          <b>{findTool(row.id)?.name ?? row.id}</b>
          <span class="phase">{phaseLabel[row.phase] ?? row.phase}</span>
          {#if row.phase === 'downloading' && row.total}
            <div class="bar"><span style="width:{(row.received / row.total) * 100}%"></span></div>
            <span class="counted">{bytes(row.received)} of {bytes(row.total)}</span>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</aside>

<style>
  aside {
    position: absolute; right: 0; top: 0; bottom: 0; z-index: 25;
    width: min(320px, 100%); box-shadow: -12px 0 30px #0005;
    flex: 0 0 auto;
    border-left: 1px solid var(--edge-2);
    background: var(--ground-3);
    padding: 14px;
    overflow: auto;
  }
  header { display: flex; align-items: center; justify-content: space-between; }
  h3 {
    margin: 0;
    font-size: 11px;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--bone-3);
  }
  header button {
    background: none;
    border: none;
    color: var(--bone-5);
    font-size: 17px;
    line-height: 1;
    cursor: pointer;
  }
  .empty { margin-top: 14px; font-size: 11.5px; color: var(--bone-4); }
  ul { margin: 14px 0 0; padding: 0; list-style: none; display: grid; gap: 15px; }
  li { display: grid; gap: 4px; }
  b { font-size: 12px; color: var(--bone-11); font-weight: 600; }
  .phase { font-size: 11px; color: var(--arcane); }
  .bar { height: 4px; border-radius: 999px; background: var(--ground-8); overflow: hidden; }
  .bar span {
    display: block;
    height: 100%;
    background: linear-gradient(90deg, var(--arcane), var(--gold-1));
    transition: width 140ms linear;
  }
  .counted { font-size: 10.5px; color: var(--bone-4); }
</style>
