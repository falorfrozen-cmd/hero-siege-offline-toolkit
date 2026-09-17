<script>
  import { onMount } from 'svelte';
  import { library, ago } from './library.svelte.js';
  import { invoke } from './bridge.js';
  let { onshow } = $props();
  let version = $state('');
  const view = $derived(library());
  const catalogNote = $derived(`Catalog ${ago(view?.catalog_generated)} · ${({ remote: 'downloaded', cache: 'cached', bundle: 'offline bundle', embedded: 'built in' })[view?.catalog_source] ?? ''}`);
  onMount(() => { invoke('hub_info').then((info) => { version = info.version; }).catch(() => {}); });
</script>
<footer>
  <button class="game" type="button" onclick={() => onshow?.('game')} title={view?.game.running ? `Hero Siege running · PID ${view.game.pid}` : 'Hero Siege is not running'}>
    <i class:lit={view?.game.running}></i>Hero Siege {view?.game.running ? 'running' : 'not running'}
  </button>
  <button type="button" class="eac" class:warn={view?.game.eac_running} onclick={() => onshow?.('game')}>EAC {view?.game.eac_running ? 'running' : 'not running'}</button>
  <button class="catalog" type="button" onclick={() => onshow?.('settings')}>{catalogNote}</button>
  <span class="grow"></span>
  {#if view?.settings.work_offline}<button type="button" class="offline" onclick={() => onshow?.('settings')}>Working offline</button>{/if}
  {#if version}<button class="version" type="button" onclick={() => onshow?.('about')}>v{version}</button>{/if}
</footer>
<style>
  footer { flex: 0 0 auto; display: flex; align-items: center; gap: 19px; min-height: 32px; padding: 6px 17px; border-top: 1px solid var(--edge-2); background: var(--ground-2); font-size: 10px; color: var(--bone-3); }
  button { background: none; border: 0; color: inherit; font: inherit; padding: 0; cursor: pointer; }
  button:hover { color: var(--bone-12); }
  .game { display: flex; gap: 7px; align-items: center; color: var(--bone-8); }
  i { width: 6px; height: 6px; border-radius: 50%; background: var(--bone-3); }
  i.lit { background: var(--success); }
  .warn { color: var(--rar-satanic); }
  .grow { flex: 1; }
  .offline { color: var(--gold-2); }
  .eac { border-left: 1px solid var(--edge-3); padding-left: 19px; }
  @media (max-width: 1000px) { .catalog { display: none; } }
  @media (max-width: 700px) { footer { gap: 10px; font-size: 9px; } .eac { border: 0; padding: 0; } }
</style>