#!/usr/bin/env python3
"""x64dbg_mcp.py -- the `x64dbg` MCP server: logging breakpoints on the running modded game.

`.mcp.json` starts this as `py -3 -m tools.x64dbg_mcp`. It answers "does this
function fire, with what arguments, how often" on a live game, through
**non-breaking hardware logging breakpoints**, with no research build and no
relaunch. Underneath it are two pinned pieces, both kept outside every git
checkout:

- headless x64dbg, snapshot `2026.05.27` (`X64DBG_*` below), whose
  `release\\x64\\headless.exe` reads commands on stdin and prints its log on
  stdout;
- [AgentSmithers/x64DbgMCPServer](https://github.com/AgentSmithers/x64DbgMCPServer)
  at `PLUGIN_COMMIT`, an x64dbg plugin that serves MCP over HTTP from inside
  the debugger. That repository has **no LICENSE**, so none of its source is
  carried here: only its URL, its commit, and our two edits as `PLUGIN_EDITS`
  applies them (loopback bind; log lines with braces).

Why a stdio proxy rather than the plugin's own endpoint in `.mcp.json`: that
endpoint exists only while headless x64dbg runs, which is after `attach`,
mid-session, so a session that connected at start would have no tools; and it
exposes the plugin's whole surface (`StopDebug` ends the game, memory writes,
module dumps, software breakpoints, stepping, an arbitrary-command
pass-through) to every session, under Codex too, which has no tool allowlist.
`serve` registers exactly `LIVE_OPERATOR_TOOLS` and forwards to the plugin on
127.0.0.1 only, after checking that the plugin's `tools/list` carries the tool
and argument it is about to use. And because the plugin reports a command
"executed successfully" once it is queued, every tool that claims a breakpoint
exists reads it back from x64dbg's own `bplist` output first.

Subcommands (all paths overridable, see `load_config`):

    py -3 -m tools.x64dbg_mcp            # stdio MCP server (what .mcp.json runs)
    py -3 -m tools.x64dbg_mcp status     # paths, pins, what is missing, session, lease
    py -3 -m tools.x64dbg_mcp setup      # download, clone, edit, build, install
    py -3 -m tools.x64dbg_mcp attach --game | <pid>
    py -3 -m tools.x64dbg_mcp detach     # detach, then end headless x64dbg

`serve` prints nothing to stdout itself, starts no process and never launches
x64dbg: `attach` does, under a live hs-drive lease, through a detached
**keeper** process that is the only holder of headless's stdin for the whole
session. x64dbg pauses the game on attach, so the keeper sends `run` as soon as
the plugin answers a debug-only call. Teardown is `bphc`, `detach`, a
confirmation that no session remains, then `exit`; headless is never killed
while it may still be attached. In a live session, detach before `hs_stop_game`.

Anything x64dbg shows of the game's code is disassembly: it stays in the
session log and the gitignored live capture, never in a tracked file
(AGENTS.md § "Legal"), and an address found this way is a research finding
that never ships (AGENTS.md § "Never Call an Address You Resolved by Hand").
docs/tools/x64dbg-mcp.md is the operator's guide.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.decomp_index import git_tree_of  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# --- the pins ---------------------------------------------------------------

X64DBG_TAG = "2026.05.27"
X64DBG_ASSET = "snapshot_2026-05-27_12-11.zip"
X64DBG_URL = f"https://github.com/x64dbg/x64dbg/releases/download/{X64DBG_TAG}/{X64DBG_ASSET}"
# GitHub's asset digest, equal to the hash of the owner's downloaded copy.
X64DBG_SHA256 = "d41966dfc5b435a372798245300ca0ab7bb8e48bdbf48512c6fb20fcca427697"
# What the extracted tree's commithash.txt reads: the identity of an install.
X64DBG_COMMIT = "9c8ca1cae0b6d56cc44f31fddcb10e3b02ffbb87"

PLUGIN_URL = "https://github.com/AgentSmithers/x64DbgMCPServer.git"
PLUGIN_COMMIT = "a8303d7ac7bfd251b9da83b80c9d1d4407ddd8df"
PLUGIN_NAME = "x64DbgMCPServer"
PLUGIN_SOLUTION = "x64DbgMCPServer.sln"
PLUGIN_OUTPUT = Path("bin") / "x64" / "Release" / f"{PLUGIN_NAME}.dp64"
# The build's native-export step. Upstream's build skips it, and without it
# no .dp64 is produced.
PLUGIN_BUILD_TARGETS = "Build;RGieseckeDllExport"
DOTNET_SDK_MAJOR = 8

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 50300
GAME_IMAGE = "Hero_Siege.exe"
MCP_PROTOCOL_VERSION = "2025-06-18"

# The tools `serve` registers, as bare names. `live-operator` carries each as
# `mcp__x64dbg__<name>`, and no other agent carries any
# (tests/test_x64dbg_agent_tools.py). Breaking breakpoints, stepping,
# registers and call stacks are left out on purpose: each stops the game's
# loop (AGENTS.md § "Don't Suspend the Game's Own Runtime").
LIVE_OPERATOR_TOOLS = (
    "status",
    "logpoint",
    "command",
    "bplist",
    "log",
    "modules",
    "disasm",
    "detach",
)

# The plugin tools this proxy calls, with the argument names it passes. The
# names were read from the pinned commit's source; `PluginClient.call_checked`
# confirms each one against the live `tools/list` before forwarding.
PLUGIN_EXECUTE = "ExecuteDbgCommand"       # (command)
PLUGIN_MODULES = "GetAllModulesFromMemMap"  # ()
PLUGIN_DISASM = "ReadDismAtAddress"         # (address, byteCount)
PLUGIN_PAUSE = "PauseDebug"                 # ()
PLUGIN_RUN = "run"                          # ()

# What the plugin answers when x64dbg is not debugging anything: its call-time
# gate for a debug-only tool, and the tools' own early returns.
NO_SESSION_MARKERS = (
    "requires an active debug session",
    "no active debugging session",
    "not actively debugging",
    "not currently debugging",
)

# `command`'s allowlist: the hardware-breakpoint housekeeping a logpoint
# session needs, by x64dbg's own names and aliases (the aliases checked
# against the pinned snapshot's x64dbg.dll command table). Matched on the verb,
# case-insensitively. Adding a breakpoint is `logpoint`'s job, so `bph` and
# `SetHardwareBreakpoint` are not here.
COMMAND_ALLOWLIST = (
    "DeleteHardwareBreakpoint", "bphc", "bphwc",
    "EnableHardwareBreakpoint", "bphe", "bphwe",
    "DisableHardwareBreakpoint", "bphd", "bphwd",
    "SetHardwareBreakpointName", "bphwname",
    "SetHardwareBreakpointLogCondition", "bphwlogcondition",
    "ResetHardwareBreakpointHitCount",
    "GetHardwareBreakpointHitCount",
    "bplist",
)
_ALLOWED_VERBS = {v.lower() for v in COMMAND_ALLOWLIST}


@dataclass(frozen=True)
class SourceEdit:
    """One of our edits to the plugin: `upstream` becomes `ours` in `path`.

    Each fragment is one line, so an edit made on bytes keeps the file's line
    endings whichever they are (the owner's clone holds LF in a file git
    expects CRLF). The fragments are short identifiers and a single
    expression, not a copied body: the plugin has no LICENSE.
    """
    path: str
    upstream: bytes
    ours: bytes
    count: int
    why: str


PLUGIN_EDITS = (
    SourceEdit(
        "DotNetPlugin.Impl/McpServerConfig.cs",
        b'public string IpAddress { get; set; } = "+";',
        b'public string IpAddress { get; set; } = "127.0.0.1";',
        1, "listen on loopback by default, not on every interface"),
    SourceEdit(
        "DotNetPlugin.Impl/McpServerConfig.cs",
        b'config.IpAddress = "+";',
        b'config.IpAddress = "127.0.0.1";',
        1, "and on loopback when a loaded config's address is blank"),
    SourceEdit(
        "DotNetPlugin.Stub/NativeBindings/SDK/PLog.cs",
        b"Plugins._plugin_logprint(string.Format(format, args));",
        b"Plugins._plugin_logprint(args == null || args.Length == 0 ? format : string.Format(format, args));",
        1, "pass a log line through unformatted when it has no arguments, so '{' and '}' survive"),
)

SESSION_SCHEMA = "x64dbg-mcp-session/1"
# A session in one of these may still hold the game: refuse a second attach.
LIVE_STATES = ("attaching", "running", "detaching", "detach-unconfirmed")


class Refused(Exception):
    """A refusal with a named reason, reported rather than raised to the user."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


# --- configuration ----------------------------------------------------------

@dataclass
class Config:
    x64dbg: Path
    download: Path
    plugin_src: Path
    dotnet: Path | None
    session: Path
    port: int
    # Test seams, never set by `load_config`: what runs as headless x64dbg,
    # and how long the keeper waits for the plugin.
    headless_cmd: tuple[str, ...] | None = None
    ready_timeout: float = 60.0
    detach_timeout: float = 30.0
    settle: float = 1.5
    poll: float = 0.2

    @property
    def url(self) -> str:
        # The host is not configurable: the plugin is only ever reached on loopback.
        return f"http://{LOOPBACK}:{self.port}/"

    @property
    def headless(self) -> Path:
        return self.x64dbg / "release" / "x64" / "headless.exe"

    @property
    def headless_argv(self) -> list[str]:
        return list(self.headless_cmd) if self.headless_cmd else [str(self.headless)]

    @property
    def plugin_dir(self) -> Path:
        return self.x64dbg / "release" / "x64" / "plugins" / PLUGIN_NAME

    @property
    def installed_plugin(self) -> Path:
        return self.plugin_dir / f"{PLUGIN_NAME}.dp64"

    @property
    def plugin_config(self) -> Path:
        return self.plugin_dir / "mcp_config.json"

    @property
    def built_plugin(self) -> Path:
        return self.plugin_src / PLUGIN_OUTPUT

    @property
    def snapshot_zip(self) -> Path:
        return self.download / X64DBG_ASSET

    @property
    def state_file(self) -> Path:
        return self.session / "state.json"

    @property
    def log_file(self) -> Path:
        return self.session / "session.log"

    @property
    def keeper_log(self) -> Path:
        return self.session / "keeper.log"

    @property
    def keeper_config(self) -> Path:
        return self.session / "keeper-config.json"

    @property
    def requests(self) -> Path:
        return self.session / "requests"

    @property
    def replies(self) -> Path:
        return self.session / "replies"

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        for k, v in out.items():
            if isinstance(v, Path):
                out[k] = str(v)
        out["headless_cmd"] = list(self.headless_cmd) if self.headless_cmd else None
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Config":
        paths = ("x64dbg", "download", "plugin_src", "session")
        values = dict(data)
        for k in paths:
            values[k] = Path(values[k])
        values["dotnet"] = Path(values["dotnet"]) if values.get("dotnet") else None
        values["headless_cmd"] = tuple(values["headless_cmd"]) if values.get("headless_cmd") else None
        return cls(**values)


def load_config(env: dict[str, str] | None = None) -> Config:
    """Defaults follow the owner's existing layout under %USERPROFILE%\\tools;
    each has an environment override."""
    env = os.environ if env is None else env
    user = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    tools = user / "tools"
    dotnet = env.get("HS_X64DBG_DOTNET")
    return Config(
        x64dbg=Path(env.get("HS_X64DBG_DIR") or tools / "x64dbg"),
        download=Path(env.get("HS_X64DBG_DL_DIR") or tools / "x64dbg-dl"),
        plugin_src=Path(env.get("HS_X64DBG_MCP_SRC") or tools / "x64dbg-mcp-src"),
        dotnet=Path(dotnet) if dotnet else tools / "dotnet-sdk",
        session=Path(env.get("HS_X64DBG_MCP_SESSION") or tools / "x64dbg-mcp-session"),
        port=int(env.get("HS_X64DBG_MCP_PORT") or DEFAULT_PORT),
    )


def refuse_inside_git(path: Path, what: str) -> None:
    tree = git_tree_of(path)
    if tree is not None:
        raise SystemExit(
            f"x64dbg_mcp: refusing to use {path} as the {what}: {tree} is a git tree. "
            "x64dbg, the plugin's unlicensed source, the build and the session log (which "
            "holds disassembled game code) all stay outside every repository (AGENTS.md § Legal)."
        )


def written_directories(cfg: Config) -> list[tuple[Path, str]]:
    """Every directory a subcommand writes, as (path, what). The plugin clone is
    a git tree of its own by design, so its parent is what is checked."""
    return [
        (cfg.x64dbg, "x64dbg directory"),
        (cfg.download, "download directory"),
        (cfg.plugin_src.parent, "plugin source's parent directory"),
        (cfg.session, "session directory"),
    ]


# --- the offline guard ------------------------------------------------------

class OfflineGuardError(RuntimeError):
    """A connection off loopback, or a process nobody expected."""


_LOOPBACK_HOSTS = {LOOPBACK, "localhost", "::1"}


def install_offline_guard(allowed_executables: tuple[str, ...] | list[str] = ()) -> Callable[[], None]:
    """Fail any connection that is not to loopback, and any process whose
    executable is not in `allowed_executables`. Returns the uninstaller.

    `serve` runs under it with nothing allowed (it starts no process), and the
    keeper with only headless x64dbg allowed. The tests install it around
    every case, so no download, clone or build can run from a test by mistake.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    real_popen = subprocess.Popen

    def norm(p: str) -> str:
        return os.path.normcase(os.path.abspath(shutil.which(p) or p))

    allowed = {norm(p) for p in allowed_executables}

    def check_host(host: Any) -> None:
        if host is None:
            return
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name not in _LOOPBACK_HOSTS:
            raise OfflineGuardError(f"x64dbg_mcp offline guard: refusing a connection to {name!r}; "
                                    "only 127.0.0.1 is reachable from here")

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        return real_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        check_host(host)
        return real_getaddrinfo(host, *args, **kwargs)

    class GuardedPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **kw):
            exe = kw.get("executable") or (args if isinstance(args, (str, bytes, os.PathLike)) else args[0])
            if isinstance(args, str) or kw.get("shell") or norm(os.fspath(exe)) not in allowed:
                raise OfflineGuardError(f"x64dbg_mcp offline guard: refusing to start {args!r}; "
                                        f"allowed: {sorted(allowed) or 'nothing'}")
            super().__init__(args, *a, **kw)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    subprocess.Popen = GuardedPopen  # type: ignore[misc]

    def uninstall() -> None:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = real_getaddrinfo  # type: ignore[assignment]
        subprocess.Popen = real_popen  # type: ignore[misc]

    return uninstall


# --- our two plugin edits ---------------------------------------------------

class EditRefused(Exception):
    pass


def edit_bytes(data: bytes, edit: SourceEdit) -> tuple[bytes, str]:
    """(new bytes, "applied" | "already"). Refuses, naming the file, unless the
    upstream fragment occurs exactly `count` times, or not at all with our
    replacement there exactly `count` times."""
    up, ours = data.count(edit.upstream), data.count(edit.ours)
    if up == edit.count and ours == 0:
        return data.replace(edit.upstream, edit.ours), "applied"
    if up == 0 and ours == edit.count:
        return data, "already"
    raise EditRefused(
        f"{edit.path}: expected the upstream fragment {edit.upstream.decode()!r} {edit.count} time(s) "
        f"(found {up}) or our replacement {edit.count} time(s) (found {ours}); the file is not the "
        f"pinned commit {PLUGIN_COMMIT[:7]}, so nothing was edited")


def plan_edits(src: Path) -> dict[str, tuple[bytes, bytes, list[str]]]:
    """For each edited file: (old bytes, new bytes, outcome per edit). Reads only."""
    out: dict[str, tuple[bytes, bytes, list[str]]] = {}
    for edit in PLUGIN_EDITS:
        path = src / edit.path
        if edit.path not in out:
            if not path.is_file():
                raise EditRefused(f"{edit.path}: not found under {src}")
            data = path.read_bytes()
            out[edit.path] = (data, data, [])
        old, cur, outcomes = out[edit.path]
        cur, outcome = edit_bytes(cur, edit)
        out[edit.path] = (old, cur, outcomes + [outcome])
    return out


def apply_plugin_edits(src: Path) -> dict[str, list[str]]:
    """Apply `PLUGIN_EDITS` under `src`. Every edit is checked before any file
    is written, so a refusal leaves the tree as it was."""
    planned = plan_edits(src)
    for rel, (old, new, _) in planned.items():
        if new != old:
            (src / rel).write_bytes(new)
    return {rel: outcomes for rel, (_, _, outcomes) in planned.items()}


def expected_edited(blob: bytes, rel: str) -> bytes:
    data = blob
    for edit in PLUGIN_EDITS:
        if edit.path == rel:
            data, _ = edit_bytes(data, edit)
    return data


def _git(src: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(src), *args], capture_output=True, check=True).stdout


def dirty_beyond_our_edits(src: Path, git: Callable[..., bytes] | None = None) -> list[str]:
    """Paths in the clone's working tree changed by anything but our edits.

    An edited file passes when, line endings aside, it equals the pinned
    commit's copy or that copy with our edits applied.
    """
    git = git or _git
    porcelain = git(src, "status", "--porcelain=v1", "--untracked-files=all").decode("utf-8", "replace")
    ours = {e.path for e in PLUGIN_EDITS}
    bad = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if path not in ours or line[:2].strip() != "M":
            bad.append(path)
            continue
        blob = git(src, "show", f"{PLUGIN_COMMIT}:{path}")
        have = (src / path).read_bytes().replace(b"\r\n", b"\n")
        try:
            edited = expected_edited(blob, path).replace(b"\r\n", b"\n")
        except EditRefused:
            edited = None
        if have not in (blob.replace(b"\r\n", b"\n"), edited):
            bad.append(path)
    return bad


# --- build and install ------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", name))


def find_sdks_path(cfg: Config, run: Callable[..., Any] | None = None) -> Path | None:
    """`<sdk>/<8.x>/Sdks` of the newest .NET 8 SDK: the private install in
    `cfg.dotnet` first, then whatever `dotnet --list-sdks` names."""
    if cfg.dotnet is not None and (cfg.dotnet / "sdk").is_dir():
        found = [p for p in (cfg.dotnet / "sdk").iterdir()
                 if p.name.split(".")[0] == str(DOTNET_SDK_MAJOR) and (p / "Sdks").is_dir()]
        if found:
            return max(found, key=lambda p: _version_key(p.name)) / "Sdks"
    exe = shutil.which("dotnet")
    if exe is None:
        return None
    run = run or subprocess.run
    try:
        out = run([exe, "--list-sdks"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    best = None
    for line in out.splitlines():
        m = re.match(r"^\s*(\d+)\.(\S+)\s+\[(.+)\]\s*$", line)
        if m and m.group(1) == str(DOTNET_SDK_MAJOR):
            ver = f"{m.group(1)}.{m.group(2)}"
            sdks = Path(m.group(3)) / ver / "Sdks"
            if sdks.is_dir() and (best is None or _version_key(ver) > _version_key(best[0])):
                best = (ver, sdks)
    return best[1] if best else None


def vswhere_path(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    return Path(base) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


def find_msbuild(run: Callable[..., Any] | None = None) -> Path | None:
    vswhere = vswhere_path()
    if not vswhere.is_file():
        return None
    run = run or subprocess.run
    try:
        out = run([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.Component.MSBuild",
                   "-find", r"MSBuild\**\Bin\MSBuild.exe"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line.strip() and Path(line.strip()).is_file():
            return Path(line.strip())
    return None


def no_x96dbg_root(cfg: Config) -> Path:
    """Where the project's post-build xcopy is pointed: a path that does not
    exist, so the copy is skipped and the launcher installs by itself."""
    return cfg.plugin_src / "no-x96dbg-root"


def build_command(cfg: Config, msbuild: Path) -> list[str]:
    return [
        str(msbuild), str(cfg.plugin_src / PLUGIN_SOLUTION),
        "/restore", f"/t:{PLUGIN_BUILD_TARGETS}",
        "/p:Configuration=Release", "/p:Platform=x64",
        "/nologo", "/v:minimal",
    ]


def build_env(cfg: Config, sdks: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    root = no_x96dbg_root(cfg)
    if root.exists():
        raise SystemExit(f"x64dbg_mcp: {root} exists; the build's post-build step would copy into it")
    env = dict(os.environ if base is None else base)
    env["MSBuildSDKsPath"] = str(sdks)
    env["MSBuildEnableWorkloadResolver"] = "false"
    env["X96DBG_ROOT"] = str(root)
    return env


def build_prerequisites(cfg: Config) -> tuple[Path | None, Path | None, list[str]]:
    """(msbuild, sdks path, missing lines). Setup never installs either."""
    msbuild, sdks, missing = find_msbuild(), find_sdks_path(cfg), []
    if sdks is None:
        missing.append(f"no .NET {DOTNET_SDK_MAJOR} SDK in {cfg.dotnet} or on PATH (install one, e.g. with "
                       "dotnet-install.ps1 -Channel 8.0 -InstallDir <that path>, or set HS_X64DBG_DOTNET)")
    if msbuild is None:
        missing.append("no MSBuild found through vswhere (install Visual Studio Build Tools 2022 with "
                       "the MSBuild component)")
    return msbuild, sdks, missing


def built_is_current(cfg: Config) -> bool:
    if not cfg.built_plugin.is_file():
        return False
    built = cfg.built_plugin.stat().st_mtime
    return all(built >= (cfg.plugin_src / e.path).stat().st_mtime
               for e in PLUGIN_EDITS if (cfg.plugin_src / e.path).is_file())


def loopback_config(cfg: Config) -> dict[str, Any]:
    return {"IpAddress": LOOPBACK, "Port": cfg.port}


def install_plugin(cfg: Config) -> list[str]:
    """Copy the built .dp64 and write a loopback mcp_config.json: the two-file
    install the 2026-10-10 probe ran. Returns what it changed."""
    changed = []
    cfg.plugin_dir.mkdir(parents=True, exist_ok=True)
    if not cfg.installed_plugin.is_file() or _sha256(cfg.installed_plugin) != _sha256(cfg.built_plugin):
        shutil.copy2(cfg.built_plugin, cfg.installed_plugin)
        changed.append(str(cfg.installed_plugin))
    if read_plugin_config(cfg) != loopback_config(cfg):
        cfg.plugin_config.write_text(json.dumps(loopback_config(cfg), separators=(",", ":")), encoding="utf-8")
        changed.append(str(cfg.plugin_config))
    return changed


def read_plugin_config(cfg: Config) -> dict[str, Any] | None:
    try:
        data = json.loads(cfg.plugin_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def x64dbg_installed(cfg: Config) -> bool:
    try:
        commit = (cfg.x64dbg / "commithash.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return commit == X64DBG_COMMIT and cfg.headless.is_file()


def problems(cfg: Config) -> list[str]:
    """What is missing before `attach` can run, each with its fix."""
    fix = "run: py -3 -m tools.x64dbg_mcp setup"
    out = []
    if not x64dbg_installed(cfg):
        out.append(f"no x64dbg {X64DBG_TAG} (commit {X64DBG_COMMIT[:7]}) with headless.exe at {cfg.x64dbg} ({fix})")
    if not cfg.installed_plugin.is_file():
        out.append(f"no {PLUGIN_NAME} plugin at {cfg.installed_plugin} ({fix})")
    conf = read_plugin_config(cfg)
    if conf is None:
        out.append(f"no readable {cfg.plugin_config} ({fix})")
    elif conf.get("IpAddress") != LOOPBACK or conf.get("Port") != cfg.port:
        out.append(f"{cfg.plugin_config} has the plugin listen on {conf.get('IpAddress')}:{conf.get('Port')}, "
                   f"not {LOOPBACK}:{cfg.port} ({fix})")
    return out


# --- setup ------------------------------------------------------------------

def fetch_snapshot(cfg: Config) -> Path:
    out = cfg.snapshot_zip
    if not out.is_file() or _sha256(out) != X64DBG_SHA256:
        cfg.download.mkdir(parents=True, exist_ok=True)
        print(f"downloading {X64DBG_URL}")
        urllib.request.urlretrieve(X64DBG_URL, out)
    if _sha256(out) != X64DBG_SHA256:
        out.unlink()
        raise SystemExit(f"x64dbg_mcp: {X64DBG_ASSET} does not match its pinned sha256; refusing it")
    return out


def extract_snapshot(cfg: Config, archive: Path) -> None:
    marker = cfg.x64dbg / "commithash.txt"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() != X64DBG_COMMIT:
        raise SystemExit(f"x64dbg_mcp: {cfg.x64dbg} holds another x64dbg build; refusing to extract over it "
                         "(move it, or set HS_X64DBG_DIR)")
    cfg.x64dbg.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(cfg.x64dbg)
    if not x64dbg_installed(cfg):
        raise SystemExit(f"x64dbg_mcp: extracted {archive} but {cfg.headless} or its commithash is not as pinned")


def ensure_plugin_clone(cfg: Config, git: Callable[..., bytes] | None = None) -> str:
    git = git or _git
    src = cfg.plugin_src
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", PLUGIN_URL, str(src)], check=True)
        git(src, "checkout", "--detach", PLUGIN_COMMIT)
        return "cloned"
    if not (src / ".git").exists():
        raise SystemExit(f"x64dbg_mcp: {src} exists and is not a git clone; refusing to use it")
    head = git(src, "rev-parse", "HEAD").decode().strip()
    if head == PLUGIN_COMMIT:
        return "at the pinned commit"
    bad = dirty_beyond_our_edits(src, git)
    status = git(src, "status", "--porcelain=v1", "--untracked-files=all").decode("utf-8", "replace").strip()
    if bad or status:
        raise SystemExit(f"x64dbg_mcp: {src} is at {head[:7]}, not {PLUGIN_COMMIT[:7]}, with local changes "
                         f"({', '.join(bad) or status}); refusing to check out over them")
    git(src, "fetch", "origin")
    git(src, "checkout", "--detach", PLUGIN_COMMIT)
    return "checked out the pinned commit"


def setup(cfg: Config) -> int:
    for path, what in written_directories(cfg):
        refuse_inside_git(path, what)
    if x64dbg_installed(cfg):
        print(f"x64dbg {X64DBG_TAG}: present at {cfg.x64dbg}")
    else:
        extract_snapshot(cfg, fetch_snapshot(cfg))
        print(f"x64dbg {X64DBG_TAG}: extracted to {cfg.x64dbg}")
    print(f"plugin source: {ensure_plugin_clone(cfg)} ({cfg.plugin_src})")
    bad = dirty_beyond_our_edits(cfg.plugin_src)
    if bad:
        raise SystemExit(f"x64dbg_mcp: {cfg.plugin_src} has changes beyond our two edits: {', '.join(bad)}; "
                         "refusing to build it")
    try:
        for rel, outcomes in apply_plugin_edits(cfg.plugin_src).items():
            print(f"edit {rel}: {', '.join(outcomes)}")
    except EditRefused as e:
        raise SystemExit(f"x64dbg_mcp: {e}") from None
    if built_is_current(cfg):
        print(f"build: {cfg.built_plugin} is newer than the edited sources")
    else:
        msbuild, sdks, missing = build_prerequisites(cfg)
        if missing:
            print("still missing:\n  " + "\n  ".join(missing))
            return 1
        assert msbuild is not None and sdks is not None
        subprocess.run(build_command(cfg, msbuild), cwd=str(cfg.plugin_src), env=build_env(cfg, sdks), check=True)
        if not cfg.built_plugin.is_file():
            raise SystemExit(f"x64dbg_mcp: the build produced no {cfg.built_plugin}")
    changed = install_plugin(cfg)
    print("install: " + (", ".join(changed) if changed else "already current"))
    left = problems(cfg)
    print("ready" if not left else "still missing:\n  " + "\n  ".join(left))
    return 0 if not left else 1


# --- processes and the lease ------------------------------------------------

def _lease():
    from tools.hs_drive_mcp import lease
    return lease


def process_start(pid: int) -> Any:
    return _lease().process_start_for(pid)


def identity_of(pid: int) -> dict[str, Any]:
    return {"pid": pid, "pid_start": process_start(pid)}


def alive(identity: Any) -> bool:
    return bool(identity) and _lease().process_alive(identity)


def lease_state() -> tuple[str, str]:
    """("held" | "free" | "stale" | "unavailable", detail). Only "held" -- a
    record not released whose holder is still that process -- lets a tool act."""
    try:
        lease = _lease()
        record = lease.read_record("x64dbg")
    except Exception as exc:  # noqa: BLE001 - an unreadable lease is a state
        return "unavailable", f"the hs-drive lease could not be read ({type(exc).__name__}: {exc})"
    if record is None:
        return "free", f"no hs-drive lease record at {lease.record_path()}"
    if record.get("refused"):
        return "unavailable", str(record.get("detail"))
    if record.get("state") == lease.RELEASED:
        return "free", f"the hs-drive lease ({record.get('label')}) was released"
    holder = record.get("holder") or {}
    if lease.process_alive(holder):
        return "held", f"held by {record.get('label')} (pid {holder.get('pid')})"
    return "stale", f"the lease names {record.get('label')} (pid {holder.get('pid')}), which is no longer running"


def image_name(pid: int) -> str | None:
    """The executable's file name for `pid`, or None."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return Path(buf.value).name
        finally:
            k.CloseHandle(handle)
    try:
        return Path(os.readlink(f"/proc/{int(pid)}/exe")).name
    except OSError:
        return None


def all_pids() -> list[int]:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        arr = (wintypes.DWORD * 16384)()
        needed = wintypes.DWORD()
        if not ctypes.WinDLL("psapi").EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
            return []
        return [int(arr[i]) for i in range(needed.value // ctypes.sizeof(wintypes.DWORD)) if arr[i]]
    try:
        return [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return []


def game_pids() -> list[int]:
    return [pid for pid in all_pids() if (image_name(pid) or "").lower() == GAME_IMAGE.lower()]


# --- the session state file -------------------------------------------------

def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    for _ in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # a reader has it open on Windows
            time.sleep(0.02)
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any] | None:
    for _ in range(50):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (PermissionError, ValueError):
            time.sleep(0.02)
    return None


def read_state(cfg: Config) -> dict[str, Any]:
    state = read_json(cfg.state_file)
    if not state or state.get("schema") != SESSION_SCHEMA:
        return {"schema": SESSION_SCHEMA, "state": "none"}
    return state


def session_summary(cfg: Config) -> dict[str, Any]:
    state = read_state(cfg)
    return {
        "state": state.get("state", "none"),
        "target_pid": state.get("target_pid"),
        "keeper_alive": alive(state.get("keeper")),
        "headless_alive": alive(state.get("headless")),
        "ready": state.get("ready"),
        "detach_confirmed": state.get("detach_confirmed"),
        "error": state.get("error"),
        "log": str(cfg.log_file),
    }


def live_session(cfg: Config) -> dict[str, Any] | None:
    """The session that may still hold the game, or None."""
    state = read_state(cfg)
    if state.get("state") in LIVE_STATES and (alive(state.get("keeper")) or alive(state.get("headless"))):
        return state
    return None


# --- the plugin's MCP endpoint, on loopback ---------------------------------

class PluginError(RuntimeError):
    pass


class PluginMismatch(PluginError):
    """The plugin's tools/list lacks a tool or an argument the proxy would use."""


def parse_reply(body: bytes, content_type: str, want_id: Any) -> dict[str, Any]:
    """One JSON-RPC message from a reply that is JSON or SSE-framed."""
    text = body.decode("utf-8", "replace")
    if "text/event-stream" not in content_type.lower() and not text.lstrip().startswith(("data:", "event:")):
        return json.loads(text)
    messages, data = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                messages.append(json.loads("\n".join(data)))
            except ValueError:
                pass
            data = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("id") == want_id:
            return msg
    raise PluginError(f"no JSON-RPC reply with id {want_id} in the SSE stream")


class PluginClient:
    """A minimal streamable-HTTP MCP client for the plugin. It refuses any
    host but 127.0.0.1."""

    def __init__(self, url: str, timeout: float = 10.0):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "http" or parts.hostname != LOOPBACK or not parts.port:
            raise PluginError(f"refusing {url!r}: the plugin is only ever reached on http://{LOOPBACK}:<port>/")
        self.port = parts.port
        self.path = parts.path or "/"
        self.timeout = timeout
        self.session_id: str | None = None
        self._id = 0

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        conn = http.client.HTTPConnection(LOOPBACK, self.port, timeout=self.timeout)
        try:
            conn.request("POST", self.path, body=json.dumps(payload).encode("utf-8"), headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            sid = resp.getheader("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            if "id" not in payload:
                return None
            if resp.status != 200:
                raise PluginError(f"HTTP {resp.status} from the plugin: {body[:200]!r}")
            msg = parse_reply(body, resp.getheader("Content-Type") or "", payload["id"])
        except (OSError, http.client.HTTPException, ValueError) as e:
            raise PluginError(f"the plugin on {LOOPBACK}:{self.port} did not answer ({type(e).__name__}: {e})") from e
        finally:
            conn.close()
        if "error" in msg:
            raise PluginError(f"the plugin answered an error: {msg['error']}")
        return msg.get("result") or {}

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.session_id is None and method != "initialize":
            self.initialize()
        self._id += 1
        result = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        return result or {}

    def initialize(self) -> dict[str, Any]:
        result = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "x64dbg_mcp", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def list_tools(self) -> dict[str, dict[str, Any]]:
        return {t.get("name"): t for t in self._request("tools/list").get("tools", []) if isinstance(t, dict)}

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> tuple[str, bool]:
        """(text, is_error) of one tools/call."""
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        text = "\n".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        return text, bool(result.get("isError"))

    def call_checked(self, name: str, arguments: dict[str, Any] | None = None) -> tuple[str, bool]:
        """`call`, after confirming the live tools/list carries `name` with
        every argument name passed. A mismatch is refused, naming it."""
        tools = self.list_tools()
        if name not in tools:
            raise PluginMismatch(f"the plugin's tools/list does not carry {name!r} (it lists "
                                 f"{len(tools)} tools); not forwarding")
        props = ((tools[name].get("inputSchema") or {}).get("properties") or {})
        missing = [a for a in (arguments or {}) if a not in props]
        if missing:
            raise PluginMismatch(f"the plugin's {name!r} takes {sorted(props)}, not {missing}; not forwarding")
        return self.call(name, arguments)

    def debug_state(self) -> str:
        """"debugging" | "none" | "unknown", from a debug-only call. Not
        answering, or an unexpected answer, is "unknown", never "none"."""
        try:
            text, is_error = self.call(PLUGIN_MODULES)
        except PluginError:
            return "unknown"
        low = text.lower()
        if any(m in low for m in NO_SESSION_MARKERS):
            return "none"
        return "unknown" if is_error else "debugging"


# --- the keeper -------------------------------------------------------------

def _detached_flags() -> dict[str, Any]:
    """Popen arguments that let a process outlive the shell that started it:
    no console, its own process group, so no Ctrl event reaches it."""
    if os.name == "nt":
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def _headless_flags() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


class Keeper:
    """Holds headless x64dbg's stdin for the session's whole life, so nothing
    else can close it, and serves `send` and `detach` requests left as files
    in the session directory."""

    def __init__(self, cfg: Config, target_pid: int):
        self.cfg = cfg
        self.target_pid = target_pid
        self.plugin = PluginClient(cfg.url, timeout=5)
        self.proc: subprocess.Popen | None = None
        self.state: dict[str, Any] = {
            "schema": SESSION_SCHEMA, "state": "attaching", "target_pid": target_pid,
            "target": identity_of(target_pid), "keeper": identity_of(os.getpid()), "headless": None,
            "ready": None, "run_reply": None, "attach_logged": None, "detach_confirmed": None,
            "error": None, "started_utc": _utc(), "log": str(cfg.log_file),
        }

    def note(self, msg: str) -> None:
        print(f"{_utc()} {msg}", flush=True)

    def save(self, **changes: Any) -> None:
        self.state.update(changes, updated_utc=_utc())
        write_json(self.cfg.state_file, self.state)

    def send(self, line: str) -> None:
        if any(c in line for c in "\r\n"):
            raise ValueError("one command per line")
        assert self.proc is not None and self.proc.stdin is not None
        self.note(f"stdin: {line}")
        self.proc.stdin.write(line.encode("utf-8") + b"\n")
        self.proc.stdin.flush()

    def headless_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def log_text(self) -> str:
        try:
            return self.cfg.log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def run(self) -> int:
        self.save()
        argv = self.cfg.headless_argv
        cwd = str(Path(argv[0]).parent) if not self.cfg.headless_cmd else None
        with open(self.cfg.log_file, "ab") as log:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                         cwd=cwd, **_headless_flags())
        self.save(headless=identity_of(self.proc.pid))
        self.send(f"attach 0x{self.target_pid:X}")
        if not self.wait_ready():
            return self.finish()
        self.save(state="running")
        while self.state["state"] != "ended":
            self.serve_requests()
            if self.state["state"] == "ended":
                break
            if not self.headless_running():
                self.save(state="ended", error=f"headless x64dbg exited with {self.proc.returncode}")
                break
            if self.state["state"] == "running" and not alive(self.state["target"]):
                self.target_gone()
                break
            time.sleep(self.cfg.poll)
        return self.finish()

    def finish(self) -> int:
        self.note(f"keeper done: {self.state['state']} {self.state.get('error') or ''}")
        return 0 if self.state.get("detach_confirmed") else 1

    def wait_ready(self) -> bool:
        """Send `run` once the attach has completed: x64dbg pauses the game on
        attach, and a `run` sent before then fails and leaves it paused."""
        deadline = time.monotonic() + self.cfg.ready_timeout
        while time.monotonic() < deadline:
            if not self.headless_running():
                self.save(state="ended", error=f"headless x64dbg exited with {self.proc.returncode} during attach")
                return False
            if self.plugin.debug_state() == "debugging":
                break
            time.sleep(self.cfg.poll)
        else:
            # Never leave the game paused: run on stdin, and say readiness was not seen.
            self.send("run")
            self.save(state="running", ready=False, attach_logged="Attached" in self.log_text(),
                      error=f"the plugin did not answer a debug-only call within {self.cfg.ready_timeout:.0f}s; "
                            "sent run on stdin without it")
            return True
        reply = self.resume()
        self.save(ready=True, run_reply=reply, attach_logged="Attached" in self.log_text())
        return True

    def resume(self) -> str:
        """`run` through the plugin until it reports RUNNING twice, a settle
        apart (a late attach breakpoint would pause the game again); stdin
        `run` if the plugin never says so."""
        running, reply = 0, ""
        for _ in range(10):
            try:
                reply, _ = self.plugin.call(PLUGIN_RUN)
            except PluginError as e:
                reply = str(e)
            running = running + 1 if "RUNNING" in reply.upper() else 0
            if running >= 2:
                return reply
            time.sleep(self.cfg.settle if running else self.cfg.poll)
        self.send("run")
        return f"{reply} (and run on stdin)"

    def serve_requests(self) -> None:
        self.cfg.requests.mkdir(parents=True, exist_ok=True)
        self.cfg.replies.mkdir(parents=True, exist_ok=True)
        for req in sorted(self.cfg.requests.glob("*.json")):
            data = read_json(req) or {}
            try:
                req.unlink()
            except OSError:
                continue
            try:
                if data.get("op") == "send":
                    for line in data.get("lines", []):
                        self.send(str(line))
                    reply = {"ok": True, "sent": len(data.get("lines", []))}
                elif data.get("op") == "detach":
                    reply = self.teardown()
                else:
                    reply = {"ok": False, "detail": f"unknown op {data.get('op')!r}"}
            except Exception as e:  # noqa: BLE001 - reported to the requester
                reply = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
            write_json(self.cfg.replies / req.name, reply)

    def teardown(self) -> dict[str, Any]:
        """`bphc`, `detach`, confirm, `exit`. Only a confirmed detach lets the
        keeper end a headless that has not exited by itself."""
        self.save(state="detaching")
        self.send("bphc")
        self.send("detach")
        deadline = time.monotonic() + self.cfg.detach_timeout
        confirmed = False
        while time.monotonic() < deadline:
            if self.plugin.debug_state() == "none":
                confirmed = True
                break
            time.sleep(self.cfg.poll)
        if not confirmed:
            detail = (f"detach not confirmed within {self.cfg.detach_timeout:.0f}s: the plugin never reported "
                      f"that no session remains. Headless x64dbg (pid {self.proc.pid}) is left running and "
                      "was not killed; it may still be attached to the game. Retry detach, or look at "
                      f"{self.cfg.log_file}")
            self.save(state="detach-unconfirmed", detach_confirmed=False, error=detail)
            return {"ok": False, "state": "detach-unconfirmed", "detail": detail}
        self.send("exit")
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()  # the detach was confirmed, so nothing is attached any more
            self.proc.wait(timeout=10)
        self.save(state="ended", detach_confirmed=True, error=None)
        return {"ok": True, "state": "ended", "detail": "detached (confirmed), then headless x64dbg exited"}

    def target_gone(self) -> None:
        """The game exited under the debugger: nothing is attached any more."""
        self.send("exit")
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
        self.save(state="ended", error=f"the game (pid {self.target_pid}) exited while attached")


def keeper_main(session: Path, pid: int) -> int:
    data = read_json(session / "keeper-config.json")
    if data is None:
        print(f"x64dbg_mcp keeper: no keeper-config.json in {session}", file=sys.stderr)
        return 2
    cfg = Config.from_json(data)
    install_offline_guard(allowed_executables=(cfg.headless_argv[0],))
    return Keeper(cfg, pid).run()


def keeper_request(cfg: Config, op: str, timeout: float, **fields: Any) -> dict[str, Any]:
    """Leave a request for the keeper and wait for its reply."""
    state = read_state(cfg)
    if not alive(state.get("keeper")):
        raise Refused("keeper_gone", f"no live keeper for the session in {cfg.session} "
                                     f"(state {state.get('state')}, headless alive: {alive(state.get('headless'))})")
    cfg.requests.mkdir(parents=True, exist_ok=True)
    cfg.replies.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{uuid.uuid4().hex}.json"
    write_json(cfg.requests / name, {"op": op, **fields})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = read_json(cfg.replies / name)
        if reply is not None:
            try:
                (cfg.replies / name).unlink()
            except OSError:
                pass
            return reply
        time.sleep(0.05)
    raise Refused("keeper_timeout", f"the keeper did not answer {op!r} within {timeout:.0f}s")


# --- attach and detach (CLI) ------------------------------------------------

def attach(cfg: Config, pid: int | None, game: bool) -> int:
    """Start a session under the hs-drive lease. Refuses, naming why, unless
    the lease is live, the target is the game, x64dbg and the plugin are
    installed, and no session is live already."""
    try:
        state = start_session(cfg, pid, game)
    except Refused as r:
        print(f"x64dbg_mcp: attach refused ({r.reason}): {r.detail}")
        return 1
    print(json.dumps(session_summary(cfg)))
    return 0 if state.get("state") == "running" and state.get("ready") else 1


def start_session(cfg: Config, pid: int | None, game: bool) -> dict[str, Any]:
    held, detail = lease_state()
    if held != "held":
        raise Refused("no_lease", f"the hs-drive lease is {held}: {detail}. Take it with hs_lease_acquire first")
    if game:
        pids = game_pids()
        if len(pids) != 1:
            raise Refused("no_single_game", f"expected one running {GAME_IMAGE}, found {len(pids)}: {pids}")
        pid = pids[0]
    if pid is None:
        raise Refused("no_target", "name a pid, or --game")
    image = image_name(pid)
    if (image or "").lower() != GAME_IMAGE.lower():
        raise Refused("not_the_game", f"pid {pid} is {image or 'not a readable process'}, not {GAME_IMAGE}")
    missing = problems(cfg)
    if missing:
        raise Refused("not_installed", "; ".join(missing))
    live = live_session(cfg)
    if live is not None:
        raise Refused("session_live", f"a session is already {live.get('state')} on pid {live.get('target_pid')} "
                                      "(detach it first)")
    refuse_inside_git(cfg.session, "session directory")
    cfg.session.mkdir(parents=True, exist_ok=True)
    for d in (cfg.requests, cfg.replies):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
    if cfg.log_file.exists():
        os.replace(cfg.log_file, cfg.session / "session.prev.log")
    write_json(cfg.keeper_config, cfg.to_json())
    write_json(cfg.state_file, {"schema": SESSION_SCHEMA, "state": "attaching", "target_pid": pid,
                                "started_utc": _utc()})
    with open(cfg.keeper_log, "ab") as log:
        keeper = subprocess.Popen(
            [sys.executable, "-m", "tools.x64dbg_mcp", "keeper", "--session", str(cfg.session), "--pid", str(pid)],
            cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **_detached_flags())
    deadline = time.monotonic() + cfg.ready_timeout + 30
    while time.monotonic() < deadline:
        state = read_state(cfg)
        if state.get("keeper") and state.get("state") in ("running", "ended", "detach-unconfirmed"):
            return state
        if keeper.poll() is not None:
            break
        time.sleep(cfg.poll)
    state = read_state(cfg)
    if state.get("state") not in ("running",):
        state.setdefault("error", f"the keeper reported {state.get('state')}; see {cfg.keeper_log}")
    return state


def detach(cfg: Config) -> int:
    try:
        reply = keeper_request(cfg, "detach", timeout=cfg.detach_timeout + 30)
    except Refused as r:
        print(f"x64dbg_mcp: detach refused ({r.reason}): {r.detail}")
        return 1
    print(json.dumps(reply))
    state = read_state(cfg)
    return 0 if state.get("state") == "ended" and state.get("detach_confirmed") else 1


# --- the eight tools --------------------------------------------------------

_HEX = re.compile(r"^(?:0x)?([0-9A-Fa-f]+)$")
_MODULE_OFFSET = re.compile(r"^([^\s+]+)\+(?:0x)?([0-9A-Fa-f]+)$")
_MODULE_ROW = re.compile(r"^(\S+)\s.*?0x([0-9A-Fa-f]{8,16})\s+0x([0-9A-Fa-f]{8,16})\s+0x[0-9A-Fa-f]+\s*$")
_BPLIST_ROW = re.compile(r"^\s*\d+:[^:\s]+:([0-9A-Fa-f]+)(?::|\s|$)")


def command_refusal(command: str) -> str | None:
    """Why `command` is not allowed, or None."""
    text = command.strip()
    if not text:
        return "an empty command"
    if any(ord(c) < 0x20 for c in text):
        return "a control character (a newline would start a second command)"
    quoted = False
    for c in text:
        if c == '"':
            quoted = not quoted
        elif c == ";" and not quoted:
            return "a ';' outside a double-quoted string, which would chain a second command"
    if quoted:
        return "an unbalanced double quote"
    verb = re.match(r"[^\s,]+", text).group(0)  # type: ignore[union-attr]
    if verb.lower() not in _ALLOWED_VERBS:
        return (f"{verb!r} is not on the allowlist ({', '.join(COMMAND_ALLOWLIST)}). "
                "Add a breakpoint with the logpoint tool; nothing here stops, steps or writes the game")
    return None


def _text_refusal(value: str, what: str, forbid: str) -> str | None:
    if any(ord(c) < 0x20 for c in value):
        return f"{what} carries a control character"
    bad = [c for c in forbid if c in value]
    if bad:
        return f"{what} may not carry {' or '.join(repr(c) for c in bad)}"
    if len(value) > 512:
        return f"{what} is longer than 512 characters"
    return None


def _refusal(tool: str, reason: str, detail: str, **fields: Any) -> dict[str, Any]:
    return {"ok": False, "tool": tool, "refused": True, "reason": reason, "detail": detail, **fields}


class Tools:
    """The eight tools' behaviour, apart from MCP, so the tests can drive it."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.plugin = PluginClient(cfg.url)

    # gates

    def _gate(self, tool: str, need_lease: bool = True) -> dict[str, Any] | None:
        state = read_state(self.cfg)
        if state.get("state") != "running" or not alive(state.get("keeper")):
            return _refusal(tool, "not_attached",
                            f"no attached session (state {state.get('state')}); run "
                            "`py -3 -m tools.x64dbg_mcp attach --game` under the hs-drive lease first")
        if need_lease:
            held, detail = lease_state()
            if held != "held":
                return _refusal(tool, "no_lease", f"the hs-drive lease is {held}: {detail}")
        return None

    def _log_size(self) -> int:
        try:
            return self.cfg.log_file.stat().st_size
        except OSError:
            return 0

    def _log_after(self, offset: int) -> list[str]:
        try:
            with open(self.cfg.log_file, "rb") as f:
                f.seek(offset)
                return f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            return []

    def _stdin(self, lines: list[str]) -> dict[str, Any]:
        return keeper_request(self.cfg, "send", timeout=15, lines=lines)

    def _bplist_lines(self, wait_for: int | None = None) -> list[str]:
        """Send `bplist` on headless's stdin and return the log lines that
        followed it: until one names `wait_for`, or the settle time passed."""
        offset = self._log_size()
        self._stdin(["bplist"])
        deadline = time.monotonic() + max(self.cfg.settle, 3.0 if wait_for is not None else 0)
        lines: list[str] = []
        while time.monotonic() < deadline:
            time.sleep(min(0.1, self.cfg.settle))
            lines = self._log_after(offset)
            if wait_for is not None and _names_address(lines, wait_for):
                break
        return lines

    def _execute(self, command: str) -> str:
        text, is_error = self.plugin.call_checked(PLUGIN_EXECUTE, {"command": command})
        if is_error or text.lstrip().lower().startswith(("error", "exception")):
            raise PluginError(f"{command!r}: {text}")
        return text

    def _resume(self) -> str:
        try:
            text, _ = self.plugin.call_checked(PLUGIN_RUN)
            if "RUNNING" in text.upper():
                return text
        except PluginError as e:
            text = str(e)
        self._stdin(["run"])
        return f"{text} (and run on stdin)"

    def resolve(self, address: str) -> int:
        """An absolute address from `0x<hex>`, `<hex>` or `<module>+<hex>`;
        the module's base comes from the plugin's module list."""
        text = address.strip()
        m = _HEX.match(text)
        if m:
            return int(m.group(1), 16)
        m = _MODULE_OFFSET.match(text)
        if not m:
            raise Refused("bad_address", f"{address!r}: give 0x<hex>, <hex> or <module>+<hex offset> "
                                         f"(e.g. {GAME_IMAGE}+427460)")
        bases = module_bases(self.plugin.call_checked(PLUGIN_MODULES)[0])
        base = bases.get(m.group(1).lower())
        if base is None:
            raise Refused("no_such_module", f"{m.group(1)!r} is not in the plugin's module list")
        return base + int(m.group(2), 16)

    # the tools

    def status(self) -> dict[str, Any]:
        held, detail = lease_state()
        try:
            PluginClient(self.cfg.url, timeout=2).initialize()
            answers = True
        except PluginError:
            answers = False
        return {"ok": True, **session_summary(self.cfg), "plugin_answers": answers,
                "plugin_url": self.cfg.url, "lease": {"state": held, "detail": detail}}

    def logpoint(self, address: str, log: str, log_condition: str | None = None,
                 name: str | None = None) -> dict[str, Any]:
        tool = "logpoint"
        gate = self._gate(tool)
        if gate:
            return gate
        for value, what, forbid in ((log, "log", '"'), (log_condition, "log_condition", '";'),
                                    (name, "name", '";')):
            why = _text_refusal(value, what, forbid) if value is not None else None
            if why:
                return _refusal(tool, "bad_argument", why)
        try:
            addr = self.resolve(address)
        except Refused as r:
            return _refusal(tool, r.reason, r.detail)
        except PluginError as e:
            return _refusal(tool, "plugin", str(e))
        hexaddr = f"0x{addr:X}"
        steps: list[dict[str, str]] = []
        try:
            text, _ = self.plugin.call_checked(PLUGIN_PAUSE)
            steps.append({"step": "pause", "reply": text})
            if "paused" not in text.lower():
                raise PluginError(f"the game did not report paused: {text}")
        except PluginError as e:
            run = self._resume()
            return {"ok": False, "tool": tool, "stage": "pause", "detail": str(e), "address": hexaddr,
                    "steps": steps, "run": run}
        try:
            commands = [f"bph {hexaddr}, x, 1", f'SetHardwareBreakpointLog {hexaddr}, "{log}"']
            if log_condition:
                commands.append(f"SetHardwareBreakpointLogCondition {hexaddr}, {log_condition}")
            if name:
                commands.append(f'SetHardwareBreakpointName {hexaddr}, "{name}"')
            commands.append(f"SetHardwareBreakpointCondition {hexaddr}, 0")
            for c in commands:
                steps.append({"step": c, "reply": self._execute(c)})
            lines = self._bplist_lines(wait_for=addr)
            if not _names_address(lines, addr):
                raise PluginError(f"bplist did not name {hexaddr} after the plugin reported every step done "
                                  "(a queued command is not a set breakpoint)")
        except (PluginError, Refused) as e:
            cleared = ""
            try:
                cleared = self._execute(f"bphc {hexaddr}")
            except (PluginError, Refused) as e2:
                cleared = f"clearing failed: {e2}"
            run = self._resume()
            return {"ok": False, "tool": tool, "stage": "set", "detail": str(e), "address": hexaddr,
                    "steps": steps, "cleared": cleared, "run": run}
        run = self._resume()
        return {"ok": True, "tool": tool, "address": hexaddr, "steps": steps, "bplist": lines, "run": run}

    def command(self, command: str) -> dict[str, Any]:
        tool = "command"
        why = command_refusal(command)
        if why:
            return _refusal(tool, "not_allowed", f"refused: {why}")
        gate = self._gate(tool)
        if gate:
            return gate
        try:
            text, is_error = self.plugin.call_checked(PLUGIN_EXECUTE, {"command": command.strip()})
        except PluginError as e:
            return _refusal(tool, "plugin", str(e))
        return {"ok": not is_error, "tool": tool, "reply": text,
                "note": "the plugin reports a command done once it is queued; confirm with bplist"}

    def bplist(self) -> dict[str, Any]:
        gate = self._gate("bplist")
        if gate:
            return gate
        try:
            lines = self._bplist_lines()
        except Refused as r:
            return _refusal("bplist", r.reason, r.detail)
        return {"ok": True, "tool": "bplist", "lines": lines,
                "breakpoints": [ln for ln in lines if _BPLIST_ROW.match(ln)]}

    def log(self, after: int | None = None, limit: int = 200) -> dict[str, Any]:
        limit = max(1, min(int(limit), 5000))
        try:
            lines = self.cfg.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        total = len(lines)
        start = max(0, total - limit) if after is None else max(0, int(after))
        chunk = lines[start:start + limit]
        return {"ok": True, "tool": "log", "total": total, "first": start + 1, "lines": chunk,
                "log": str(self.cfg.log_file)}

    def modules(self) -> dict[str, Any]:
        gate = self._gate("modules")
        if gate:
            return gate
        try:
            text, is_error = self.plugin.call_checked(PLUGIN_MODULES)
        except PluginError as e:
            return _refusal("modules", "plugin", str(e))
        return {"ok": not is_error, "tool": "modules", "reply": text,
                "bases": {k: f"0x{v:X}" for k, v in module_bases(text).items()}}

    def disasm(self, address: str, byte_count: int = 64) -> dict[str, Any]:
        gate = self._gate("disasm")
        if gate:
            return gate
        try:
            addr = self.resolve(address)
            text, is_error = self.plugin.call_checked(
                PLUGIN_DISASM, {"address": f"0x{addr:X}", "byteCount": max(1, min(int(byte_count), 4096))})
        except Refused as r:
            return _refusal("disasm", r.reason, r.detail)
        except PluginError as e:
            return _refusal("disasm", "plugin", str(e))
        return {"ok": not is_error, "tool": "disasm", "address": f"0x{addr:X}", "reply": text,
                "note": "disassembled game code: paraphrase it, never paste it into a tracked file"}

    def detach(self) -> dict[str, Any]:
        # No lease check: detaching only gives the game back, and refusing it
        # would leave the debugger attached.
        gate = self._gate("detach", need_lease=False)
        if gate:
            return gate
        try:
            reply = keeper_request(self.cfg, "detach", timeout=self.cfg.detach_timeout + 30)
        except Refused as r:
            return _refusal("detach", r.reason, r.detail)
        return {"tool": "detach", **reply, **session_summary(self.cfg)}


def module_bases(text: str) -> dict[str, int]:
    """Lower-cased module name -> base, from GetAllModulesFromMemMap's table."""
    out = {}
    for line in text.splitlines():
        m = _MODULE_ROW.match(line.strip())
        if m:
            out[m.group(1).lower()] = int(m.group(2), 16)
    return out


def _names_address(lines: list[str], addr: int) -> bool:
    for line in lines:
        m = _BPLIST_ROW.match(line)
        if m and int(m.group(1), 16) == addr:
            return True
    return False


# --- serve ------------------------------------------------------------------

DESCRIPTIONS = {
    "status": "Session state (none, attaching, running, detaching, ended, detach-unconfirmed), target pid, "
              "keeper and headless alive, whether the plugin answers on 127.0.0.1, and the hs-drive lease.",
    "logpoint": "Add one non-breaking hardware logging breakpoint (bph, never breaks). address: 0x<hex> or "
                "<module>+<hex>, e.g. Hero_Siege.exe+427460. log: an x64dbg log format string, braces allowed, "
                "no double quote. Pauses the game for the set-up, reads bplist back, and always resumes it. "
                "Four hardware breakpoints at most: start with a positive control.",
    "command": "One allowlisted x64dbg command: delete, enable or disable a hardware breakpoint, name it, set "
               "its log condition, read or reset its hit count, or bplist. Anything else is refused.",
    "bplist": "Send bplist and return the log lines it produced (the only trustworthy breakpoint list; "
              "the plugin's GetBreakpointInfo is not).",
    "log": "Lines of the session log after line number `after` (default: the last `limit`), with the total "
           "line count, to page through logging-breakpoint hits.",
    "modules": "The debuggee's modules with their bases (gives Hero_Siege.exe's base).",
    "disasm": "Disassemble byte_count bytes at an address (0x<hex> or <module>+<hex>), to check an address "
              "against Ghidra. Disassembled game code: never paste it into a tracked file.",
    "detach": "Delete every hardware breakpoint, detach, confirm, then end headless x64dbg. Detach before "
              "hs_stop_game.",
}


def serve(cfg: Config) -> int:
    """stdio MCP. Prints nothing to stdout itself, starts no process, and never
    launches x64dbg: with no session every acting tool answers "not attached"."""
    install_offline_guard(allowed_executables=())
    from mcp.server.mcpserver import MCPServer  # only here: hub CI has no `mcp`

    tools = Tools(cfg)
    server = MCPServer("x64dbg", instructions=(
        "Logging breakpoints on the running modded game. Attach first with "
        "`py -3 -m tools.x64dbg_mcp attach --game` under the hs-drive lease; detach before hs_stop_game. "
        "See docs/tools/x64dbg-mcp.md."))

    def register(name: str, fn: Callable[..., dict[str, Any]]) -> None:
        server.tool(name=name, description=DESCRIPTIONS[name])(fn)

    def status() -> dict[str, Any]:
        return tools.status()

    def logpoint(address: str, log: str, log_condition: str | None = None, name: str | None = None) -> dict[str, Any]:
        return tools.logpoint(address, log, log_condition, name)

    def command(command: str) -> dict[str, Any]:
        return tools.command(command)

    def bplist() -> dict[str, Any]:
        return tools.bplist()

    def log(after: int | None = None, limit: int = 200) -> dict[str, Any]:
        return tools.log(after, limit)

    def modules() -> dict[str, Any]:
        return tools.modules()

    def disasm(address: str, byte_count: int = 64) -> dict[str, Any]:
        return tools.disasm(address, byte_count)

    def detach() -> dict[str, Any]:
        return tools.detach()

    handlers = {"status": status, "logpoint": logpoint, "command": command, "bplist": bplist, "log": log,
                "modules": modules, "disasm": disasm, "detach": detach}
    assert tuple(handlers) == LIVE_OPERATOR_TOOLS
    for name in LIVE_OPERATOR_TOOLS:
        register(name, handlers[name])
    server.run("stdio")
    return 0


# --- status and main --------------------------------------------------------

def status(cfg: Config) -> int:
    rows = [
        ("x64dbg", cfg.x64dbg), ("headless", cfg.headless), ("download", cfg.download),
        ("plugin_src", cfg.plugin_src), ("plugin", cfg.installed_plugin), ("session", cfg.session),
        ("plugin_url", cfg.url),
        ("x64dbg_pin", f"{X64DBG_TAG} {X64DBG_ASSET} commit {X64DBG_COMMIT[:7]}"),
        ("plugin_pin", f"{PLUGIN_URL} @ {PLUGIN_COMMIT}"),
    ]
    for k, v in rows:
        print(f"{k:15} {v}")
    conf = read_plugin_config(cfg)
    print(f"{'plugin_config':15} {conf if conf is not None else 'none'}")
    _, sdks, build_missing = build_prerequisites(cfg)
    print(f"{'dotnet_sdks':15} {sdks or 'none'}")
    for p in problems(cfg) + build_missing:
        print(f"missing        {p}")
    held, detail = lease_state()
    print(f"{'lease':15} {held} ({detail})")
    s = session_summary(cfg)
    print(f"{'session_state':15} {s['state']} target={s['target_pid']} keeper_alive={s['keeper_alive']} "
          f"headless_alive={s['headless_alive']}")
    try:
        PluginClient(cfg.url, timeout=2).initialize()
        print(f"{'plugin_answers':15} yes, on {cfg.url}")
    except PluginError:
        print(f"{'plugin_answers':15} no (nothing on {cfg.url}; it serves only while attached)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="x64dbg_mcp", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", metavar="{serve,status,setup,attach,detach}")
    sub.add_parser("serve", help="the stdio MCP server (the default; what .mcp.json runs)")
    sub.add_parser("status", help="paths, pins, what is missing, the session and the lease")
    sub.add_parser("setup", help="download, clone, edit, build and install, each step skipped when done")
    a = sub.add_parser("attach", help="attach headless x64dbg to the game under the hs-drive lease")
    a.add_argument("pid", nargs="?", type=int)
    a.add_argument("--game", action="store_true", help=f"the sole running {GAME_IMAGE}")
    sub.add_parser("detach", help="detach (confirmed), then end headless x64dbg")
    k = sub.add_parser("keeper")
    k.add_argument("--session", required=True, type=Path)
    k.add_argument("--pid", required=True, type=int)
    args = ap.parse_args(argv)
    if args.cmd == "keeper":
        return keeper_main(args.session, args.pid)
    cfg = load_config()
    if args.cmd in (None, "serve"):
        return serve(cfg)
    if args.cmd == "status":
        return status(cfg)
    if args.cmd == "setup":
        return setup(cfg)
    if args.cmd == "attach":
        if (args.pid is None) == (not args.game):
            ap.error("attach takes a pid or --game, not both")
        return attach(cfg, args.pid, args.game)
    return detach(cfg)


if __name__ == "__main__":
    sys.exit(main())
