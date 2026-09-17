<script>
  import { chrome } from './bridge.js';
  import Icon from './Icon.svelte';
</script>
<header data-tauri-drag-region>
  <span class="title" data-tauri-drag-region>Hero Siege Toolkit <span class="divider">/</span> Offline workshop</span>
  <span class="spacer" data-tauri-drag-region></span>
  <nav aria-label="Window controls">
    {#each [['minimize', 'Minimise', chrome.minimize], ['maximize', 'Maximise', chrome.toggleMaximize], ['close', 'Close', chrome.close]] as [name, label, action] (name)}
      <button type="button" aria-label={label} title={label} class:close={name === 'close'} onclick={action}><Icon {name} size={13}/></button>
    {/each}
  </nav>
</header>
<style>
  header { display: flex; align-items: center; height: var(--titlebar-h, 34px); padding: 0 4px 0 17px; background: var(--ground-2); user-select: none; flex: 0 0 auto; }
  .title { font-size: 10px; color: var(--bone-3); letter-spacing: .015em; }
  .divider { margin: 0 9px; color: var(--edge-4); }
  .spacer { flex: 1; height: 100%; }
  nav { display: flex; gap: 1px; }
  button { width: 39px; height: 30px; display: grid; place-items: center; border: 0; border-radius: 4px; color: var(--bone-5); background: none; cursor: pointer; }
  button:hover { background: var(--ground-8); color: var(--bone-14); }
  button.close:hover { background: #a53443; color: white; }
</style>