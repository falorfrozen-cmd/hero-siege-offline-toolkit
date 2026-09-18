//! The catalog: its shape, where it comes from, and what it takes to be believed.
//!
//! Resolution order is bundle, then cache, then the copy compiled in. The
//! network is consulted only when the settings allow it and something asks. A
//! hub that has never been online still shows a full library, because the
//! embedded catalog was generated at build time.

use std::io::Read as _;
use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::verify;

/// Which repository this build trusts for its catalog, its own updates, and its
/// documentation links.
///
/// One value rather than four literals, because the four have to agree. They
/// once did not: the hub fetched from a fork while the release-notification
/// template told tool repositories to notify the canonical repository, so a new
/// release would rebuild one catalog while every installed hub read another.
///
/// Worse than a broken link, had it merged upstream: every upstream user's hub
/// would have fetched its catalog and its own updates from a personal fork's
/// release assets.
///
/// `hub-release.yml` sets `HUB_REPO` from the repository running the workflow,
/// so whichever repository publishes a hub builds one that points back at
/// itself -- a fork's release checks the fork, the canonical release checks the
/// canonical repository, and neither needs a source edit. The default is what a
/// local `cargo build` gets.
pub const HUB_REPO: &str = match option_env!("HUB_REPO") {
    Some(repo) => repo,
    None => "falorfrozen-cmd/hero-siege-offline-toolkit",
};

/// Where a signed catalog is published. The pair of files lives on a release
/// tag rather than in the repository tree so that regenerating the catalog does
/// not require a commit to be pushed before clients can see it.
pub fn catalog_url() -> String {
    format!("https://github.com/{HUB_REPO}/releases/download/catalog/catalog.json")
}

pub fn catalog_signature_url() -> String {
    format!("https://github.com/{HUB_REPO}/releases/download/catalog/catalog.json.minisig")
}

/// The developer guide for a tool, in whichever repository this hub came from.
/// Built here rather than in the interface so the frontend holds no opinion
/// about which repository that is.
pub fn guide_url(guide: &str) -> Option<String> {
    let guide = guide.trim();
    if guide.is_empty() {
        return None;
    }
    Some(format!("https://github.com/{HUB_REPO}/blob/main/{guide}"))
}

/// The catalog this hub was built with. Also the answer when every other source
/// fails, which is why "Work offline" is a usable setting rather than a broken
/// one.
pub const EMBEDDED_CATALOG: &str = include_str!("../../../catalog/catalog.json");
pub const EMBEDDED_SIGNATURE: &str = include_str!("../../../catalog/catalog.json.minisig");

pub const SCHEMA: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Catalog {
    pub schema: u32,
    pub generated: String,
    pub tools: Vec<Tool>,
    #[serde(default)]
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tool {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub summary: String,
    pub repo: String,
    #[serde(default)]
    pub submodule: String,
    pub version: String,
    #[serde(default)]
    pub tag: String,
    #[serde(default)]
    pub published: String,
    #[serde(default)]
    pub license: String,
    pub requires: Requires,
    pub artifact: Artifact,
    pub launch: Launch,
    #[serde(default)]
    pub source_launch: Option<SourceLaunch>,
    #[serde(default)]
    pub notes_url: String,
    #[serde(default)]
    pub notes: String,
    #[serde(default)]
    pub guide: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Requires {
    #[serde(default)]
    pub admin: bool,
    #[serde(default)]
    pub game_closed: bool,
    #[serde(default)]
    pub game_running: bool,
    #[serde(default = "default_true")]
    pub windows_only: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Artifact {
    pub kind: String,
    pub name: String,
    pub url: String,
    #[serde(default)]
    pub size: u64,
    pub sha256: String,
    #[serde(default)]
    pub sha256_source: String,
    #[serde(default)]
    pub strip_prefix: String,
    /// `exe`/`nsis` only: the stable filename to save the download under.
    #[serde(default)]
    pub install_as: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Launch {
    #[serde(default)]
    pub exe: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default)]
    pub elevate: bool,
    #[serde(default)]
    pub ports: Vec<u16>,
    #[serde(default)]
    pub health: Option<Health>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Health {
    pub url: String,
    #[serde(default = "default_timeout")]
    pub timeout_s: u64,
    /// HS Offline Launcher answers an unauthenticated probe with 401/403 because
    /// it binds a per-process HMAC token. Any status proves it is listening,
    /// which is the whole question.
    #[serde(default)]
    pub any_status: bool,
}

fn default_timeout() -> u64 {
    20
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceLaunch {
    pub cmd: String,
    #[serde(default)]
    pub args: Vec<String>,
}

impl Catalog {
    pub fn parse(text: &str) -> Result<Self, String> {
        let catalog: Catalog =
            serde_json::from_str(text).map_err(|e| format!("catalog is not valid JSON: {e}"))?;
        if catalog.schema != SCHEMA {
            return Err(format!(
                "catalog declares schema {} but this hub understands {SCHEMA}. Update the hub.",
                catalog.schema
            ));
        }
        Ok(catalog)
    }

    pub fn tool(&self, id: &str) -> Option<&Tool> {
        self.tools.iter().find(|t| t.id == id)
    }
}

impl Tool {
    /// `kind: "html"` is opened in a browser rather than spawned, so it has no
    /// process and never shows as Running.
    pub fn is_document(&self) -> bool {
        self.artifact.kind == "html"
    }

    /// `nsis` artifacts are installers the hub deliberately does not run: it
    /// installs per-user into its own tree and never hands control to a setup
    /// program that would put files somewhere else.
    pub fn is_installable(&self) -> bool {
        self.artifact.kind != "nsis"
    }

    pub fn is_archive(&self) -> bool {
        matches!(self.artifact.kind.as_str(), "zip" | "html")
    }
}

/// Which source the catalog in hand actually came from. Shown in the status bar,
/// because "catalog 3m ago" means something different when it is the embedded
/// copy from the day the hub was built.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    Remote,
    Cache,
    Bundle,
    Embedded,
}

#[derive(Debug, Clone, Serialize)]
pub struct LoadedCatalog {
    pub catalog: Catalog,
    pub source: Source,
    /// The signature's trusted comment, which is covered by its own signature.
    pub trusted_comment: String,
}

/// Parse and verify a catalog/signature pair. Verification is not optional: an
/// unsigned or badly signed catalog is refused rather than downgraded to a
/// warning, because the pinned hashes inside it are the only integrity story the
/// unsigned tool binaries have.
pub fn accept(payload: &[u8], signature: &str, source: Source) -> Result<LoadedCatalog, String> {
    let trusted_comment = verify::verify_catalog(payload, signature).map_err(|e| e.to_string())?;
    let text = std::str::from_utf8(payload).map_err(|e| format!("catalog is not UTF-8: {e}"))?;
    Ok(LoadedCatalog {
        catalog: Catalog::parse(text)?,
        source,
        trusted_comment,
    })
}

/// The catalog compiled into this build. Verified like any other: if the build
/// embedded a catalog and a signature that disagree, that is a broken hub and it
/// should say so on startup rather than the first time it matters.
pub fn embedded() -> Result<LoadedCatalog, String> {
    accept(
        EMBEDDED_CATALOG.as_bytes(),
        EMBEDDED_SIGNATURE,
        Source::Embedded,
    )
}

fn read_pair(json: &Path, sig: &Path, source: Source) -> Option<LoadedCatalog> {
    let payload = std::fs::read(json).ok()?;
    let signature = std::fs::read_to_string(sig).ok()?;
    accept(&payload, &signature, source).ok()
}

/// The best catalog available without touching the network.
///
/// Bundle first so an offline install uses what shipped with it; then the last
/// verified download; then the embedded copy. A file that fails verification is
/// skipped rather than fatal -- the next source down is still trustworthy.
pub fn load_local(bundle_dir: &Path, cached: &Path, cached_sig: &Path) -> LoadedCatalog {
    let bundle = read_pair(
        &bundle_dir.join("catalog.json"),
        &bundle_dir.join("catalog.json.minisig"),
        Source::Bundle,
    );
    if let Some(loaded) = bundle {
        return loaded;
    }
    if let Some(loaded) = read_pair(cached, cached_sig, Source::Cache) {
        return loaded;
    }
    embedded().unwrap_or_else(|e| {
        // Unreachable in a correctly built hub; a test in verify.rs fails first.
        panic!("the embedded catalog did not verify: {e}");
    })
}

/// Fetch and verify the published catalog. One request for the catalog and one
/// for its signature -- the whole point of D3 is that this is not ten.
pub fn fetch_remote(timeout: Duration) -> Result<(Vec<u8>, String), String> {
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(10))
        .timeout(timeout)
        .user_agent(concat!("hero-siege-toolkit-hub/", env!("CARGO_PKG_VERSION")))
        .build();

    let mut payload = Vec::new();
    agent
        .get(&catalog_url())
        .call()
        .map_err(|e| format!("could not fetch the catalog: {e}"))?
        .into_reader()
        // A signed catalog is a few tens of kilobytes. The cap is here so a
        // redirect to something enormous cannot fill a disk before the
        // signature gets a chance to reject it.
        .take(4 * 1024 * 1024)
        .read_to_end(&mut payload)
        .map_err(|e| format!("could not read the catalog: {e}"))?;

    let signature = agent
        .get(&catalog_signature_url())
        .call()
        .map_err(|e| format!("could not fetch the catalog signature: {e}"))?
        .into_string()
        .map_err(|e| format!("could not read the catalog signature: {e}"))?;

    Ok((payload, signature))
}


#[cfg(test)]
mod tests {
    use super::*;

    fn loaded() -> LoadedCatalog {
        embedded().expect("the embedded catalog must verify")
    }

    #[test]
    fn the_repo_is_the_override_when_set_and_the_canonical_one_otherwise() {
        // Both halves matter, so both are asserted rather than one being
        // skipped. Unset: a build must not point users at somebody's fork --
        // the assertion that would have caught the four hardcoded
        // `S-Borkowski/...` URLs before they could reach upstream. Set: the
        // override must actually reach the constant, which also exercises
        // `cargo:rerun-if-env-changed=HUB_REPO` in build.rs, since without it a
        // cached build would answer with the previous value.
        match option_env!("HUB_REPO") {
            Some(repo) => assert_eq!(HUB_REPO, repo),
            None => assert_eq!(HUB_REPO, "falorfrozen-cmd/hero-siege-offline-toolkit"),
        }
    }

    #[test]
    fn every_url_is_built_from_the_one_constant() {
        for url in [catalog_url(), catalog_signature_url()] {
            assert!(url.starts_with("https://github.com/"), "{url}");
            assert!(url.contains(HUB_REPO), "{url} does not use HUB_REPO");
        }
        assert!(catalog_url().ends_with("/catalog/catalog.json"));
        assert!(catalog_signature_url().ends_with(".minisig"));
        // The signature must sit beside the catalog it covers.
        assert_eq!(
            catalog_signature_url(),
            format!("{}.minisig", catalog_url())
        );
    }

    #[test]
    fn a_guide_path_becomes_a_link_and_an_empty_one_does_not() {
        let url = guide_url("docs/submodules/ForgePact/instructions.md").unwrap();
        assert_eq!(
            url,
            format!("https://github.com/{HUB_REPO}/blob/main/docs/submodules/ForgePact/instructions.md")
        );
        assert_eq!(guide_url(""), None);
        assert_eq!(guide_url("   "), None);
    }

    #[test]
    fn every_tool_in_the_catalog_yields_a_guide_link() {
        for tool in &loaded().catalog.tools {
            assert!(
                guide_url(&tool.guide).is_some(),
                "{} has no developer guide",
                tool.id
            );
        }
    }

    #[test]
    fn the_embedded_catalog_has_not_been_line_ending_converted() {
        // The signature covers the file's exact bytes. `core.autocrlf` is on by
        // default on Windows, including GitHub's windows runners, so a fresh
        // clone there rewrote catalog.json with CRLF and produced a catalog the
        // hub refuses -- and the symptom was fourteen signature failures that
        // named everything except the cause. `.gitattributes` marks these files
        // `-text`; this is the assertion that says so if that ever stops
        // working, in one line instead of fourteen.
        // Compared as a byte so there is no escape sequence in this source
        // for a line-ending conversion to eat -- which is how the first
        // attempt at this test broke.
        assert!(
            !EMBEDDED_CATALOG.as_bytes().contains(&b'\r'),
            "catalog.json contains CR: it has been line-ending converted, so its \n             signature can no longer verify. Check that .gitattributes still marks \n             catalog/catalog.json as -text."
        );
    }

    #[test]
    fn the_embedded_catalog_parses_and_verifies() {
        let loaded = loaded();
        assert_eq!(loaded.source, Source::Embedded);
        assert_eq!(loaded.catalog.schema, SCHEMA);
        assert_eq!(loaded.catalog.tools.len(), 11);
    }

    #[test]
    fn every_tool_has_a_pinned_hash_and_an_https_url() {
        for tool in &loaded().catalog.tools {
            assert_eq!(tool.artifact.sha256.len(), 64, "{}", tool.id);
            assert!(
                tool.artifact.url.starts_with("https://"),
                "{} downloads over {}",
                tool.id,
                tool.artifact.url
            );
        }
    }

    #[test]
    fn the_three_memory_tools_are_the_ones_that_elevate() {
        let catalog = loaded().catalog;
        let elevating: Vec<&str> = catalog
            .tools
            .iter()
            .filter(|t| t.launch.elevate)
            .map(|t| t.id.as_str())
            .collect();
        assert_eq!(
            elevating,
            vec!["hs-value-editor", "hs-offline-loot-forge", "hs-stat-forge"]
        );
        for tool in catalog.tools.iter().filter(|t| t.launch.elevate) {
            assert!(tool.requires.admin, "{} elevates without requiring admin", tool.id);
        }
    }

    #[test]
    fn the_steam_deck_editor_is_the_only_document_and_the_only_cross_platform_one() {
        let catalog = loaded().catalog;
        let documents: Vec<&str> = catalog
            .tools
            .iter()
            .filter(|t| t.is_document())
            .map(|t| t.id.as_str())
            .collect();
        assert_eq!(documents, vec!["hssaveeditor-steamdeck"]);
        for tool in &catalog.tools {
            assert_eq!(
                tool.requires.windows_only,
                !tool.is_document(),
                "{}",
                tool.id
            );
        }
    }

    #[test]
    fn a_tool_can_be_looked_up_by_id() {
        let catalog = loaded().catalog;
        assert_eq!(catalog.tool("forgepact").unwrap().name, "ForgePact");
        assert!(catalog.tool("no-such-tool").is_none());
    }

    #[test]
    fn a_future_schema_is_refused_rather_than_half_understood() {
        let err = Catalog::parse(r#"{"schema": 99, "generated": "", "tools": []}"#).unwrap_err();
        assert!(err.contains("99"), "{err}");
    }

    #[test]
    fn a_tampered_catalog_is_not_accepted() {
        let mut payload = EMBEDDED_CATALOG.as_bytes().to_vec();
        payload[10] ^= 0x20;
        assert!(accept(&payload, EMBEDDED_SIGNATURE, Source::Remote).is_err());
    }

    #[test]
    fn local_loading_falls_back_to_the_embedded_copy_when_nothing_is_on_disk() {
        let nowhere = Path::new("C:/this/path/does/not/exist");
        let loaded = load_local(nowhere, &nowhere.join("c.json"), &nowhere.join("c.minisig"));
        assert_eq!(loaded.source, Source::Embedded);
    }
}
