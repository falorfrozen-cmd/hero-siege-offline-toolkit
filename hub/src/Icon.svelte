<script>
  let { name, size = 20 } = $props();
  const paths = {
    library: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
    updates: 'M20 7a9 9 0 0 0-15-2L2 8m0-6v6h6M4 17a9 9 0 0 0 15 2l3-3m0 6v-6h-6',
    game: 'M6 7h12c2 0 3 2 3.5 5l.5 5c0 2-2 3-3.5 1.5L16 16H8l-2.5 2.5C4 20 2 19 2 17l.5-5C3 9 4 7 6 7zM6 10v5m-2.5-2.5h5M16 11h.01M19 14h.01',
    settings: 'M10 3h4l1 3 3 1 3 2v4l-3 2-1 3-3 3h-4l-1-3-3-1-3-2v-4l3-2 1-3zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    about: 'M12 16v-5m0-3h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    download: 'M12 3v12m-5-5 5 5 5-5M3 15v6h18v-6',
    search: 'M16 16l5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    star: 'm12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.9-6.2-3.3-6.2 3.3L7 14.2l-5-4.9 6.9-1z',
    more: 'M5 12h.01M12 12h.01M19 12h.01',
    list: 'M9 5h12M9 12h12M9 19h12M3 5h.01M3 12h.01M3 19h.01',
    close: 'M6 6l12 12M18 6 6 18',
    maximize: 'M5 5h14v14H5z',
    minimize: 'M5 12h14',
    arrow: 'M5 12h14m-5-5 5 5-5 5',
    chevron: 'm8 4 8 8-8 8',
  };
</script>
<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={name === 'more' ? 3 : 1.6} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.library} /></svg>
