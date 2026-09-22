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
  async function runSecondary() {
    if (!state.secondary || pending) return;
    try {
      await act('launch_tool', { id: tool.id });
    } catch { /* act puts the failure on the shared, persistent toast. */ }
  }
</script>
<span class="actions">
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
  {#if state.secondary}
    <button type="button" class="hub-button action secondary" class:compact
      disabled={pending}
      title={state.secondary.why}
      aria-label={state.secondary.aria}
      onclick={runSecondary}>
      {state.secondary.label}
    </button>
  {/if}
</span>
<style>
  .actions { flex-shrink: 0; display: flex; align-items: center; gap: 6px; }
  .action { flex-shrink: 0; min-width: 86px; color: var(--accent); background: transparent; border-color: var(--edge-7); }
  .action.solid { color: var(--accent-ink); background: var(--accent); border-color: var(--accent); }
  .action.stop { color: var(--bone-10); border-color: var(--edge-4); }
  .action.stop:hover:not(:disabled) { color: var(--rar-satanic); border-color: var(--rar-satanic); }
  .action.compact { min-width: 75px; min-height: 32px; padding: 6px 12px; }
  .action.secondary { min-width: 0; font-size: 0.85em; padding: 4px 8px; color: var(--bone-10); border-color: var(--edge-4); }
  .action.secondary.compact { min-height: 28px; padding: 4px 8px; }
  .spinner { width: 11px; height: 11px; border: 1.5px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>