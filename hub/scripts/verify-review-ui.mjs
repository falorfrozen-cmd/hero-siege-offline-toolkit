// PR #64 regressions in the real Tauri dev window, through its MCP bridge.
// Requires a connected driver session and an isolated profile (see design.md).
// Usage: node scripts/verify-review-ui.mjs <tauri-mcp-cli entry.js> <isolated state.json> <results.json> [layout|actions|all]
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const [cli, statePath, output, phase = 'all'] = process.argv.slice(2);
assert(cli && statePath && output, 'Supply CLI entry, isolated state.json, and results.json');
assert(['layout', 'actions', 'all'].includes(phase), 'Unknown phase');
const initial = JSON.parse(readFileSync(statePath, 'utf8'));
assert.equal(initial.settings.work_offline, true, 'Use an isolated offline profile');
assert.equal(initial.installed.forgepact.version, '1.3.15');
assert.equal(initial.installed.forgepact.previous, '1.3.14');
assert.deepEqual(initial.favorites, ['forgepact']);
const checks = [];
let alignment = [], conflict = null;

function mcp(command, ...args) {
  const raw = execFileSync(process.execPath, [cli, command, '--window-id', 'hub', ...args, '--json'],
    { encoding: 'utf8', timeout: 45000, windowsHide: true });
  const result = JSON.parse(raw);
  return result.text ?? result.content?.map(part => part.text ?? '').join('\n') ?? '';
}
function js(source) {
  const result = mcp('webview-execute-js', '--script', `(async()=>{return JSON.stringify(await (${source.replace(/\r?\n/g, ' ')}));})()`);
  return JSON.parse(result.split('\n\n[Executed in window:')[0]);
}
function click(selector) { mcp('webview-interact', '--action', 'click', '--selector', selector); }
function check(name, value) {
  assert(value, name);
  checks.push(name);
  console.log(`PASS ${name}`);
}
function resetScroll() { js('(()=>{document.querySelector("main").scrollTop=0;return true})()'); }
const quick = '.quick-section [data-tool-id="forgepact"]';
const all = '[role="group"][aria-label="All tools"] [data-tool-id="forgepact"]';
const more = 'button[aria-haspopup="menu"]';

try {
  js('(()=>{document.querySelector("button.back")?.click();return true})()');
  const fixture = js('(async()=>{const m=await import("/src/library.svelte.js");return {native:!!window.__TAURI_INTERNALS__,path:m.tool("forgepact").install_path}})()');
  check('real native window uses the isolated fixture', fixture.native && fixture.path === initial.installed.forgepact.path);
  if (phase !== 'actions') {
    for (const [name, card, layout] of [['quick launch', quick, 'Grid'], ['grid', all, 'Grid'], ['list', all, 'List']]) {
      resetScroll();
      click(`button[aria-label="${layout} view"]`);
      click(`${card} ${more}`);
      check(`${name}: menu opened`, js('!!document.querySelector("[role=menu]")'));
      mcp('webview-interact', '--action', 'scroll', '--selector', 'main', '--scroll-y', '200');
      const after = js('({scrolled:document.querySelector("main").scrollTop,menu:!!document.querySelector("[role=menu]")})');
      check(`${name}: main really scrolled and menu closed`, after.scrolled > 0 && !after.menu);
    }
    resetScroll();
    click('button[aria-label="Grid view"]');
    click(`${quick} ${more}`);
    js('(()=>{const m=document.querySelector("[role=menu]");m.style.maxHeight="80px";m.scrollTop=40;return true})()');
    const inside = js('(()=>{const m=document.querySelector("[role=menu]");return {open:!!m,scrolled:m?.scrollTop}})()');
    check('scrolling inside a constrained menu keeps it open', inside.open && inside.scrolled > 0);
    js('(()=>{document.activeElement.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}));return true})()');
    check('Escape closes menu and restores trigger focus', js('!document.querySelector("[role=menu]") && document.activeElement.matches("button[aria-haspopup=menu]")'));

    alignment = js('Array.from(document.querySelectorAll(".card .status")).map(s=>{const dot=s.querySelector("i").getBoundingClientRect(),label=s.querySelector(".status-label").getBoundingClientRect(),v=s.querySelector(".version").getBoundingClientRect();return {dotOffset:Math.abs(dot.y+dot.height/2-label.y-label.height/2),versionHeight:v.height}})');
    check('status dots align with labels and empty version rows reserve space', alignment.length === 11 && alignment.every(s => s.dotOffset < 0.1 && s.versionHeight > 12));

    click('button[aria-label="Star HSCraftSim"]');
    check('favorite click persists through real IPC', JSON.parse(readFileSync(statePath, 'utf8')).favorites.includes('hscraftsim'));
    click('.quick-section button[aria-label="Unstar HSCraftSim"]');
    check('unstar persists through real IPC', !JSON.parse(readFileSync(statePath, 'utf8')).favorites.includes('hscraftsim'));
  }

  if (phase !== 'layout') {
    // Only the two destructive commands below are intercepted. All other IPC,
    // including the bridge and favorite persistence, goes to the real backend.
    js('(async()=>{const api=window.__TAURI_INTERNALS__;window.__review={original:window.fetch,calls:[],module:await import("/src/library.svelte.js")};window.fetch=(url,options)=>{const r=window.__review;const cmd=["install_tool","rollback_tool"].find(c=>String(url)===api.convertFileSrc(c,"ipc"));if(cmd&&JSON.parse(options.body).id==="forgepact"){r.calls.push(cmd);const reply=value=>new Response(JSON.stringify(value),{headers:{"Content-Type":"application/json","Tauri-Response":"ok"}});return cmd==="install_tool"?new Promise(resolve=>{r.finish=value=>resolve(reply(value))}):Promise.resolve(reply("rolled back"))};return r.original.call(window,url,options)};return true})()');
    click(`${quick} button[aria-label="Details for ForgePact"]`);
    click('button[aria-label="Update ForgePact"]');
    const pending = js('(()=>{const b=t=>Array.from(document.querySelectorAll("button")).find(b=>b.textContent.trim()===t);return {rollback:b("Roll back")?.disabled,folder:b("Open folder")?.disabled,update:document.querySelector("main button.action")?.disabled,calls:window.__review.calls}})()');
    console.log('Pending command state:', JSON.stringify(pending));
    check('pending update disables rollback and primary action but not Open folder', pending.rollback && pending.update && pending.folder === false && pending.calls.join() === 'install_tool');
    conflict = js('(async()=>{try{await window.__review.module.act("rollback_tool",{id:"forgepact"});return {rejected:false}}catch(e){return {rejected:true,name:e.name,message:e.message,calls:window.__review.calls}}})()');
    check('different command rejects before IPC', conflict.rejected && conflict.name === 'ToolBusyError' && conflict.calls.join() === 'install_tool');
    check('conflict is visible as a persistent error toast', js('document.body.textContent.includes("This tool is busy. Wait for its current operation to finish, then try again.")'));
    js('(()=>{window.__review.duplicate=window.__review.module.act("install_tool",{id:"forgepact"});return true})()');
    check('identical duplicate does not issue a second IPC', js('window.__review.calls.length===1'));
    js('(()=>{window.__review.finish("installed");return true})()');
    check('original and duplicate settle together', js('(async()=>await window.__review.duplicate)()') === 'installed');
    check('rollback re-enables after update settles', js('Array.from(document.querySelectorAll("button")).some(b=>b.textContent.trim()==="Roll back"&&!b.disabled)'));
    js('(()=>{Array.from(document.querySelectorAll("button")).find(b=>b.textContent.trim()==="Roll back").click();return true})()');
    check('rollback invokes its own command after the update', js('window.__review.calls.join(",")==="install_tool,rollback_tool"'));

    js('(async()=>{await window.__TAURI_INTERNALS__.invoke("plugin:event|emit",{event:"install-progress",payload:{id:"forgepact",phase:"verifying"}});return true})()');
    check('backend progress disables detail rollback without a pending frontend command', js('!window.__review.module.pendingFor("forgepact") && Array.from(document.querySelectorAll("button")).some(b=>b.textContent.trim()==="Roll back"&&b.disabled)'));
    click('button.back');
    click(`${quick} ${more}`);
    check('backend progress disables mutating menu actions but leaves release notes enabled', js('(()=>{const b=t=>Array.from(document.querySelectorAll("[role=menuitem]")).find(b=>b.textContent.trim()===t);return b("Roll back").disabled&&b("Uninstall").disabled&&!b("Release notes").disabled})()'));
    js('(async()=>{await window.__TAURI_INTERNALS__.invoke("plugin:event|emit",{event:"install-progress",payload:{id:"forgepact",phase:"done"}});return true})()');
    check('terminal progress re-enables mutating menu actions', js('Array.from(document.querySelectorAll("[role=menuitem]")).some(b=>b.textContent.trim()==="Roll back"&&!b.disabled)'));
  }
  writeFileSync(output, JSON.stringify({ phase, checks, alignment, conflict }, null, 2));
  console.log(`${checks.length} checks passed; results: ${output}`);
} finally {
  js('(async()=>{if(window.__review){const r=window.__review;window.fetch=r.original;r.finish?.("cleanup");await window.__TAURI_INTERNALS__.invoke("plugin:event|emit",{event:"install-progress",payload:{id:"forgepact",phase:"done"}});delete window.__review}const m=await import("/src/library.svelte.js");if(m.tool("hscraftsim").favorite)await m.setFavorite("hscraftsim",false);return true})()');
}
