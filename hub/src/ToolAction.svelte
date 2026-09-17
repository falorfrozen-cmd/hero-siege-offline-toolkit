<script>
  import { act, progressFor, pendingFor } from './library.svelte.js';
  import { presentation } from './tool-presentation.js';
  let { tool, compact = false } = $props();
  const state = $derived(presentation(tool, progressFor(tool.id)));
  const pending = $derived(pendingFor(tool.id));
  async function run() {
    const command = state.primary.command;
    if (!command || pending) return;
    try {
      await act(command === 'open_release' ? 'open_url' : command,
        command === 'open_release' ? { id: tool.id, url: tool.notes_url } : { id: tool.id });
    } catch { /* act puts the failure on the shared, persistent toast. */ }
  }
</script>
<button type="button" class="hub-button action" class:compact
  class:solid={state.primary.command === 'launch_tool'}
  class:stop={state.primary.command === 'stop_tool'}
  disabled={pending || !state.primary.command}
  title={state.primary.why || `${state.primary.label} ${tool.name}`}
  aria-label={`${state.primary.label} ${tool.name}`}
  aria-busy={pending || state.inFlight}
  onclick={run}>
  {#if pending || state.inFlight}<span class="spinner" aria-hidden="true"></span>{/if}
  {pending ? 'Working…' : state.primary.label}
</button>
<style>
  .action { flex-shrink: 0; min-width: 86px; color: var(--accent); background: transparent; border-color: var(--edge-7); }
  .action.solid { color: var(--accent-ink); background: var(--accent); border-color: var(--accent); }
  .action.stop { color: var(--bone-10); border-color: var(--edge-4); }
  .action.stop:hover:not(:disabled) { color: var(--rar-satanic); border-color: var(--rar-satanic); }
  .action.compact { min-width: 75px; min-height: 32px; padding: 6px 12px; }
  .spinner { width: 11px; height: 11px; border: 1.5px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>