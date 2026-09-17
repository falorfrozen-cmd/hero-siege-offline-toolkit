// Display-only metadata. Install/launch permissions and update availability
// always come from the signed catalog and Rust's ToolView.
const identities = {
  forgepact: { title: 'ForgePact', icon: 'anvil', category: 'gameplay', summary: 'Offline gameplay modifiers', order: 0 },
  'hero-siege-item-editor': { title: 'Item Editor', icon: 'equipment', category: 'editors', summary: 'Create and customize equipment', order: 1 },
  hscraftsim: { title: 'HSCraftSim', icon: 'cube', category: 'crafting', summary: 'Explore recipes and simulate crafting', order: 2 },
  'hs-offline-tracker': { title: 'HS Offline Tracker', icon: 'compass', category: 'tracking', summary: 'Track your runs and loot', order: 3 },
  hssaveeditor: { title: 'HS Save Editor', icon: 'scroll', category: 'editors', summary: 'Edit your offline characters', order: 4 },
  'hs-offline-launcher': { title: 'HS Offline Launcher', icon: 'portal', category: 'gameplay', summary: 'Start Hero Siege offline', order: 5 },
  'hs-value-editor': { title: 'HS Value Scanner', icon: 'target', category: 'editors', summary: 'Find and adjust runtime values', order: 6 },
  'hs-offline-loot-forge': { title: 'HS Loot Forge', icon: 'chest', category: 'gameplay', summary: 'Loot tables and targeted farming', order: 7 },
  'hs-stat-forge': { title: 'HS Stat Forge', icon: 'stats', category: 'editors', summary: 'Tune character stats and density', order: 8 },
  'hssaveeditor-steamdeck': { title: 'Steam Deck Save Editor', icon: 'handheld', category: 'editors', summary: 'Edit saves in your browser', order: 9 },
};

export const categories = [
  ['all', 'All'], ['editors', 'Editors'], ['gameplay', 'Gameplay'],
  ['tracking', 'Tracking'], ['crafting', 'Crafting'],
];

export function identity(tool) {
  return identities[tool.id] ?? { title: tool.name, summary: tool.summary, icon: 'cube', category: 'other', order: 100 };
}

export function selectTools(tools, { query = '', category = 'all', availability = 'all' } = {}) {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return tools.filter((tool) => {
    const meta = identity(tool);
    const text = `${tool.name} ${tool.id} ${tool.summary} ${meta.title} ${meta.summary} ${meta.category}`.toLowerCase();
    return words.every((word) => text.includes(word))
      && (category === 'all' || meta.category === category)
      && (availability !== 'installed' || !!tool.installed_version)
      && (availability !== 'updates' || tool.update_available)
      && (availability !== 'available' || !tool.installed_version);
  }).sort((a, b) => identity(a).order - identity(b).order || a.name.localeCompare(b.name));
}

export function quickTools(shown) {
  const favorites = shown.filter((tool) => tool.favorite);
  if (favorites.length) return favorites;
  return shown.filter((tool) => tool.installed_version || tool.running_pid || tool.running_elsewhere).slice(0, 3);
}

export const terminalPhases = ['done', 'failed', 'staged', 'downloaded'];
const phases = { started: 'Starting', downloading: 'Downloading', verifying: 'Verifying', extracting: 'Extracting', activating: 'Installing' };

// Shared by the full card and quick launch; neither invents a second action
// for a running/elevated/external tool or a completed-but-staged download.
export function presentation(tool, progress = null) {
  const inFlight = !!progress && !terminalPhases.includes(progress.phase);
  const justInstalled = progress?.phase === 'done' ? progress.version : null;
  const installed = tool.installed_version ?? justInstalled;
  const failed = progress?.phase === 'failed';
  let chip;
  if (inFlight) {
    const pct = progress.phase === 'downloading' && progress.total
      ? ` ${Math.min(100, Math.max(0, Math.round(progress.received / progress.total * 100)))}%` : '';
    chip = { text: (phases[progress.phase] ?? 'Working') + pct, tone: 'busy' };
  } else if (failed) chip = { text: 'Install failed', tone: 'failed' };
  else if (tool.running_elsewhere) chip = { text: 'Running externally', tone: 'running' };
  else if (tool.running_pid) chip = { text: 'Running', tone: 'running' };
  else if (tool.staged) chip = { text: 'Update staged', tone: 'staged' };
  else if (tool.update_available && !justInstalled) chip = { text: 'Update available', tone: 'update' };
  else if (installed) chip = { text: 'Installed', tone: 'ok' };
  else chip = { text: 'Not installed', tone: 'idle' };

  let primary;
  if (inFlight) primary = { label: phases[progress.phase] ?? 'Working', command: null };
  else if (tool.running_pid && tool.can_stop) primary = { label: 'Stop', command: 'stop_tool', why: tool.running_elsewhere ? 'Running from the hub-installed copy. The hub can stop it.' : '' };
  else if (tool.running_pid) primary = { label: 'Running', command: null, why: 'Started with Administrator rights. Close it from its own window.' };
  else if (tool.running_elsewhere) primary = { label: 'Running', command: null, why: 'Running outside the hub. Close it from its own window.' };
  else if (tool.update_available && !justInstalled) primary = { label: 'Update', command: 'install_tool' };
  else if (installed) primary = { label: tool.artifact.kind === 'html' ? 'Open' : 'Launch', command: 'launch_tool' };
  else if (tool.artifact.kind === 'nsis') primary = { label: 'Get it', command: 'open_release' };
  else primary = { label: failed ? 'Try again' : 'Install', command: 'install_tool' };
  return { chip, primary, installed, inFlight };
}
