//! `state.json`: what is installed, what the settings say, what is waiting.
//!
//! Written atomically -- to a sibling temp file and renamed -- because the thing
//! this file records is which directory a tool's `current.json` points at, and a
//! half-written state file after a power cut would lose the whole installed set.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// The master switch. With this on the hub makes no outbound request at
    /// all, including the launch check. HS-Offline-Tracker's About panel states
    /// the project's value plainly -- the check is "never something the app does
    /// on its own" -- and a hub whose job *is* distribution still owes the
    /// player an honest way out.
    pub work_offline: bool,
    /// Off by default, a security requirement: the hub checks for updates
    /// only when asked, unless the player opts in. Only a missing key takes
    /// this default, so a `state.json` that already says `true` keeps it.
    pub check_on_launch: bool,
    pub auto_download: bool,
    /// Nested under auto_download: installing without asking presupposes having
    /// the bytes without asking. The UI disables it when auto_download is off,
    /// and `effective_auto_install()` enforces the same thing here so a
    /// hand-edited state file cannot get past it.
    pub auto_install: bool,
    pub theme: String,
    /// None means `paths::default_install_root()`.
    pub install_root: Option<String>,
    /// Run tools from the checked-out submodules instead of installed copies.
    pub developer_mode: bool,
    /// Set once the first-run screen has been acknowledged. Until then the hub
    /// has not contacted anything.
    pub first_run_done: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            work_offline: false,
            check_on_launch: false,
            auto_download: false,
            auto_install: false,
            theme: "obsidian".to_string(),
            install_root: None,
            developer_mode: false,
            first_run_done: false,
        }
    }
}

impl Settings {
    /// Auto-install only means anything when auto-download is on.
    pub fn effective_auto_install(&self) -> bool {
        self.auto_download && self.auto_install
    }

    /// Is the hub allowed to make a request right now?
    pub fn may_reach_network(&self) -> bool {
        !self.work_offline && self.first_run_done
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Installed {
    pub version: String,
    pub installed_at: String,
    /// The artifact hash this version was installed from, so the detail view can
    /// show what was actually verified rather than what the catalog now says.
    pub sha256: String,
    /// Absolute path to the version directory.
    pub path: String,
    /// The version kept for rollback, if any.
    pub previous: Option<String>,
}

/// An update that was downloaded and verified but must not be applied yet.
///
/// The interlocks from D5: never install over a running tool, and never while
/// `Hero_Siege.exe` is up. ForgePact patches the game's PE and holds file IPC;
/// HSSaveEditor documents a game-closed requirement. Staging says so instead of
/// applying anyway.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Staged {
    pub version: String,
    /// The verified download, waiting in the cache.
    pub artifact_path: String,
    pub sha256: String,
    pub staged_at: String,
    /// Why it has not been applied, in words the Updates view can show.
    pub blocked_by: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct HubState {
    pub settings: Settings,
    pub installed: BTreeMap<String, Installed>,
    pub staged: BTreeMap<String, Staged>,
    pub last_check: Option<String>,
    /// Versions the user asked not to be updated past.
    pub pinned: BTreeMap<String, String>,
    /// Tools starred in the Library, which puts them in their own row above
    /// everything else.
    ///
    /// Ids rather than an ordering: the grid below is catalog order, and the
    /// starred row is the same order with the rest taken out. A set also means
    /// a tool that leaves the catalog leaves no ordering hole behind -- its id
    /// simply matches nothing when the view is built.
    pub favorites: BTreeSet<String>,
}

impl HubState {
    pub fn load(path: &Path) -> Self {
        let Ok(text) = std::fs::read_to_string(path) else {
            return Self::default();
        };
        match serde_json::from_str(&text) {
            Ok(state) => state,
            Err(error) => {
                // A state file we cannot read is not a reason to lose a player's
                // settings silently. Keep it beside the new one so it can be
                // looked at, and start clean rather than refusing to launch.
                let backup = path.with_extension("json.unreadable");
                let _ = std::fs::rename(path, &backup);
                eprintln!("state.json could not be read ({error}); moved to {backup:?}");
                Self::default()
            }
        }
    }

    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let text = serde_json::to_string_pretty(self)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
        let temp = path.with_extension("json.tmp");
        std::fs::write(&temp, text)?;
        // Windows' rename refuses to replace an existing file, so the old one
        // goes first. The window between the two is why `temp` is kept until the
        // rename lands rather than written in place.
        if path.exists() {
            std::fs::remove_file(path)?;
        }
        std::fs::rename(&temp, path)
    }

    pub fn is_installed(&self, id: &str) -> bool {
        self.installed.contains_key(id)
    }

    pub fn is_favorite(&self, id: &str) -> bool {
        self.favorites.contains(id)
    }

    /// Star or unstar a tool, and say whether that changed anything.
    ///
    /// The answer is what stops a click that changes nothing from costing a
    /// state write and a view rebuild -- starring is a click on a card, and the
    /// card is in a grid people drag a cursor across.
    pub fn set_favorite(&mut self, id: &str, favorite: bool) -> bool {
        if favorite {
            self.favorites.insert(id.to_string())
        } else {
            self.favorites.remove(id)
        }
    }
}

/// `current.json`, next to the version directories it arbitrates between.
///
/// Separate from `state.json` on purpose: this one travels with the tool's own
/// directory, so a hub whose state file is lost can still tell which of two
/// version directories is live.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Current {
    pub version: String,
    pub previous: Option<String>,
}

pub fn read_current(path: &Path) -> Option<Current> {
    serde_json::from_str(&std::fs::read_to_string(path).ok()?).ok()
}

pub fn write_current(path: &Path, current: &Current) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(
        path,
        serde_json::to_string_pretty(current)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?,
    )
}

pub fn now_iso() -> String {
    // Seconds since the epoch, rendered as UTC. Enough for "installed on", and
    // it avoids a date-time dependency for a field nobody does arithmetic on.
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    format_utc(secs)
}

fn format_utc(secs: i64) -> String {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (hour, minute, second) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    let (year, month, day) = civil_from_days(days);
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

/// Howard Hinnant's `civil_from_days`. Thirty lines of arithmetic instead of a
/// calendar crate, for one timestamp field.
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(tag: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "hub-state-{tag}-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn defaults_are_offline_friendly_and_never_install_behind_your_back() {
        let settings = Settings::default();
        assert!(!settings.work_offline);
        assert!(!settings.check_on_launch);
        assert!(!settings.auto_download);
        assert!(!settings.auto_install);
        assert!(!settings.first_run_done);
        // Nothing may be fetched before the first-run screen has been seen.
        assert!(!settings.may_reach_network());
    }

    #[test]
    fn auto_install_without_auto_download_does_nothing() {
        let mut settings = Settings {
            auto_install: true,
            ..Settings::default()
        };
        assert!(!settings.effective_auto_install());
        settings.auto_download = true;
        assert!(settings.effective_auto_install());
    }

    #[test]
    fn launch_check_is_off_unless_the_state_file_turns_it_on() {
        let fresh: Settings = serde_json::from_str("{}").unwrap();
        assert!(!fresh.check_on_launch);
        let opted_in: Settings = serde_json::from_str(r#"{"check_on_launch":true}"#).unwrap();
        assert!(opted_in.check_on_launch);
    }

    #[test]
    fn work_offline_beats_everything_else() {
        let mut settings = Settings {
            first_run_done: true,
            ..Settings::default()
        };
        assert!(settings.may_reach_network());
        settings.work_offline = true;
        assert!(!settings.may_reach_network());
    }

    #[test]
    fn state_round_trips_through_the_file() {
        let dir = temp_dir("roundtrip");
        let path = dir.join("state.json");
        let mut state = HubState::default();
        state.settings.theme = "ember".into();
        state.installed.insert(
            "forgepact".into(),
            Installed {
                version: "1.3.16".into(),
                installed_at: now_iso(),
                sha256: "a".repeat(64),
                path: "C:/x".into(),
                previous: None,
            },
        );
        state.save(&path).unwrap();
        let reloaded = HubState::load(&path);
        assert_eq!(reloaded.settings.theme, "ember");
        assert_eq!(reloaded.installed["forgepact"].version, "1.3.16");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn stars_survive_a_restart_and_a_second_star_is_not_a_change() {
        let dir = temp_dir("favorites");
        let path = dir.join("state.json");
        let mut state = HubState::default();
        assert!(state.set_favorite("forgepact", true));
        // Already starred, so nothing to write and nothing to announce.
        assert!(!state.set_favorite("forgepact", true));
        state.save(&path).unwrap();

        let mut reloaded = HubState::load(&path);
        assert!(reloaded.is_favorite("forgepact"));
        assert!(reloaded.set_favorite("forgepact", false));
        assert!(!reloaded.is_favorite("forgepact"));
        assert!(!reloaded.set_favorite("forgepact", false));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn a_state_file_written_before_stars_existed_still_loads() {
        let dir = temp_dir("no-favorites-field");
        let path = dir.join("state.json");
        std::fs::write(&path, r#"{"settings":{"theme":"ember"},"installed":{}}"#).unwrap();
        let state = HubState::load(&path);
        assert_eq!(state.settings.theme, "ember");
        assert!(state.favorites.is_empty());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn saving_twice_replaces_rather_than_failing_on_windows() {
        let dir = temp_dir("replace");
        let path = dir.join("state.json");
        let state = HubState::default();
        state.save(&path).unwrap();
        state.save(&path).expect("a second save must overwrite");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn an_unreadable_state_file_is_preserved_and_the_hub_starts_clean() {
        let dir = temp_dir("corrupt");
        let path = dir.join("state.json");
        std::fs::write(&path, "{ this is not json").unwrap();
        let state = HubState::load(&path);
        assert!(state.installed.is_empty());
        assert!(
            path.with_extension("json.unreadable").exists(),
            "the unreadable file should have been kept"
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn a_missing_state_file_is_just_a_first_run() {
        let state = HubState::load(Path::new("C:/nope/state.json"));
        assert!(!state.settings.first_run_done);
    }

    #[test]
    fn timestamps_render_as_iso_utc() {
        assert_eq!(format_utc(0), "1970-01-01T00:00:00Z");
        assert_eq!(format_utc(1_757_620_800), "2025-09-11T20:00:00Z");
        assert_eq!(format_utc(951_782_400), "2000-02-29T00:00:00Z");
        let now = now_iso();
        assert_eq!(now.len(), 20, "{now}");
        assert!(now.ends_with('Z'));
    }
}
