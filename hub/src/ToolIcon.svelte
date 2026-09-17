<script>
  // Original vector artwork. No game assets or network requests; remains crisp
  // at Windows display scaling and in both card and list layouts.
  let { name = 'anvil', size = 64 } = $props();
  const uid = $props.id();
  const colors = { scroll: ['#d7c4ec', '#8467a2'], compass: ['#e0d4a5', '#938355'], handheld: ['#d1d5db', '#687681'], equipment: ['#eee0c0', '#978362'] };
  const palette = $derived(colors[name] ?? ['#efc79b', '#b27a48']);
</script>
<svg width={size} height={size} viewBox="0 0 80 80" fill="none" aria-hidden="true">
  <defs>
    <linearGradient id={uid} x1="15" y1="8" x2="65" y2="73" gradientUnits="userSpaceOnUse"><stop stop-color={palette[0]}/><stop offset=".48" stop-color={palette[1]}/><stop offset="1" stop-color="#563d2c"/></linearGradient>
  </defs>
  <g stroke={palette[0]} stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round">
    {#if name === 'anvil'}
      <path d="M39 3 51 17 40 31 29 17Z" fill={`url(#${uid})`}/><path d="m40 9-5 8 5 8 5-8Z" fill="#141619"/>
      <path d="M9 30h61c-2 8-10 12-23 13v12l8 9H28l7-9V43H24c-9 0-15-5-19-10h23V27h19v3" fill={`url(#${uid})`}/><path d="M30 64h23l5 7H24Z" fill={`url(#${uid})`}/><path d="M12 34h52M39 34v25m-7 8h19" opacity=".7"/>
    {:else if name === 'equipment'}
      <path d="m44 12 23 9v18c0 14-10 24-23 30-13-6-23-16-23-30V21Z" fill="#27272a"/><path d="m44 18 17 7v14c0 10-7 19-17 24-10-5-17-14-17-24V25Z" fill={`url(#${uid})`}/><path d="M44 21v39l12-14 2-18Z" fill="#22282b"/>
      <path d="m13 6 11 5 27 40-5 5L17 17Z" fill={`url(#${uid})`}/><path d="m38 53 16-11 4 5-16 11Z" fill={`url(#${uid})`}/><path d="m49 54 8 11 5-4-8-11M56 67l6-4 3 4-6 5Z" fill="#86714f"/>
    {:else if name === 'cube'}
      <path d="m40 6 29 16v36L40 75 11 58V22Z" fill="#251d18"/><path d="m40 11 24 13-24 14-24-14Zm0 31 24-14v27L40 69Zm-5 0v27L16 56V28Z" fill={`url(#${uid})`}/><path d="m40 17 14 7-14 8-14-8Zm4 28 15-9v16l-15 9Zm-24-9 11 8v16l-11-7Z" fill="#221e1b"/>
      <path d="m34 23 6-3 6 3-6 4ZM48 46l5-3v9l-5 3M23 43l4 3v8l-4-3"/>
    {:else if name === 'compass'}
      <circle cx="40" cy="41" r="30" fill="#242623"/><circle cx="40" cy="41" r="25" stroke-width="2"/><path d="M40 6V2m-4 5h8M40 13v7m0 43v7M12 41h7m43 0h7"/><path d="m40 17 7 18 17 6-18 7-6 18-7-18-17-7 18-6Z" fill={`url(#${uid})`}/><path d="m40 23-4 16 4 2 4-3Zm0 18 3 4-3 14-4-15Z" fill="#262825"/><circle cx="40" cy="41" r="3" fill={palette[0]}/>
    {:else if name === 'scroll'}
      <path d="M18 12h42c-6 2-8 8-8 15l-4 31H15l5-36c-9 0-9-10-2-10Z" fill={`url(#${uid})`}/><path d="M60 12c9 0 10 13 1 13h-9M19 58h30c-9 0-8 13 0 13H16c-9 0-8-13 3-13Z" fill={`url(#${uid})`}/><path d="M28 28h17M26 36h17M24 44h12M21 64h19" stroke="#44334f" stroke-width="2"/><path d="M50 67c1-19 6-38 23-43-2 20-11 32-19 31L48 73m8-27 13-14" fill="#746087"/>
    {:else if name === 'portal'}
      <path d="M13 70V31a27 27 0 0 1 54 0v39H55V32a15 15 0 0 0-30 0v38Z" fill={`url(#${uid})`}/><path d="M26 70V32a14 14 0 0 1 28 0v38Z" fill="#25201d"/><path d="M46 32c-18-6-21 24-7 26 12 2 16-15 8-18-8-4-13 10-5 9" stroke-width="2.5"/><path d="M9 70h20v5H9Zm43 0h19v5H52ZM14 39h10M56 39h10M14 54h10M56 54h10M40 6v12m-20-5 8 10m32-10-8 10"/>
    {:else if name === 'target'}
      <circle cx="40" cy="40" r="28" fill="#25211e"/><circle cx="40" cy="40" r="21"/><path d="M40 5v17m0 36v17M5 40h17m36 0h17m-50-15 6 6m18 18 6 6m0-30-6 6M31 49l-6 6"/><path d="m40 30 10 10-10 10-10-10Z" fill={`url(#${uid})`}/>
    {:else if name === 'chest'}
      <path d="M12 38V27c0-12 10-17 27-17 18 0 29 5 29 17v11Z" fill={`url(#${uid})`}/><path d="M12 38h56v29H12Z" fill="#503a2b"/><path d="M9 35h62v9H9Zm7-17 8-4v53h-8Zm38-4 8 4v49h-8Z" fill={`url(#${uid})`}/><path d="M34 38h12v18H34Z" fill={`url(#${uid})`}/><path d="M40 44v7M28 18h20M29 25h21M28 59h22" stroke="#31251f"/>
    {:else if name === 'stats'}
      <path d="m40 5 10 13-10 13-10-13Z" fill={`url(#${uid})`}/><path d="M15 50h12v21H15Zm19-14h12v35H34Zm20 8h12v27H54Z" fill={`url(#${uid})`}/><path d="M20 55v11M39 41v25M59 49v17M40 12v12"/>
    {:else if name === 'handheld'}
      <rect x="5" y="19" width="70" height="44" rx="10" fill={`url(#${uid})`}/><rect x="21" y="24" width="38" height="34" rx="3" fill="#121619"/><path d="m28 48 8-13 7 8 7-5" stroke="#596772"/><path d="M12 29v10m-5-5h10M66 44v8m-4-4h8" stroke="#22272a" stroke-width="2.5"/><circle cx="13" cy="49" r="4" fill="#252b30"/><circle cx="67" cy="32" r="4" fill="#252b30"/>
    {/if}
  </g>
</svg>
<style>svg { flex-shrink: 0; display: block; filter: drop-shadow(0 3px 3px #0005); }</style>
