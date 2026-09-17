<script>
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import ToolIcon from './ToolIcon.svelte';
  import {
    connect, library, status, updates, staged, busy, hubUpdate,
  } from './library.svelte.js';
  import TitleBar from './TitleBar.svelte';
  import Library from './Library.svelte';
  import ToolDetail from './ToolDetail.svelte';
  import Updates from './Updates.svelte';
  import Game from './Game.svelte';
  import Settings from './Settings.svelte';
  import About from './About.svelte';
  import FirstRun from './FirstRun.svelte';
  import Downloads from './Downloads.svelte';
  import StatusBar from './StatusBar.svelte';
  import Toasts from './Toasts.svelte';

  let route = $state('library');
  let openTool = $state(null);
  let drawerOpen = $state(false);

  const view = $derived(library());
  const state = $derived(status());
  /**
   * What the Updates badge counts. The hub's own release counts as one of them:
   * it is an update waiting on the Updates screen like any other, and leaving
   * it out of the count was the difference between a release being announced
   * and a release being findable only by someone who went looking.
   */
  const pendingCount = $derived(updates().length + (hubUpdate() ? 1 : 0));
  /** Nothing is drawn until the first-run screen has been answered. */
  const needsFirstRun = $derived(view && !view.settings.first_run_done);

  const sections = [
    { id: 'library', label: 'Library', icon: 'library' },
    { id: 'updates', label: 'Updates', icon: 'updates' },
    { id: 'game', label: 'Game', icon: 'game' },
    { id: 'settings', label: 'Settings', icon: 'settings' },
    { id: 'about', label: 'About', icon: 'about' },
  ];

  onMount(() => {
    // Hero Siege starting or stopping changes what the interlocks allow, and
    // nothing pushes that at us -- so it is still polled, but in Rust, where
    // the question costs one process snapshot and is answered without building
    // or sending a view unless something has actually moved. This used to be a
    // `setInterval(refresh, 10_000)` here, which asked for a full view every
    // ten seconds whether or not anything had changed.
    return connect();
  });

  function show(id) {
    openTool = null;
    route = id;
  }

  function openDetail(id, action = null) {
    openTool = { id, action };
  }
</script>

<div class="shell">
  <TitleBar />

  {#if state.loading}
    <main class="centred"><p>Reading the catalog…</p></main>
  {:else if needsFirstRun}
    <FirstRun />
  {:else}
    <div class="body">
      <nav class="sidebar" aria-label="Main navigation">
        <button class="brand" type="button" onclick={() => show('library')} aria-label="Hero Siege Toolkit library">
          <ToolIcon name="anvil" size={76}/>
          <span class="wordmark">HERO SIEGE<small>TOOLKIT</small></span>
        </button>
        {#each sections as section (section.id)}
          <button
            type="button"
            aria-label={section.label}
            class:active={route === section.id && !openTool}
            aria-current={route === section.id && !openTool ? 'page' : undefined}
            onclick={() => show(section.id)}
          >
            <Icon name={section.icon} size={20}/>
            <span>{section.label}</span>
            {#if section.id === 'updates' && pendingCount}
              <em class="count">{pendingCount}</em>
            {:else if section.id === 'updates' && staged().length}
              <em class="count staged">{staged().length}</em>
            {/if}
          </button>
        {/each}

        <span class="grow"></span>

        <button
          type="button"
          class="drawer-toggle"
          aria-label="Downloads"
          aria-expanded={drawerOpen}
          class:lit={busy().length > 0}
          onclick={() => (drawerOpen = !drawerOpen)}
        >
          <Icon name="download" size={20}/>
          <span>Downloads</span>
          {#if busy().length}<em class="count">{busy().length}</em>{/if}
        </button>
        <p class="credit">
          <span>Created by <b>ST4H</b></span>
          <span>UI Design by <b>Falor</b></span>
        </p>
      </nav>

      <main id="main-content">
        {#if openTool}
          <ToolDetail id={openTool.id} action={openTool.action} onback={() => (openTool = null)} />
        {:else if route === 'library'}
          <Library onopen={openDetail} />
        {:else if route === 'updates'}
          <Updates onopen={openDetail} />
        {:else if route === 'game'}
          <Game />
        {:else if route === 'settings'}
          <Settings />
        {:else}
          <About />
        {/if}
      </main>

      {#if drawerOpen}
        <Downloads onclose={() => (drawerOpen = false)} />
      {/if}
    </div>

    <StatusBar onshow={show} />
  {/if}

  <!-- Outside `main`, so a message is not parked wherever the reader happens
       to have scrolled to. Rendered in every state, including first run, so no
       failure path is left without a way to say so. -->
  <Toasts inset={!state.loading && !needsFirstRun} />
</div>

<style>
  .shell { --titlebar-h: 34px; --sidebar-w: 190px; display: flex; flex-direction: column; height: 100dvh; background: var(--ground-1); overflow: hidden; }
  .body { position: relative; flex: 1; display: flex; min-height: 0; }
  .sidebar { width: var(--sidebar-w); flex: 0 0 auto; display: flex; flex-direction: column; gap: 5px; padding: 12px 12px 0; border-right: 1px solid var(--edge-2); background: var(--ground-2); }
  .sidebar button { display: flex; align-items: center; gap: 12px; background: none; border: 1px solid transparent; border-radius: 7px; color: var(--bone-6); font-size: 13px; padding: 12px; cursor: pointer; text-align: left; }
  .sidebar button:hover { color: var(--bone-13); background: var(--ground-6); }
  .sidebar button.active { color: var(--bone-13); background: var(--accent-soft); border-color: var(--edge-7); }
  .sidebar button.active :global(svg) { color: var(--accent); }
  .sidebar button > span { flex: 1; }
  .sidebar .brand { flex-direction: column; gap: 8px; align-items: center; text-align: center; padding: 4px 0 28px; margin-bottom: 14px; border-radius: 0; }
  .sidebar .brand:hover { background: transparent; }
  .wordmark { font-family: Georgia, serif; color: var(--gold-2); font-size: 18px; letter-spacing: .04em; font-weight: 700; }
  .wordmark small { display: block; margin-top: 8px; font-family: 'Segoe UI', sans-serif; font-size: 10px; font-weight: 500; letter-spacing: .43em; padding-left: .43em; color: var(--accent); }
  .grow { flex: 1; min-height: 20px; }
  .count { font-style: normal; font-size: 10px; min-width: 19px; text-align: center; padding: 2px 5px; border-radius: 20px; background: var(--accent); color: var(--accent-ink); }
  .count.staged { background: var(--ground-9); color: var(--gold-2); }
  .sidebar .drawer-toggle { border-top: 1px solid var(--edge-2); border-radius: 0; padding-top: 17px; padding-bottom: 17px; }
  .drawer-toggle.lit { color: var(--arcane); }
  .credit { display: grid; gap: 5px; margin: 0; padding: 15px 10px; border-top: 1px solid var(--edge-2); color: var(--bone-3); font-size: 10px; line-height: 1.4; }
  .credit b { font-weight: 500; color: var(--bone-6); }
  main { flex: 1; min-width: 0; overflow: auto; padding: 25px 28px; scrollbar-gutter: stable; }
  .centred { display: grid; place-items: center; color: var(--bone-5); }
  @media (min-width: 1500px) { .shell { --sidebar-w: 218px; } main { padding: 32px 36px; } .sidebar { padding-top: 25px; } }
  @media (max-width: 1040px) { .shell { --sidebar-w: 166px; } main { padding: 22px 20px; } .sidebar { padding-left: 8px; padding-right: 8px; } .sidebar button { padding: 11px 9px; gap: 9px; font-size: 12px; } .wordmark { font-size: 16px; } }
  @media (max-height: 700px) { .sidebar .brand { flex-direction: row; padding: 0 3px 18px; gap: 4px; margin-bottom: 6px; } .brand :global(svg) { width: 40px; height: 50px; } .wordmark { font-size: 12px; } .wordmark small { font-size: 8px; margin-top: 5px; } }
  @media (max-width: 700px) { .shell { --sidebar-w: 62px; } .sidebar button { justify-content: center; padding: 11px; } .sidebar button > span, .sidebar .wordmark, .credit { display: none; } .sidebar .brand { padding: 0 0 14px; } .brand :global(svg) { width: 40px; height: 48px; } .sidebar button { position: relative; } .count { position: absolute; right: -3px; top: 0; } main { padding: 18px 14px; } }
</style>
