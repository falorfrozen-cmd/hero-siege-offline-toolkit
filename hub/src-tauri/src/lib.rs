//! Toolkit Hub -- the Tauri side.
//!
//! A library and process manager for the ten tools in the Hero Siege Offline
//! Toolkit: it installs them from a signed catalog, runs them, notices when they
//! have a newer release, and can put one back the way it was.

pub mod catalog;
pub mod game;
pub mod install;
pub mod launch;
pub mod log;
pub mod paths;
pub mod procs;
pub mod state;
pub mod verify;
pub mod version;

use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::UpdaterExt;

use catalog::{LoadedCatalog, Source};
use paths::Layout;
use state::HubState;

/// Everything the commands share. Managed as an `Arc` because installs run on a
/// worker thread -- a 50 MB download must not hold the UI still.
pub struct Hub {
    pub layout: Layout,
    pub state: Mutex<HubState>,
    pub catalog: Mutex<LoadedCatalog>,
    /// Tool id -> PID of the process this hub started.
    pub running: Mutex<BTreeMap<String, u32>>,
    /// Tool id -> whether its health endpoint, or its preferred port, answered
    /// on the last probe round.
    ///
    /// Written only by the probe ticker, read only by `build_view`. A probe is
    /// a loopback connect, and a machine whose network stack does not refuse a
    /// closed port promptly pays the whole timeout for every one of them --
    /// measured here at 700 ms each, 2.8 s for the four tools that declare an
    /// endpoint. That is far too much to spend assembling a view, and it was
    /// being spent on the thread pumping the window's messages.
    ///
    /// The ticker rewrites the map whole each round, so an answer is never
    /// older than one tick and a tool it has stopped asking about leaves no
    /// stale entry behind.
    pub probes: Mutex<BTreeMap<String, bool>>,
    /// Tool ids with an install in flight, whoever started it.
    ///
    /// Two installs of one tool share a `.part` download and a staging
    /// directory, so the second writes over the first's download and then races
    /// it to the rename that commits the install. Nothing above this stopped
    /// that: the interface disables a card's button while its install runs, but
    /// Update all submits every tool at once and a second click on it arrives
    /// before any of them have finished.
    pub installing: Mutex<BTreeSet<String>>,
    /// The hub's own newer release, if the last check found one.
    ///
    /// Held here rather than in `state.json`: it is an answer about a remote
    /// release, and a cached "0.1.1 is available" surviving a restart into an
    /// already-updated hub would be a notice nobody can clear.
    pub hub_update: Mutex<Option<HubUpdate>>,
    /// The checkout this hub was built in, if it can still be found. Developer
    /// mode runs tools out of the submodules under it.
    pub repo_root: Option<PathBuf>,
    /// Read once at startup: a process's own elevation does not change.
    pub elevated: bool,
    pub log: log::Log,
}

impl Hub {
    fn settings(&self) -> state::Settings {
        self.state
            .lock()
            .map(|s| s.settings.clone())
            .unwrap_or_default()
    }

    fn persist(&self) {
        if let Ok(state) = self.state.lock() {
            if let Err(error) = state.save(&self.layout.state_file()) {
                self.log.error(format!("could not write state.json: {error}"));
            }
        }
    }

    fn tool(&self, id: &str) -> Result<catalog::Tool, String> {
        self.catalog
            .lock()
            .map_err(|_| "the catalog is busy".to_string())?
            .catalog
            .tool(id)
            .cloned()
            .ok_or_else(|| format!("{id} is not in the catalog"))
    }
}

// ---------------------------------------------------------------------------
// What the frontend sees
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct HubInfo {
    pub version: String,
    pub install_root: String,
    pub log_path: String,
    pub repo_root: Option<String>,
    pub catalog_url: String,
    /// Which repository this build trusts for its catalog and its own updates.
    pub hub_repo: String,
    /// Normally false, and deliberately so -- the hub elevates tools per launch
    /// rather than running elevated itself.
    pub elevated: bool,
}

/// A newer release of the hub itself, as announced by `latest.json`.
///
/// The ten tools are compared against the signed catalog; the hub is compared
/// against its own updater endpoint. Two different sources, but the interface
/// says "an update is available" the same way for both, so this rides in
/// `LibraryView` beside the tools rather than being asked for separately.
/// Deliberately not carrying the release body: every hub release ships the same
/// boilerplate about SmartScreen, so showing it would be a paragraph of noise
/// on top of the one fact that differs, which is the version number.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct HubUpdate {
    pub version: String,
    pub current_version: String,
}

/// One row of the Library grid, with everything the card needs already decided.
///
/// Assembled here rather than in Svelte so that "is this an update" has exactly
/// one implementation -- the version comparison that `About.svelte` had to get
/// right for `0.9.10` against `0.9.8`.
#[derive(Debug, Clone, Serialize)]
pub struct ToolView {
    #[serde(flatten)]
    pub tool: catalog::Tool,
    pub installed_version: Option<String>,
    pub installed_at: Option<String>,
    pub installed_sha256: Option<String>,
    pub install_path: Option<String>,
    pub can_roll_back: bool,
    pub update_available: bool,
    pub running_pid: Option<u32>,
    /// False for an elevated tool under an unelevated hub: Windows refuses the
    /// terminate, so the card must not offer Stop.
    pub can_stop: bool,
    /// A copy started outside the hub, noticed by its port being taken.
    pub running_elsewhere: bool,
    pub staged: Option<state::Staged>,
    /// Starred, which lifts the card into the Library's own row above the grid.
    pub favorite: bool,
    pub source_available: bool,
    /// Built from `HUB_REPO`, so the interface never has to know which
    /// repository this build came from. None when the tool declares no guide.
    pub guide_url: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LibraryView {
    pub tools: Vec<ToolView>,
    pub catalog_generated: String,
    pub catalog_source: Source,
    pub catalog_trusted_comment: String,
    pub last_check: Option<String>,
    pub settings: state::Settings,
    pub game: game::GameStatus,
    pub hub_repo: String,
    /// None when the last successful check found nothing newer. A failed
    /// check does not touch this field -- it leaves whatever was here in
    /// place, because a request that could not reach the release page is no
    /// evidence that a previously-found release went away.
    pub hub_update: Option<HubUpdate>,
}

fn build_view(hub: &Hub) -> Result<LibraryView, String> {
    let loaded = hub
        .catalog
        .lock()
        .map_err(|_| "the catalog is busy".to_string())?
        .clone();
    let hub_state = hub
        .state
        .lock()
        .map_err(|_| "the state is busy".to_string())?
        .clone();
    let running = hub
        .running
        .lock()
        .map_err(|_| "the process table is busy".to_string())?
        .clone();
    let probes = hub
        .probes
        .lock()
        .map_err(|_| "the probe cache is busy".to_string())?
        .clone();
    // One look at the process table for the whole view. It answers three
    // questions that used to be asked separately -- the game's state, whether
    // each tracked PID is alive, and whether a tool is running that this hub
    // never started -- and answering them from one snapshot means they cannot
    // contradict each other.
    let snapshot = procs::Snapshot::take();
    let game = game::status_from(&snapshot);

    let mut tools = Vec::with_capacity(loaded.catalog.tools.len());
    for tool in &loaded.catalog.tools {
        let installed = hub_state.installed.get(&tool.id);

        let tracked = running
            .get(&tool.id)
            .copied()
            .filter(|pid| snapshot.is_alive(*pid));

        // `Hub.running` is in memory, so a restart loses every tracked PID. A
        // process whose executable lives inside this tool's install directory
        // is this tool, whatever it is called -- which is the only signal that
        // works for the four tools with no health endpoint and no declared
        // port. Before this they went invisible on restart and their cards
        // offered Launch for something already open.
        let found = match (tracked, installed) {
            (None, Some(installed)) => {
                snapshot.find_under(std::path::Path::new(&installed.path))
            }
            _ => None,
        };
        let pid = tracked.or(found);

        // Only reached when the process table knew nothing, because a probe
        // is the weaker answer as well as the expensive one. Read from the
        // cache rather than taken here: this function must not touch the
        // network. See `Hub::probes`, and the budget test at the bottom of
        // this file.
        let answering = pid.is_none() && probes.get(&tool.id).copied().unwrap_or(false);

        let source_available = tool.source_launch.is_some()
            && hub
                .repo_root
                .as_ref()
                .map(|root| launch::submodule_path(root, &tool.submodule).is_dir())
                .unwrap_or(false);

        tools.push(ToolView {
            installed_version: installed.map(|i| i.version.clone()),
            installed_at: installed.map(|i| i.installed_at.clone()),
            installed_sha256: installed.map(|i| i.sha256.clone()),
            install_path: installed.map(|i| i.path.clone()),
            can_roll_back: installed.and_then(|i| i.previous.as_ref()).is_some(),
            update_available: installed
                .map(|i| version::is_newer(&tool.version, &i.version))
                .unwrap_or(false),
            running_pid: pid,
            can_stop: pid.is_some() && launch::can_stop(tool.launch.elevate, hub.elevated),
            // Up, but not started by this hub. Found by path it still has a
            // PID and so can still be stopped; known only by its health
            // endpoint it does not.
            running_elsewhere: tracked.is_none() && (found.is_some() || answering),
            staged: hub_state.staged.get(&tool.id).cloned(),
            favorite: hub_state.is_favorite(&tool.id),
            source_available,
            guide_url: catalog::guide_url(&tool.guide),
            tool: tool.clone(),
        });
    }

    Ok(LibraryView {
        tools,
        catalog_generated: loaded.catalog.generated,
        catalog_source: loaded.source,
        catalog_trusted_comment: loaded.trusted_comment,
        last_check: hub_state.last_check,
        settings: hub_state.settings,
        game,
        hub_repo: catalog::HUB_REPO.to_string(),
        hub_update: hub.hub_update.lock().ok().and_then(|u| u.clone()),
    })
}

fn announce(app: &AppHandle, hub: &Hub) {
    match build_view(hub) {
        Ok(view) => {
            let _ = app.emit("library-changed", view);
        }
        Err(error) => hub.log.error(format!("could not rebuild the library: {error}")),
    }
}

// ---------------------------------------------------------------------------
// The probe ticker
// ---------------------------------------------------------------------------

/// How often the ticker looks at the world.
///
/// This replaced a `setInterval(refresh, 10_000)` in the frontend, which cost a
/// full view build, a serialization and an IPC round trip every ten seconds
/// whether or not anything had changed. Same cadence, because the thing it
/// watches for -- Hero Siege starting or stopping -- is still not pushed at us
/// by anything. But the work is now one process snapshot, and nothing is sent
/// unless an answer actually moved.
const TICK: Duration = Duration::from_secs(10);

/// The parts of the view that change with nobody asking.
///
/// Everything else -- what is installed, what is staged, what the catalog says
/// -- changes only through a command, and every command that changes it calls
/// `announce` itself. So this is the whole of what a poll could discover.
#[derive(PartialEq)]
struct Pulse {
    /// Running, its PID, and whether EAC is up.
    game: (bool, Option<u32>, bool),
    /// Per tool: its PID if the process table has one, and its last probe.
    tools: Vec<(String, Option<u32>, bool)>,
}

/// Take one reading, refreshing the probe cache as a side effect.
///
/// None when a lock was busy: a round that could not read the world has nothing
/// to say about it, and returning a default would announce a change that did
/// not happen.
fn take_pulse(hub: &Hub) -> Option<Pulse> {
    let tools: Vec<catalog::Tool> = hub.catalog.lock().ok()?.catalog.tools.clone();
    let installed: BTreeMap<String, String> = hub
        .state
        .lock()
        .ok()?
        .installed
        .iter()
        .map(|(id, entry)| (id.clone(), entry.path.clone()))
        .collect();
    let running = hub.running.lock().ok()?.clone();

    let snapshot = procs::Snapshot::take();
    let game = game::status_from(&snapshot);

    let mut pids: BTreeMap<String, Option<u32>> = BTreeMap::new();
    let mut ask: Vec<&catalog::Tool> = Vec::new();
    for tool in &tools {
        // The same two questions `build_view` asks of the process table, in the
        // same order, so the two cannot disagree about which tool has a PID.
        let tracked = running
            .get(&tool.id)
            .copied()
            .filter(|pid| snapshot.is_alive(*pid));
        let found = match (tracked, installed.get(&tool.id)) {
            (None, Some(path)) => snapshot.find_under(std::path::Path::new(path)),
            _ => None,
        };
        let pid = tracked.or(found);

        // A tool this hub has neither installed nor started cannot be launched,
        // stopped or updated from its card, so "is something answering
        // somewhere" changes nothing the reader could act on. It is also the
        // probe that costs the most, because there is nothing there to answer
        // it -- six of the ten tools are in this state on a fresh install.
        if pid.is_none() && (installed.contains_key(&tool.id) || running.contains_key(&tool.id)) {
            ask.push(tool);
        }
        pids.insert(tool.id.clone(), pid);
    }

    // Concurrently, because the cost of a probe on a machine that does not
    // refuse a closed port is its timeout, in full, every time. Four of those
    // in series is four timeouts; started together it is one.
    let answers: BTreeMap<String, bool> = std::thread::scope(|scope| {
        let handles: Vec<_> = ask
            .iter()
            .map(|tool| scope.spawn(move || (tool.id.clone(), launch::already_running(tool))))
            .collect();
        handles.into_iter().filter_map(|handle| handle.join().ok()).collect()
    });

    if let Ok(mut guard) = hub.probes.lock() {
        *guard = answers.clone();
    }

    Some(Pulse {
        game: (game.running, game.pid, game.eac_running),
        tools: tools
            .iter()
            .map(|tool| {
                (
                    tool.id.clone(),
                    pids.get(&tool.id).copied().flatten(),
                    answers.get(&tool.id).copied().unwrap_or(false),
                )
            })
            .collect(),
    })
}

/// Watch for the changes nothing announces, and announce them.
///
/// The first round always announces, which is how the probe cache reaches a
/// view that was built before any probe had been taken.
fn start_ticker(app: AppHandle, hub: Arc<Hub>) {
    std::thread::spawn(move || {
        let mut last: Option<Pulse> = None;
        loop {
            if let Some(pulse) = take_pulse(&hub) {
                if last.as_ref() != Some(&pulse) {
                    announce(&app, &hub);
                    last = Some(pulse);
                }
            }
            std::thread::sleep(TICK);
        }
    });
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

// Everything below that reads the disk, the network or the process table is
// `#[tauri::command(async)]`. On a plain `fn` that attribute does not make the
// function async; it moves the call onto the async runtime instead of running
// it inline in the IPC handler -- which, on Windows, is the thread pumping
// WebView2's messages. A synchronous command holds that thread for its whole
// duration, so the window takes no clicks and paints no frames while it runs.
//
// `hub_info`, `get_settings` and `report` stay synchronous on purpose: they
// read memory and nothing else, and the thread hop would cost more than the
// work. Borrowed `State<'_, Arc<Hub>>` is fine under the attribute precisely
// because these are still `fn` and not `async fn`.

#[tauri::command]
fn hub_info(hub: State<'_, Arc<Hub>>) -> HubInfo {
    HubInfo {
        version: env!("CARGO_PKG_VERSION").to_string(),
        install_root: hub.layout.root().to_string_lossy().to_string(),
        log_path: hub.log.path().to_string_lossy().to_string(),
        repo_root: hub.repo_root.as_ref().map(|p| p.to_string_lossy().to_string()),
        catalog_url: catalog::catalog_url(),
        hub_repo: catalog::HUB_REPO.to_string(),
        elevated: hub.elevated,
    }
}

#[tauri::command(async)]
fn library(hub: State<'_, Arc<Hub>>) -> Result<LibraryView, String> {
    build_view(&hub)
}

#[tauri::command]
fn get_settings(hub: State<'_, Arc<Hub>>) -> state::Settings {
    hub.settings()
}

#[tauri::command(async)]
fn set_settings(
    app: AppHandle,
    hub: State<'_, Arc<Hub>>,
    settings: state::Settings,
) -> Result<state::Settings, String> {
    {
        let mut guard = hub.state.lock().map_err(|_| "the state is busy".to_string())?;
        guard.settings = settings;
    }
    hub.persist();
    let settings = hub.settings();
    let _ = app.emit("settings-changed", settings.clone());
    announce(&app, &hub);
    Ok(settings)
}

/// Star or unstar a tool, which is what decides the Library's top row.
///
/// Starring checks the catalog first, so a stale frontend cannot write an id
/// nothing will ever match. Unstarring does not: a tool that has since left the
/// catalog must still be removable, and the whole point of removing it is that
/// it is no longer there.
#[tauri::command(async)]
fn set_favorite(
    app: AppHandle,
    hub: State<'_, Arc<Hub>>,
    id: String,
    favorite: bool,
) -> Result<(), String> {
    if favorite {
        hub.tool(&id)?;
    }
    let changed = {
        let mut guard = hub.state.lock().map_err(|_| "the state is busy".to_string())?;
        guard.set_favorite(&id, favorite)
    };
    // Nothing moved, so nothing to write to disk and nothing for the grid to
    // re-lay-out.
    if !changed {
        return Ok(());
    }
    hub.persist();
    announce(&app, &hub);
    Ok(())
}

/// Refresh the catalog from the network, if the settings permit it.
///
/// Work offline is checked here rather than only in the UI, so a stale frontend
/// or a hand-edited state file cannot produce a request the player disabled.
#[tauri::command(async)]
fn check_for_updates(app: AppHandle, hub: State<'_, Arc<Hub>>) -> Result<LibraryView, String> {
    let settings = hub.settings();
    if !settings.may_reach_network() {
        return Err(if settings.work_offline {
            "Work offline is on. Turn it off in Settings to check for updates.".into()
        } else {
            "The hub has not finished its first run yet.".into()
        });
    }

    let (payload, signature) = catalog::fetch_remote(Duration::from_secs(30))?;
    let loaded = catalog::accept(&payload, &signature, Source::Remote)?;

    // Cached only once it verified. A catalog that failed its signature is not
    // written anywhere the hub would read it back from.
    let _ = std::fs::create_dir_all(hub.layout.cache());
    let _ = std::fs::write(hub.layout.cached_catalog(), &payload);
    let _ = std::fs::write(hub.layout.cached_catalog_signature(), &signature);

    hub.log.info(format!(
        "catalog refreshed: generated {}, {} tools",
        loaded.catalog.generated,
        loaded.catalog.tools.len()
    ));

    *hub.catalog.lock().map_err(|_| "the catalog is busy".to_string())? = loaded;
    {
        let mut guard = hub.state.lock().map_err(|_| "the state is busy".to_string())?;
        guard.last_check = Some(state::now_iso());
    }
    hub.persist();

    let view = build_view(&hub)?;
    let _ = app.emit("library-changed", view.clone());
    Ok(view)
}

/// Check the hub's own release, on demand.
///
/// Separate from `check_for_updates` rather than folded into it: they are two
/// requests to two places, and keeping them apart lets the interface say which
/// one it is waiting on instead of showing one spinner for both.
#[tauri::command]
async fn check_hub_update(app: AppHandle, hub: State<'_, Arc<Hub>>) -> Result<Option<HubUpdate>, String> {
    let settings = hub.settings();
    if !settings.may_reach_network() {
        return Err(if settings.work_offline {
            "Work offline is on. Turn it off in Settings to check for updates.".into()
        } else {
            "The hub has not finished its first run yet.".into()
        });
    }

    let result = refresh_hub_update(&hub, &app).await;
    // Announce on both outcomes: harmless when nothing changed, and it keeps
    // "announce after the check" unconditional rather than one more thing a
    // failure path has to remember to do.
    announce(&app, &hub);
    result
}

/// Whether a tool is running, answered the way `build_view` answers it.
///
/// `Hub.running` on its own is not enough, and the interlock used to consult
/// nothing else. It lives in memory, so a restart empties it while the tool it
/// was tracking is still open -- and a restart is exactly when `apply_staged`
/// runs, which made the one moment the interlock most needed to hold the one
/// moment it could not see anything. A process whose executable sits inside the
/// tool's install directory is that tool, whatever it is called, and that
/// survives a restart.
///
/// Takes the snapshot rather than making one so that a caller checking several
/// tools gets answers that cannot contradict each other, the same reason
/// `build_view` takes one.
fn tool_is_running(hub: &Hub, id: &str, snapshot: &procs::Snapshot) -> bool {
    let tracked = hub.running.lock().ok().and_then(|r| r.get(id).copied());
    if tracked.is_some_and(|pid| snapshot.is_alive(pid)) {
        return true;
    }
    let installed = hub
        .state
        .lock()
        .ok()
        .and_then(|s| s.installed.get(id).map(|i| i.path.clone()));
    installed
        .map(|path| snapshot.find_under(std::path::Path::new(&path)).is_some())
        .unwrap_or(false)
}

/// The right to install one tool, released when this is dropped.
///
/// Dropped on every exit from the install -- success, failure, the early return
/// when the interlock stages it -- because a claim leaked once is a tool that
/// can never be installed again without restarting the hub.
struct InstallClaim {
    hub: Arc<Hub>,
    id: String,
}

impl InstallClaim {
    fn take(hub: &Arc<Hub>, id: &str) -> Result<Self, String> {
        let mut claimed = hub
            .installing
            .lock()
            .map_err(|_| "the install set is busy".to_string())?;
        if !claimed.insert(id.to_string()) {
            // Worded for every holder, not just `install_tool`: uninstall and
            // rollback take this too, and "already being installed" is the
            // reason those were refused as much as it is for a second install.
            return Err(format!("An install of {id} is already running."));
        }
        Ok(Self {
            hub: Arc::clone(hub),
            id: id.to_string(),
        })
    }
}

impl Drop for InstallClaim {
    fn drop(&mut self) {
        if let Ok(mut claimed) = self.hub.installing.lock() {
            claimed.remove(&self.id);
        }
    }
}

/// A progress stream that cannot be left open.
///
/// A card shows itself busy from `Started` until a terminal event, so a path
/// that returns without one disables that card's button for the rest of the
/// session -- there is no second signal that clears it, and `library-changed`
/// does not. Emitting one by hand at every exit is exactly the discipline that
/// failed when orchestration moved out of `install::install`, which had been
/// emitting `Failed` on the way out: four exits lost it at once.
///
/// So it is structural instead. Terminal events passing through are noticed,
/// and a drop without one emits `Failed` rather than leaving the card stuck.
/// The explicit emissions are still there and still carry the real reason; this
/// only catches what they miss.
struct ProgressStream<'a> {
    inner: &'a dyn Fn(install::Progress),
    id: String,
    finished: std::cell::Cell<bool>,
}

impl<'a> ProgressStream<'a> {
    fn new(id: &str, inner: &'a dyn Fn(install::Progress)) -> Self {
        Self {
            inner,
            id: id.to_string(),
            finished: std::cell::Cell::new(false),
        }
    }

    fn emit(&self, progress: install::Progress) {
        if progress.is_terminal() {
            self.finished.set(true);
        }
        (self.inner)(progress);
    }

    /// Hand to anything that takes an emitter, so what it emits is seen here.
    fn as_emitter(&self) -> impl Fn(install::Progress) + '_ {
        move |progress| self.emit(progress)
    }
}

impl Drop for ProgressStream<'_> {
    fn drop(&mut self) {
        if !self.finished.get() {
            (self.inner)(install::Progress::Failed {
                id: self.id.clone(),
                error: "the install stopped without saying why".into(),
            });
        }
    }
}

/// The interlock, read now.
///
/// Deliberately a function rather than a value computed once and carried: the
/// answer goes stale in seconds, and the gap that matters is the download,
/// which runs for minutes. Whoever is about to write over an installation must
/// ask again immediately before doing it.
fn blocked_now(hub: &Hub, tool: &catalog::Tool) -> Option<String> {
    let snapshot = procs::Snapshot::take();
    let game = game::status_from(&snapshot);
    let running = tool_is_running(hub, &tool.id, &snapshot);
    game::install_blocked_by(&tool.name, running, &game)
}

/// Write a downloaded artifact into place, or stage it if the interlock has
/// closed since the download began.
///
/// `blocked` is passed in rather than read here so that the caller has to state
/// *when* it asked -- and every caller asks after its download, never before.
/// Checking only before is how an install that started against a closed game
/// went on to overwrite a running one: the check was true when it was made and
/// meaningless by the time it was used.
fn activate_or_stage(
    hub: &Arc<Hub>,
    tool: &catalog::Tool,
    artifact: &std::path::Path,
    emitter: &dyn Fn(install::Progress),
    blocked: Option<String>,
) -> Result<(), String> {
    if let Some(reason) = blocked {
        stage(hub, tool, artifact, reason.clone());
        // Terminal, and not `Done`: the bytes are verified and waiting, but no
        // version has been installed, and a card told otherwise would show one.
        emitter(install::Progress::Staged {
            id: tool.id.clone(),
            reason,
        });
        return Ok(());
    }
    match install::install_artifact(&hub.layout, tool, artifact, emitter) {
        Ok(installed) => {
            hub.log.info(format!(
                "installed {} {} ({})",
                tool.id, installed.version, installed.sha256
            ));
            if let Ok(mut guard) = hub.state.lock() {
                guard.installed.insert(tool.id.clone(), installed);
                guard.staged.remove(&tool.id);
            }
            hub.persist();
            Ok(())
        }
        Err(error) => {
            hub.log
                .error(format!("installing {} failed: {error}", tool.id));
            // `install_artifact` does not emit this itself -- the old
            // `install::install` wrapper did, and nothing replaced it when the
            // orchestration moved here.
            emitter(install::Progress::Failed {
                id: tool.id.clone(),
                error: error.to_string(),
            });
            Err(error.to_string())
        }
    }
}

/// Record an install that cannot be applied yet, with the reason on it.
fn stage(hub: &Hub, tool: &catalog::Tool, artifact: &std::path::Path, reason: String) {
    hub.log.info(format!("staged {}: {reason}", tool.id));
    if let Ok(mut guard) = hub.state.lock() {
        guard.staged.insert(
            tool.id.clone(),
            state::Staged {
                version: tool.version.clone(),
                artifact_path: artifact.to_string_lossy().to_string(),
                sha256: tool.artifact.sha256.clone(),
                staged_at: state::now_iso(),
                blocked_by: reason,
            },
        );
    }
    hub.persist();
}

#[tauri::command(async)]
fn install_tool(app: AppHandle, hub: State<'_, Arc<Hub>>, id: String) -> Result<(), String> {
    let tool = hub.tool(&id)?;
    let settings = hub.settings();
    if !settings.may_reach_network() && bundled_artifact(&hub, &tool).is_none() {
        return Err(
            "Work offline is on and this artifact is not in the offline bundle.".into(),
        );
    }

    let hub = Arc::clone(&hub);
    // One at a time per tool, whoever asked. Held for the whole command.
    let _claim = InstallClaim::take(&hub, &tool.id)?;

    let emitter = {
        let app = app.clone();
        move |progress: install::Progress| {
            let _ = app.emit("install-progress", progress);
        }
    };

    // Download first, then read the interlock, then activate -- the same order
    // the launch check uses, and now the same code. Staging a blocked update
    // needs the artifact in hand anyway, so there is nothing to save by
    // checking first, and checking *only* first is what let an install started
    // against a closed game overwrite a running one several minutes later.
    //
    // Inline rather than on a spawned thread. `#[tauri::command(async)]`
    // already runs this off the thread pumping the window's messages, and
    // spawning again meant the command returned as soon as the worker started
    // -- so `await install_tool(...)` resolved before anything had been
    // downloaded, and Update all cleared its own button while ten installs were
    // still running.
    let stream = ProgressStream::new(&tool.id, &emitter);
    let emit = stream.as_emitter();

    let artifact = match bundled_artifact(&hub, &tool) {
        Some(path) => path,
        None => match install::download(&tool, &hub.layout, &emit) {
            Ok(path) => path,
            Err(error) => {
                hub.log
                    .error(format!("downloading {} failed: {error}", tool.id));
                // `download` emits `Started` and then nothing on the way out,
                // so without this the card sits on *Starting* forever.
                stream.emit(install::Progress::Failed {
                    id: tool.id.clone(),
                    error: error.to_string(),
                });
                return Err(error.to_string());
            }
        },
    };

    let result = activate_or_stage(&hub, &tool, &artifact, &emit, blocked_now(&hub, &tool));
    // Closed before the announce, so the card has its terminal event by the
    // time the new library view arrives to be drawn from.
    drop(emit);
    drop(stream);
    announce(&app, &hub);
    result
}

/// An artifact that came with an offline bundle, if it is there and correct.
fn bundled_artifact(hub: &Hub, tool: &catalog::Tool) -> Option<PathBuf> {
    let path = hub.layout.bundle().join(&tool.artifact.name);
    if !path.is_file() {
        return None;
    }
    match verify::sha256_file(&path) {
        Ok(actual) if verify::expect_sha256(&actual, &tool.artifact.sha256).is_ok() => Some(path),
        _ => None,
    }
}

#[tauri::command(async)]
fn uninstall_tool(app: AppHandle, hub: State<'_, Arc<Hub>>, id: String) -> Result<(), String> {
    let hub = Arc::clone(&hub);
    // Uninstalling deletes the directory an install writes into, so it takes
    // the same claim: an auto-install from the launch check can be part way
    // through its rename when this arrives.
    let _claim = InstallClaim::take(&hub, &id)?;

    // The same restart-blindness the interlock had. `hub.running` is in memory,
    // so after a restart this saw nothing and cheerfully deleted the directory
    // a running tool was executing from. A process running out of the install
    // directory is that tool, tracked or not.
    if tool_is_running(&hub, &id, &procs::Snapshot::take()) {
        return Err("Stop the tool before uninstalling it.".into());
    }
    install::uninstall(&hub.layout, &id).map_err(|e| e.to_string())?;
    {
        let mut guard = hub.state.lock().map_err(|_| "the state is busy".to_string())?;
        guard.installed.remove(&id);
        guard.staged.remove(&id);
    }
    hub.persist();
    hub.log.info(format!("uninstalled {id}"));
    announce(&app, &hub);
    Ok(())
}

#[tauri::command(async)]
fn rollback_tool(app: AppHandle, hub: State<'_, Arc<Hub>>, id: String) -> Result<(), String> {
    let hub = Arc::clone(&hub);
    // Rollback rewrites `current.json`, which is the same file an install
    // rewrites when it activates. Whichever wrote last would win, and the
    // pointer would name a version the other one had just moved.
    let _claim = InstallClaim::take(&hub, &id)?;

    let installed = install::rollback(&hub.layout, &id).map_err(|e| e.to_string())?;
    hub.log
        .info(format!("rolled {id} back to {}", installed.version));
    {
        let mut guard = hub.state.lock().map_err(|_| "the state is busy".to_string())?;
        guard.installed.insert(id, installed);
    }
    hub.persist();
    announce(&app, &hub);
    Ok(())
}

#[tauri::command(async)]
fn verify_tool(hub: State<'_, Arc<Hub>>, id: String) -> Result<install::VerifyReport, String> {
    let version = hub
        .state
        .lock()
        .map_err(|_| "the state is busy".to_string())?
        .installed
        .get(&id)
        .map(|i| i.version.clone())
        .ok_or_else(|| format!("{id} is not installed"))?;
    Ok(install::verify_installed(&hub.layout, &id, &version))
}

#[tauri::command(async)]
fn launch_tool(
    app: AppHandle,
    hub: State<'_, Arc<Hub>>,
    id: String,
    from_source: Option<bool>,
) -> Result<launch::Started, String> {
    let tool = hub.tool(&id)?;
    let from_source = from_source.unwrap_or(false);

    let started = if from_source {
        let root = hub
            .repo_root
            .as_ref()
            .ok_or("this hub was not built inside the toolkit checkout")?;
        launch::launch_from_source(&tool, &launch::submodule_path(root, &tool.submodule))
    } else {
        let dir = hub
            .state
            .lock()
            .map_err(|_| "the state is busy".to_string())?
            .installed
            .get(&id)
            .map(|i| PathBuf::from(&i.path))
            .ok_or_else(|| format!("{} is not installed", tool.name))?;
        launch::launch(&tool, &dir)
    }
    .map_err(|error| {
        // Launch failures used to reach only the banner, which meant a report
        // of one arrived as a screenshot rather than as a log line.
        hub.log.error(format!("launching {id} failed: {error}"));
        error.to_string()
    })?;

    if let launch::Started::Process { pid } = started {
        if let Ok(mut running) = hub.running.lock() {
            running.insert(id.clone(), pid);
        }
        hub.log.info(format!("launched {id} as pid {pid}"));

        // Wait for the tool's own health endpoint on a worker thread, so the
        // card can turn from Starting to Running without the UI blocking for
        // the twenty-odd seconds a frozen Python app takes to bind its port.
        let app = app.clone();
        let hub = Arc::clone(&hub);
        std::thread::spawn(move || {
            let healthy = launch::wait_until_healthy(&tool);
            let _ = app.emit(
                "tool-health",
                serde_json::json!({ "id": tool.id, "healthy": healthy, "pid": pid }),
            );
            announce(&app, &hub);
        });
    }

    announce(&app, &hub);
    Ok(started)
}

#[tauri::command(async)]
fn stop_tool(app: AppHandle, hub: State<'_, Arc<Hub>>, id: String) -> Result<(), String> {
    let tracked = hub
        .running
        .lock()
        .map_err(|_| "the process table is busy".to_string())?
        .get(&id)
        .copied();

    // The view offers Stop for a tool found by its install path as well as one
    // this hub launched, so this has to be able to stop both -- otherwise the
    // button is the same lie as a Launch offered for something already open.
    let pid = match tracked {
        Some(pid) => Some(pid),
        None => hub
            .state
            .lock()
            .ok()
            .and_then(|state| state.installed.get(&id).map(|i| i.path.clone()))
            .and_then(|path| {
                procs::Snapshot::take().find_under(std::path::Path::new(&path))
            }),
    };

    if let Some(pid) = pid {
        launch::stop(pid).map_err(|e| e.to_string())?;
        if let Ok(mut running) = hub.running.lock() {
            running.remove(&id);
        }
        hub.log.info(format!("stopped {id} (pid {pid})"));
    }
    // Anything staged behind this tool can go in now.
    apply_staged(&app, &hub);
    announce(&app, &hub);
    Ok(())
}

#[tauri::command(async)]
fn game_status() -> game::GameStatus {
    game::status()
}

#[tauri::command(async)]
fn open_path(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener()
        .open_path(path, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command(async)]
fn open_url(app: AppHandle, url: String) -> Result<(), String> {
    // Only ever http(s): a catalog field is not a reason to hand an arbitrary
    // scheme to the shell.
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err(format!("refusing to open {url}"));
    }
    use tauri_plugin_opener::OpenerExt;
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

/// Errors from the web side, into the same log as everything else.
#[tauri::command]
fn report(hub: State<'_, Arc<Hub>>, level: String, message: String) {
    hub.log.write(&level, &message);
}

/// Why a staged update can never be applied, if it cannot.
///
/// `install_artifact` verifies the artifact against the hash the catalog
/// carries *now*. So a tool that releases again while its update waits behind a
/// running game leaves bytes that can no longer pass: the check fails on every
/// startup, forever, with an error toast each time and nothing in the interface
/// able to clear it. An entry whose download has been cleared out of the cache
/// is the same story with a different first failure.
///
/// Dropping the entry leaves the tool showing "an update is available", which
/// is true, actionable, and downloads the right bytes next time.
fn unapplicable(tool: &catalog::Tool, entry: &state::Staged) -> Option<String> {
    if entry.version != tool.version {
        return Some(format!(
            "the catalog has moved on to {} since {} was staged",
            tool.version, entry.version
        ));
    }
    if !std::path::Path::new(&entry.artifact_path).is_file() {
        return Some("its download is no longer in the cache".to_string());
    }
    None
}

/// Apply anything that was staged, now that whatever blocked it may be gone.
fn apply_staged(app: &AppHandle, hub: &Arc<Hub>) {
    let staged: Vec<(String, state::Staged)> = match hub.state.lock() {
        Ok(guard) => guard
            .staged
            .iter()
            .map(|(id, s)| (id.clone(), s.clone()))
            .collect(),
        Err(_) => return,
    };
    if staged.is_empty() {
        return;
    }
    for (id, entry) in staged {
        let Ok(tool) = hub.tool(&id) else { continue };
        let Ok(_claim) = InstallClaim::take(hub, &id) else {
            continue;
        };
        let artifact = PathBuf::from(&entry.artifact_path);

        if let Some(why) = unapplicable(&tool, &entry) {
            hub.log
                .info(format!("dropped the staged update for {id}: {why}"));
            if let Ok(mut guard) = hub.state.lock() {
                guard.staged.remove(&id);
            }
            hub.persist();
            continue;
        }
        let emitter = {
            let app = app.clone();
            move |progress: install::Progress| {
                let _ = app.emit("install-progress", progress);
            }
        };
        // Read per tool rather than once for the pass: applying one staged
        // update takes time, and the tool after it may have been opened while
        // that ran. `blocked_now` also sees tools this hub did not start, which
        // is what this pass needs -- it runs at startup, where `hub.running` is
        // empty by definition, so consulting only that map meant a staged
        // update was applied over whatever the reader had left open.
        if let Err(error) =
            activate_or_stage(hub, &tool, &artifact, &emitter, blocked_now(hub, &tool))
        {
            hub.log
                .error(format!("staged update for {id} failed: {error}"));
        }
    }
}

/// Shown to the player when a hub update check fails. The updater's own
/// error -- offline, a release page with no `latest.json`, a signature that
/// does not verify -- goes to the log instead, where the wording in the
/// issue and this constant can both be searched for.
const HUB_UPDATE_CHECK_FAILED: &str = "Could not check for updates. Please try again.";

/// Turn an update-check outcome into what `LibraryView::hub_update` should
/// hold, and log it the way the log has always read.
///
/// Split out of `refresh_hub_update` so the bug in how a failure was handled
/// -- looking exactly like "checked, nothing newer" -- has a home that does
/// not need `tauri_plugin_updater::Updater` or an `AppHandle` to test: this
/// half takes the outcome as a plain `Result` and never touches the network.
fn settle_hub_update_check(hub: &Hub, outcome: Result<Option<HubUpdate>, String>) -> Result<Option<HubUpdate>, String> {
    match outcome {
        Ok(update) => {
            match &update {
                Some(update) => hub.log.info(format!(
                    "hub update available: {} (running {})",
                    update.version, update.current_version
                )),
                None => hub.log.info("hub update check: this is the newest release"),
            }
            if let Ok(mut guard) = hub.hub_update.lock() {
                *guard = update.clone();
            }
            Ok(update)
        }
        Err(detail) => {
            // A failed check says nothing about whether a cached newer
            // release went away, so the cache is left untouched -- but it
            // must not come back looking like a success. `install_hub_update`
            // already refuses with "no longer being offered" if the cached
            // release really did disappear.
            hub.log.info(format!("hub update check: {detail}"));
            Err(HUB_UPDATE_CHECK_FAILED.to_string())
        }
    }
}

/// Ask the updater endpoint whether a newer hub has been released.
///
/// Awaited from commands. Only the startup worker outside the async runtime
/// uses `block_on`: nesting it inside a command panics and leaves its IPC
/// promise unresolved, so the interface stays on "Checking..." forever.
///
/// Deliberately independent of the catalog check. They are two different files
/// on two different release pages, and the hub's own update is the one a player
/// has no other way to find out about -- so a catalog fetch that fails must not
/// take it down with it.
///
/// A failure -- offline, a release page with no `latest.json`, a signature
/// that does not verify against the built-in public key -- comes back as
/// `Err`, not as `Ok(None)`: the two used to look identical, which is what let
/// the About screen claim "This is the newest release" after a check that
/// never actually ran.
async fn refresh_hub_update(hub: &Hub, app: &AppHandle) -> Result<Option<HubUpdate>, String> {
    let found = match app.updater_builder().timeout(Duration::from_secs(30)).build() {
        Ok(updater) => match updater.check().await {
            Ok(found) => found,
            Err(error) => return settle_hub_update_check(hub, Err(error.to_string())),
        },
        Err(error) => return settle_hub_update_check(hub, Err(error.to_string())),
    };

    let update = found.map(|update| HubUpdate {
        version: update.version.clone(),
        current_version: update.current_version.clone(),
    });

    settle_hub_update_check(hub, Ok(update))
}

/// Download and install the hub's own update.
///
/// In Rust, and not in the frontend, because `work_offline` has to be enforced
/// somewhere a stale frontend cannot get past -- the same reasoning that keeps
/// the *check* here. The frontend used to call the updater plugin directly,
/// which meant turning Work offline on left "Download and install" working: the
/// switch covered every request the hub makes except the largest one it makes
/// about itself. `updater:default` is no longer in the window's capability, so
/// that route is closed rather than merely unused.
///
/// The handle stays on this side for its whole life, so nothing has to cross
/// the boundary: `check()` returns it and `download_and_install` consumes it.
#[tauri::command]
async fn install_hub_update(app: AppHandle, hub: State<'_, Arc<Hub>>) -> Result<String, String> {
    if !hub.settings().may_reach_network() {
        return Err("Work offline is on. Turn it off to update the hub.".into());
    }

    let updater = app.updater().map_err(|error| error.to_string())?;
    let found = updater.check().await.map_err(|error| error.to_string())?;
    let Some(update) = found else {
        // The backend said there was one. Between then and now the release page
        // stopped offering it -- a draft re-drafted, a release deleted.
        return Err("The release is no longer being offered. Check again.".into());
    };

    let version = update.version.clone();
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|error| error.to_string())?;
    hub.log.info(format!("installed hub update {version}"));
    Ok(version)
}

/// The launch check, plus whatever auto-download/auto-install allow.
fn startup_check(app: AppHandle, hub: Arc<Hub>) {
    let settings = hub.settings();
    if !settings.may_reach_network() || !settings.check_on_launch {
        return;
    }

    // Before the catalog, and announced on its own, because the catalog fetch
    // below returns early on any failure -- and the hub's own update went
    // unmentioned entirely until it was checked here. Stays silent on
    // failure: no timestamp, no toast, and whatever was cached is kept.
    if matches!(tauri::async_runtime::block_on(refresh_hub_update(&hub, &app)), Ok(Some(_))) {
        announce(&app, &hub);
    }

    let Ok((payload, signature)) = catalog::fetch_remote(Duration::from_secs(30)) else {
        hub.log.info("launch check: the catalog could not be fetched");
        return;
    };
    let loaded = match catalog::accept(&payload, &signature, Source::Remote) {
        Ok(loaded) => loaded,
        Err(error) => {
            hub.log.error(format!("launch check: {error}"));
            return;
        }
    };
    let _ = std::fs::create_dir_all(hub.layout.cache());
    let _ = std::fs::write(hub.layout.cached_catalog(), &payload);
    let _ = std::fs::write(hub.layout.cached_catalog_signature(), &signature);

    let updates: Vec<catalog::Tool> = {
        let Ok(guard) = hub.state.lock() else { return };
        loaded
            .catalog
            .tools
            .iter()
            .filter(|tool| {
                guard
                    .installed
                    .get(&tool.id)
                    .map(|i| version::is_newer(&tool.version, &i.version))
                    .unwrap_or(false)
            })
            .cloned()
            .collect()
    };

    if let Ok(mut guard) = hub.catalog.lock() {
        *guard = loaded;
    }
    if let Ok(mut guard) = hub.state.lock() {
        guard.last_check = Some(state::now_iso());
    }
    hub.persist();
    announce(&app, &hub);

    if !settings.auto_download || updates.is_empty() {
        return;
    }

    for tool in updates {
        let emitter = {
            let app = app.clone();
            move |progress: install::Progress| {
                let _ = app.emit("install-progress", progress);
            }
        };
        // Claimed before the download, not after it. The download is the part
        // that collides: every download of one tool writes the same `.part`
        // file, so a click on Update all during this one used to start a second
        // download into it. Held for the rest of the iteration, which covers
        // the download, the staging and the activation alike -- including the
        // download-only case below, which returns while the bytes are on disk
        // and the claim still matters.
        let Ok(_claim) = InstallClaim::take(&hub, &tool.id) else {
            continue;
        };

        let stream = ProgressStream::new(&tool.id, &emitter);
        let emit = stream.as_emitter();

        let artifact = match install::download(&tool, &hub.layout, &emit) {
            Ok(path) => path,
            Err(error) => {
                hub.log
                    .error(format!("auto-download of {} failed: {error}", tool.id));
                stream.emit(install::Progress::Failed {
                    id: tool.id.clone(),
                    error: error.to_string(),
                });
                continue;
            }
        };

        if !settings.effective_auto_install() {
            // Downloaded is all that was asked for. Terminal, and distinct from
            // `Staged`: nothing is waiting to be applied, the bytes are just
            // cached so that installing later is quick. Without it the card
            // stayed on *Verifying* until the hub was restarted.
            stream.emit(install::Progress::Downloaded {
                id: tool.id.clone(),
            });
            continue;
        }

        // D5's interlocks, read after the download rather than before it: it
        // can run for minutes, and what was closed when it started is often
        // open by the time it finishes. An update that cannot be applied safely
        // waits and says why, rather than being written over a running tool or
        // over a game whose PE ForgePact has patched.
        if let Err(error) =
            activate_or_stage(&hub, &tool, &artifact, &emit, blocked_now(&hub, &tool))
        {
            hub.log
                .error(format!("auto-install of {} failed: {error}", tool.id));
        }
    }
    announce(&app, &hub);
}

/// Walk up from a starting directory looking for the toolkit checkout.
///
/// `tauri dev` runs with the working directory at `hub/src-tauri`, and a
/// released hub is installed nowhere near a checkout -- so this returns None
/// often, and developer mode is simply unavailable when it does.
fn find_repo_root(start: PathBuf) -> Option<PathBuf> {
    let mut current = start;
    for _ in 0..8 {
        if current.join(".gitmodules").is_file() && current.join("catalog").is_dir() {
            return Some(current);
        }
        current = current.parent()?.to_path_buf();
    }
    None
}

pub fn run() {
    let install_root = paths::default_install_root();

    // Settings can move the install root, so the state file has to be read from
    // the default location first to find out where everything else lives.
    let bootstrap = HubState::load(&Layout::new(&install_root).state_file());
    let layout = Layout::new(
        bootstrap
            .settings
            .install_root
            .clone()
            .map(PathBuf::from)
            .unwrap_or(install_root),
    );
    let _ = layout.ensure();

    let hub_state = HubState::load(&layout.state_file());
    let loaded = catalog::load_local(
        &layout.bundle(),
        &layout.cached_catalog(),
        &layout.cached_catalog_signature(),
    );
    let logger = log::Log::new(layout.log_file());
    let elevated = launch::hub_is_elevated();
    logger.info(format!(
        "hub {} starting; repo {}; catalog {:?} generated {}; elevated {}",
        env!("CARGO_PKG_VERSION"),
        catalog::HUB_REPO,
        loaded.source,
        loaded.catalog.generated,
        elevated
    ));
    if elevated {
        // Not fatal, but worth a line: every tool started from here inherits
        // Administrator, which is exactly what elevating per launch avoids.
        logger.info(
            "this hub is running elevated, so every tool it starts will be too",
        );
    }

    let repo_root = std::env::current_dir()
        .ok()
        .and_then(find_repo_root)
        .or_else(|| {
            std::env::current_exe()
                .ok()
                .and_then(|exe| exe.parent().map(|p| p.to_path_buf()))
                .and_then(find_repo_root)
        });

    let hub = Arc::new(Hub {
        layout,
        state: Mutex::new(hub_state),
        catalog: Mutex::new(loaded),
        running: Mutex::new(BTreeMap::new()),
        probes: Mutex::new(BTreeMap::new()),
        installing: Mutex::new(BTreeSet::new()),
        hub_update: Mutex::new(None),
        repo_root,
        elevated,
        log: logger,
    });

    #[allow(unused_mut)]
    let mut builder = tauri::Builder::default();

    // A bridge an agent can drive the running hub through: click the tabs, read
    // the view, check the window is still taking input. That is how the
    // responsiveness work was checked, because the defect it fixes is invisible
    // to a test -- it is the window not repainting, not a wrong answer.
    //
    // Debug builds with the `mcp-bridge` feature only (`npm start` turns it
    // on), and bound to loopback rather than the plugin's default of every
    // interface: it can invoke any command this app has.
    #[cfg(all(debug_assertions, feature = "mcp-bridge"))]
    {
        builder = builder.plugin(
            tauri_plugin_mcp_bridge::Builder::new()
                .bind_address("127.0.0.1")
                .build(),
        );
    }

    builder
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // A second launch raises the window already open rather than racing
            // it for state.json.
            if let Some(window) = app.get_webview_window("hub") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Arc::clone(&hub))
        .setup(move |app| {
            let handle = app.handle().clone();
            // The bridge drives the window by invoking its own plugin commands
            // from the webview, so the window needs permission to make those
            // calls. Added here rather than in `capabilities/`, which every
            // build reads -- this way the released hub's capability set is
            // exactly what it was.
            #[cfg(all(debug_assertions, feature = "mcp-bridge"))]
            {
                if let Err(error) = handle.add_capability(
                    r#"{"identifier":"mcp-bridge-dev","windows":["hub"],"permissions":["mcp-bridge:default"]}"#,
                ) {
                    eprintln!("the MCP bridge capability could not be added: {error}");
                }
            }
            // The poll that used to live in `App.svelte`, moved to where the
            // data is: it announces only when something it watches has moved,
            // so an idle hub costs one process snapshot a tick and no IPC.
            start_ticker(handle.clone(), Arc::clone(&hub));
            let hub = Arc::clone(&hub);
            std::thread::spawn(move || {
                // Anything staged from a previous session goes in first, before
                // the network is touched -- a pending install the user already
                // agreed to should not wait on a check succeeding.
                apply_staged(&handle, &hub);
                startup_check(handle, hub);
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            hub_info,
            library,
            get_settings,
            set_settings,
            set_favorite,
            check_for_updates,
            check_hub_update,
            install_hub_update,
            install_tool,
            uninstall_tool,
            rollback_tool,
            verify_tool,
            launch_tool,
            stop_tool,
            game_status,
            open_path,
            open_url,
            report,
        ])
        .run(tauri::generate_context!())
        .expect("the hub could not start");
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A `Hub` with nothing installed and nothing running, in its own temporary
    /// directory. That is the ordinary state of a fresh install, and it used to
    /// be the expensive one: every tool fell through to a health probe
    /// precisely because there was nothing on disk to find.
    fn scratch_hub(name: &str) -> (Hub, PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "hub-{name}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let layout = Layout::new(root.clone());
        let _ = layout.ensure();
        let log = log::Log::new(root.join("hub.log"));
        let hub = Hub {
            layout,
            state: Mutex::new(HubState::default()),
            catalog: Mutex::new(catalog::embedded().expect("the embedded catalog must verify")),
            running: Mutex::new(BTreeMap::new()),
            probes: Mutex::new(BTreeMap::new()),
            installing: Mutex::new(BTreeSet::new()),
            hub_update: Mutex::new(None),
            repo_root: None,
            elevated: false,
            log,
        };
        (hub, root)
    }

    fn installed_at(path: &str) -> state::Installed {
        state::Installed {
            version: "1.0.0".into(),
            installed_at: state::now_iso(),
            sha256: "0".repeat(64),
            path: path.to_string(),
            previous: None,
        }
    }

    fn proc_at(pid: u32, exe: PathBuf) -> procs::Proc {
        procs::Proc {
            pid,
            parent: None,
            name: exe
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default(),
            exe: Some(exe),
        }
    }

    /// The case the interlock could not see, and the reason it now takes a
    /// snapshot.
    ///
    /// `Hub.running` is in memory, so a restart empties it. `apply_staged` runs
    /// at startup and asked only that map, which meant it applied a staged
    /// update over a tool the reader had left open -- the one thing the
    /// interlock exists to stop, at the one moment it was blindest.
    #[test]
    fn a_tool_left_open_across_a_restart_still_counts_as_running() {
        let (hub, root) = scratch_hub("running-after-restart");
        let dir = root.join("tools").join("forgepact").join("1.3.16");
        let exe = dir.join("ForgePact.exe");
        hub.state
            .lock()
            .unwrap()
            .installed
            .insert("forgepact".into(), installed_at(&dir.to_string_lossy()));

        // Nothing tracked: exactly the state after a restart.
        assert!(hub.running.lock().unwrap().is_empty());

        let elsewhere = procs::Snapshot::of(vec![proc_at(4242, root.join("other").join("thing.exe"))]);
        assert!(
            !tool_is_running(&hub, "forgepact", &elsewhere),
            "a process outside the install directory is not this tool"
        );

        let open = procs::Snapshot::of(vec![proc_at(4242, exe)]);
        assert!(
            tool_is_running(&hub, "forgepact", &open),
            "a process running out of the install directory is this tool, tracked or not"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    /// Two installs of one tool share a `.part` file and a staging directory.
    #[test]
    fn one_install_per_tool_and_the_claim_is_released() {
        let (hub, root) = scratch_hub("install-claim");
        let hub = Arc::new(hub);

        let first = InstallClaim::take(&hub, "forgepact").expect("the first claim is free");
        assert!(
            InstallClaim::take(&hub, "forgepact").is_err(),
            "a second install of the same tool must be refused"
        );
        InstallClaim::take(&hub, "hscraftsim").expect("a different tool is unaffected");

        drop(first);
        InstallClaim::take(&hub, "forgepact")
            .expect("the claim must be released on drop, or the tool is stuck until restart");

        let _ = std::fs::remove_dir_all(root);
    }

    /// The gap between deciding and acting.
    ///
    /// The interlock was read once, before a download that runs for minutes,
    /// and then not again -- so an install begun while the game was closed went
    /// on to overwrite it once the player had started it. `activate_or_stage`
    /// takes the answer as an argument precisely so the caller has to say when
    /// it asked, and every caller asks after its download.
    ///
    /// Being handed a blocked verdict *with the artifact already downloaded* is
    /// exactly the post-download moment, so this covers it: nothing is
    /// activated, the update waits, and the reason is on it.
    #[test]
    fn an_interlock_that_closes_during_the_download_stages_instead_of_activating() {
        let (hub, root) = scratch_hub("blocked-after-download");
        let hub = Arc::new(hub);
        let tool = hub
            .catalog
            .lock()
            .unwrap()
            .catalog
            .tools
            .first()
            .cloned()
            .expect("the embedded catalog has tools");

        // A path that could not possibly be installed from. Reaching
        // `install_artifact` at all would fail the test by failing on this.
        let artifact = root.join("downloaded.zip");

        let outcome = activate_or_stage(
            &hub,
            &tool,
            &artifact,
            &|_| {},
            Some("Hero Siege is running.".to_string()),
        );
        assert!(outcome.is_ok(), "a blocked update is not an error");

        let state = hub.state.lock().unwrap();
        assert!(
            !state.installed.contains_key(&tool.id),
            "nothing may be activated while the interlock is closed"
        );
        let waiting = state
            .staged
            .get(&tool.id)
            .expect("the downloaded artifact must be kept, not thrown away");
        assert_eq!(waiting.blocked_by, "Hero Siege is running.");
        assert_eq!(waiting.artifact_path, artifact.to_string_lossy());
        drop(state);

        let _ = std::fs::remove_dir_all(root);
    }

    /// The claim has to be held across the download, not just the activation.
    ///
    /// Every download of one tool writes the same `.part` file, so the download
    /// is the part that collides. The launch check took its claim after
    /// downloading, which left Update all free to start a second download into
    /// that same file.
    #[test]
    fn a_claim_held_across_a_download_blocks_a_second_one() {
        let (hub, root) = scratch_hub("claim-covers-download");
        let hub = Arc::new(hub);

        // What the launch check holds while its download runs.
        let downloading = InstallClaim::take(&hub, "forgepact").expect("the first claim is free");

        // What Update all does in the middle of it.
        assert!(
            InstallClaim::take(&hub, "forgepact").is_err(),
            "a second download of the same tool writes the same .part file"
        );

        drop(downloading);
        InstallClaim::take(&hub, "forgepact").expect("released once the first is done");

        let _ = std::fs::remove_dir_all(root);
    }

    /// Collect the phases an emitter is handed, in order.
    fn recorder() -> (impl Fn(install::Progress), Arc<Mutex<Vec<String>>>) {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&seen);
        let emit = move |progress: install::Progress| {
            let phase = match progress {
                install::Progress::Started { .. } => "started",
                install::Progress::Downloading { .. } => "downloading",
                install::Progress::Verifying { .. } => "verifying",
                install::Progress::Extracting { .. } => "extracting",
                install::Progress::Activating { .. } => "activating",
                install::Progress::Done { .. } => "done",
                install::Progress::Failed { .. } => "failed",
                install::Progress::Staged { .. } => "staged",
                install::Progress::Downloaded { .. } => "downloaded",
            };
            sink.lock().unwrap().push(phase.to_string());
        };
        (emit, seen)
    }

    fn installable_tool(hub: &Hub) -> catalog::Tool {
        hub.catalog
            .lock()
            .unwrap()
            .catalog
            .tools
            .iter()
            .find(|t| t.is_installable())
            .cloned()
            .expect("the embedded catalog has an installable tool")
    }

    /// A card shows itself busy from `Started` until a terminal event arrives.
    /// A staged install never sent one, so the card sat on *Verifying* with its
    /// button disabled until the hub was restarted -- and `library-changed`
    /// does not clear it, because the busy state takes priority over the staged
    /// state it would otherwise show.
    #[test]
    fn staging_ends_the_progress_stream_without_claiming_an_install() {
        let (hub, root) = scratch_hub("staged-terminal");
        let hub = Arc::new(hub);
        let tool = installable_tool(&hub);
        let (emit, seen) = recorder();

        activate_or_stage(
            &hub,
            &tool,
            &root.join("downloaded.zip"),
            &emit,
            Some("Hero Siege is running.".to_string()),
        )
        .expect("a blocked update is not an error");

        let phases = seen.lock().unwrap().clone();
        assert_eq!(
            phases,
            vec!["staged"],
            "staging must end the stream, and must not report itself as done"
        );
        assert!(
            install::Progress::Staged {
                id: tool.id.clone(),
                reason: String::new()
            }
            .is_terminal(),
            "and the frontend has to be able to tell that it ended"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    /// The same hole on the failure side: `install_artifact` does not emit
    /// `Failed` itself. The wrapper that used to do it was dropped when the
    /// orchestration moved here, so a failed install left the card on
    /// *Verifying* rather than offering Try again.
    #[test]
    fn a_failed_install_ends_its_stream_so_the_card_can_offer_a_retry() {
        let (hub, root) = scratch_hub("failed-terminal");
        let hub = Arc::new(hub);
        let tool = installable_tool(&hub);
        let (emit, seen) = recorder();

        // An artifact that is not there: `install_artifact` cannot hash it.
        let outcome = activate_or_stage(&hub, &tool, &root.join("missing.zip"), &emit, None);
        assert!(outcome.is_err(), "a missing artifact is a failure");

        let phases = seen.lock().unwrap().clone();
        assert_eq!(
            phases.last().map(String::as_str),
            Some("failed"),
            "the stream must end, or the button never comes back: {phases:?}"
        );
        assert!(
            !hub.state.lock().unwrap().installed.contains_key(&tool.id),
            "and nothing may be recorded as installed"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    /// The backstop, for the exits nobody thought about.
    ///
    /// Four of them lost their terminal event at once when orchestration moved
    /// out of `install::install`, which is the argument for not relying on
    /// remembering.
    #[test]
    fn a_stream_dropped_without_a_terminal_event_still_ends() {
        let (emit, seen) = recorder();
        {
            let stream = ProgressStream::new("forgepact", &emit);
            stream.emit(install::Progress::Started {
                id: "forgepact".into(),
                total: 10,
            });
        }
        assert_eq!(
            seen.lock().unwrap().clone(),
            vec!["started", "failed"],
            "an abandoned stream must fail rather than hang"
        );

        // And a stream that ended properly is not failed a second time.
        let (emit, seen) = recorder();
        {
            let stream = ProgressStream::new("forgepact", &emit);
            stream.emit(install::Progress::Downloaded {
                id: "forgepact".into(),
            });
        }
        assert_eq!(seen.lock().unwrap().clone(), vec!["downloaded"]);
    }

    /// A staged update that can never be applied has to be dropped, not
    /// retried.
    ///
    /// `install_artifact` verifies the artifact against the hash the catalog
    /// carries *now*. So if a tool releases again while its update sits behind
    /// a running game, the staged bytes are the old version's and the hash
    /// check fails -- on every startup, forever, with an error toast each time
    /// and nothing in the interface able to clear it. The same is true of an
    /// entry whose download has been cleared out of the cache.
    ///
    /// Dropping it leaves the tool showing "an update is available", which is
    /// both true and actionable.
    #[test]
    fn a_staged_update_that_can_never_apply_is_dropped_rather_than_retried() {
        let (hub, root) = scratch_hub("stale-staged");
        let tool = installable_tool(&hub);

        let entry = |version: &str, path: &std::path::Path| state::Staged {
            version: version.to_string(),
            artifact_path: path.to_string_lossy().to_string(),
            sha256: "0".repeat(64),
            staged_at: state::now_iso(),
            blocked_by: "Hero Siege is running.".into(),
        };

        let present = root.join("staged.zip");
        std::fs::write(&present, b"bytes").unwrap();

        // Applicable: the version still matches and the download is there.
        assert_eq!(
            unapplicable(&tool, &entry(&tool.version, &present)),
            None,
            "a staged update that can still be applied must be kept"
        );

        // The tool released again while this waited behind a running game.
        let stale = unapplicable(&tool, &entry("0.0.1-old", &present))
            .expect("a version the catalog has moved past can never pass its hash check");
        assert!(stale.contains(&tool.version) && stale.contains("0.0.1-old"), "{stale}");

        // The download was cleared out of the cache.
        let gone = unapplicable(&tool, &entry(&tool.version, &root.join("not-here.zip")))
            .expect("an entry whose artifact is gone can never be applied");
        assert!(gone.contains("cache"), "{gone}");

        let _ = std::fs::remove_dir_all(root);
    }

    /// The regression that prompted the threading work, pinned.
    ///
    /// `build_view` used to call `launch::already_running` per tool, which is a
    /// loopback connect. On a machine that does not refuse a closed port
    /// promptly -- this one, where a refusal takes two seconds -- each of the
    /// four tools that declare a health endpoint cost the probe's whole
    /// timeout, so one view took 2.8 s. It was built on the thread pumping the
    /// window's messages, on a ten-second poll, and the hub was therefore
    /// unresponsive about a third of the time it was open.
    ///
    /// 200 ms is deliberately generous against the ~25 ms the process snapshot
    /// actually costs, so this will not flake on a loaded runner. Anything near
    /// the budget means a probe has crept back onto this path, which is exactly
    /// how it got here the first time.
    #[test]
    fn building_the_view_never_touches_the_network() {
        let (hub, root) = scratch_hub("view-budget");
        let expected = hub.catalog.lock().unwrap().catalog.tools.len();

        let started = std::time::Instant::now();
        let view = build_view(&hub).expect("the view should build");
        let elapsed = started.elapsed();

        assert_eq!(view.tools.len(), expected);
        assert!(
            view.tools.iter().all(|tool| !tool.running_elsewhere),
            "an empty probe cache cannot report anything as running elsewhere"
        );
        assert!(
            elapsed < Duration::from_millis(200),
            "building the view took {elapsed:?}, over its 200 ms budget -- \
             something on this path is doing network work again"
        );

        let _ = std::fs::remove_dir_all(&root);
    }

    /// The other half of the same contract: the view does report what the
    /// ticker found, so moving the probe off this path did not drop the answer.
    #[test]
    fn the_view_reports_what_the_probe_cache_holds() {
        let (hub, root) = scratch_hub("probe-cache");
        let id = hub.catalog.lock().unwrap().catalog.tools[0].id.clone();
        hub.probes.lock().unwrap().insert(id.clone(), true);

        let view = build_view(&hub).expect("the view should build");
        let tool = view.tools.iter().find(|t| t.tool.id == id).unwrap();
        assert!(tool.running_pid.is_none());
        assert!(
            tool.running_elsewhere,
            "a cached probe answer is what tells the card a copy is already up"
        );

        let _ = std::fs::remove_dir_all(&root);
    }

    /// The card draws its own star, so the flag has to reach it on the tool it
    /// belongs to rather than as a list the frontend would have to cross-index.
    #[test]
    fn the_view_carries_the_star_on_the_tool_it_belongs_to() {
        let (hub, root) = scratch_hub("favorites");
        let id = hub.catalog.lock().unwrap().catalog.tools[0].id.clone();

        let view = build_view(&hub).expect("the view should build");
        assert!(
            view.tools.iter().all(|t| !t.favorite),
            "nothing is starred on a fresh install"
        );

        hub.state.lock().unwrap().set_favorite(&id, true);
        let view = build_view(&hub).expect("the view should build");
        let starred: Vec<&str> = view
            .tools
            .iter()
            .filter(|t| t.favorite)
            .map(|t| t.tool.id.as_str())
            .collect();
        assert_eq!(starred, vec![id.as_str()]);

        let _ = std::fs::remove_dir_all(&root);
    }

    /// A star for an id the catalog does not have is not an error and not a
    /// row: it simply matches nothing when the view is built.
    #[test]
    fn a_star_for_a_tool_that_left_the_catalog_shows_up_nowhere() {
        let (hub, root) = scratch_hub("favorites-ghost");
        hub.state.lock().unwrap().set_favorite("no-such-tool", true);

        let view = build_view(&hub).expect("the view should build");
        assert!(view.tools.iter().all(|t| !t.favorite));

        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn the_repo_root_is_found_from_inside_the_crate() {
        // The tests run with the working directory at hub/src-tauri, which is
        // two levels under the checkout.
        let root = find_repo_root(std::env::current_dir().unwrap());
        assert!(root.is_some(), "the toolkit checkout should be findable from here");
        assert!(root.unwrap().join("catalog/sources.toml").is_file());
    }

    #[test]
    fn a_directory_outside_any_checkout_has_no_repo_root() {
        assert!(find_repo_root(std::env::temp_dir()).is_none());
    }

    #[test]
    fn only_http_urls_are_openable() {
        for url in [
            "file:///C:/Windows/System32/calc.exe",
            "javascript:alert(1)",
            "ms-settings:",
            "\\\\server\\share",
        ] {
            assert!(
                !(url.starts_with("https://") || url.starts_with("http://")),
                "{url}"
            );
        }
    }

    /// A successful check that finds nothing newer replaces whatever was
    /// cached, the same as a check that never found anything in the first
    /// place -- a stale "v9.9.9 is available" must not survive a check that
    /// really did run and really did come back clean.
    #[test]
    fn hub_update_check_that_finds_nothing_newer_is_ok_none_and_clears_the_cache() {
        let (hub, root) = scratch_hub("hub-update-clears-cache");
        *hub.hub_update.lock().unwrap() = Some(HubUpdate {
            version: "9.9.9".into(),
            current_version: "1.0.2".into(),
        });

        let result = settle_hub_update_check(&hub, Ok(None));

        assert_eq!(result, Ok(None));
        assert_eq!(*hub.hub_update.lock().unwrap(), None);

        let _ = std::fs::remove_dir_all(&root);
    }

    /// A successful check that finds a release caches it, so every other
    /// screen reading `hub.hub_update` sees the same answer.
    #[test]
    fn hub_update_check_that_finds_a_release_caches_it() {
        let (hub, root) = scratch_hub("hub-update-caches-release");
        let found = HubUpdate {
            version: "1.0.3".into(),
            current_version: "1.0.2".into(),
        };

        let result = settle_hub_update_check(&hub, Ok(Some(found.clone())));

        assert_eq!(result, Ok(Some(found.clone())));
        assert_eq!(*hub.hub_update.lock().unwrap(), Some(found));

        let _ = std::fs::remove_dir_all(&root);
    }

    /// The bug in issue #44: a failed check with nothing cached must come
    /// back as an error, not as `Ok(None)`, which looks exactly like "checked
    /// and there is nothing newer".
    #[test]
    fn hub_update_check_that_fails_with_nothing_cached_is_an_error_not_no_update() {
        let (hub, root) = scratch_hub("hub-update-fails-empty-cache");

        let result = settle_hub_update_check(
            &hub,
            Err("Could not fetch a valid release JSON from the remote".into()),
        );

        assert_eq!(result, Err(HUB_UPDATE_CHECK_FAILED.to_string()));
        assert_eq!(*hub.hub_update.lock().unwrap(), None);

        let _ = std::fs::remove_dir_all(&root);
    }

    /// A failed check says nothing about whether a previously-found update
    /// went away, so the cache is left exactly as it was.
    #[test]
    fn hub_update_check_that_fails_keeps_the_cached_update() {
        let (hub, root) = scratch_hub("hub-update-fails-keeps-cache");
        let cached = HubUpdate {
            version: "1.0.3".into(),
            current_version: "1.0.2".into(),
        };
        *hub.hub_update.lock().unwrap() = Some(cached.clone());

        let result = settle_hub_update_check(&hub, Err("offline".into()));

        assert!(result.is_err());
        assert_eq!(*hub.hub_update.lock().unwrap(), Some(cached));

        let _ = std::fs::remove_dir_all(&root);
    }
}
