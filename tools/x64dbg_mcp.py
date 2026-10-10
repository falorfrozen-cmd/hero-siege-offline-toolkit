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
    py -3 -m tools.x64dbg_mcp tool <name> ['<json object of arguments>']
                                         # one of the eight tools from a shell

`serve` prints nothing to stdout itself, starts no process and never launches
x64dbg: `attach` does, under a live hs-drive lease, through a detached
**keeper** process that is the only holder of headless's stdin for the whole
session. The keeper keeps the game running, and reads x64dbg's state only
from the `[STATE] <name>` lines headless prints in the session log, never from
the plugin's `run` or `PauseDebug` answers (`PauseDebug` is asynchronous, and
both answers read a flag x64dbg's own breakpoint handling flips). x64dbg holds
the game at its attach break; the keeper resumes it on stdin once the plugin
answers a debug-only call and that break has been seen, then resumes every
later pause x64dbg takes on its own (its TLS-callback breakpoints, a late
break), counting each. Nothing here asks x64dbg to pause. A change to hardware
breakpoints while one of them logs is made with the game held at a breaking
hit of that one and resumed at once (a "held change", `Keeper.hold`). The
outside check, `tools/thread_state.py`, reads the game's threads from the OS
before attach, at the attach break (where it must read the game frozen: the
instrument's control), after the resume and after detach. Teardown is a held
`bphc`, a settle at running, `detach`, a confirmation that no session remains,
`exit`, then that outside check: a detach that left game threads suspended
ends `game-not-released`, naming them, and only a force-stop of the game
releases them. Headless is never killed while it may still be attached. In a
live session, detach before `hs_stop_game`.

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
import inspect
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
from typing import Any, Callable, Iterable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import thread_state  # noqa: E402
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
PLUGIN_MODULES = "GetAllModulesFromMemMap"  # ()
PLUGIN_DISASM = "ReadDismAtAddress"         # (address, byteCount)
# Named only so the tests can show they are never called. Every command goes
# on headless's stdin instead of through ExecuteDbgCommand (which redirects
# x64dbg's whole log around each call); `PauseDebug` is asynchronous (its
# pause lands whenever a thread next reaches it, Live 2); and the `run` and
# `PauseDebug` answers read a flag x64dbg's own breakpoint handling flips.
PLUGIN_EXECUTE = "ExecuteDbgCommand"       # (command)
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
# `SetHardwareBreakpoint` are not here. Nor is `GetHardwareBreakpointHitCount`:
# it sets `$result` and, as far as is known, prints nothing, so it would
# answer ok with no number. Count hits from the log instead (a counter field
# in the logpoint's log string, docs/tools/x64dbg-mcp.md).
COMMAND_ALLOWLIST = (
    "DeleteHardwareBreakpoint", "bphc", "bphwc",
    "EnableHardwareBreakpoint", "bphe", "bphwe",
    "DisableHardwareBreakpoint", "bphd", "bphwd",
    "SetHardwareBreakpointName", "bphwname",
    "SetHardwareBreakpointLogCondition", "bphwlogcondition",
    "ResetHardwareBreakpointHitCount",
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
# `attach-unconfirmed`: within the ready timeout the keeper did not see all of
# the plugin answering, x64dbg's attach break, x64dbg settled at running and
# the outside check reading the game running; the keeper keeps resuming every
# pause and promotes the session once it has, and only `detach` is served
# meanwhile.
LIVE_STATES = ("attaching", "attach-unconfirmed", "running", "detaching", "detach-unconfirmed")
# Where a keeper stops. `game-not-released`: the detach was confirmed, but the
# outside check found game threads still suspended or stopped. Nothing but a
# force-stop of the game releases them.
TERMINAL_STATES = ("ended", "game-not-released")


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
    # what answers the outside check of the game (run with the pid appended,
    # printing a `tools/thread_state.py` check as JSON; None reads the OS in
    # this process), and how long the keeper waits for each thing.
    headless_cmd: tuple[str, ...] | None = None
    probe_cmd: tuple[str, ...] | None = None
    ready_timeout: float = 60.0
    detach_timeout: float = 30.0
    settle: float = 1.5
    poll: float = 0.2
    # A hold's wait for its end marker, and each wait for x64dbg to settle at
    # running.
    hold_timeout: float = 10.0

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
        for k in ("headless_cmd", "probe_cmd"):
            out[k] = list(getattr(self, k)) if getattr(self, k) else None
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Config":
        paths = ("x64dbg", "download", "plugin_src", "session")
        values = dict(data)
        for k in paths:
            values[k] = Path(values[k])
        values["dotnet"] = Path(values["dotnet"]) if values.get("dotnet") else None
        for k in ("headless_cmd", "probe_cmd"):
            values[k] = tuple(values[k]) if values.get(k) else None
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
    """The session at a glance: what `attach` prints and `status` carries.
    `x64dbg_state` is x64dbg's own settled state from its `[STATE]` lines;
    `breaks_resumed`, `last_break` and `break_storm` report the pauses the
    keeper resumed; `instrument` is the outside check's control."""
    state = read_state(cfg)
    out = {
        "state": state.get("state", "none"),
        "target_pid": state.get("target_pid"),
        "keeper_alive": alive(state.get("keeper")),
        "headless_alive": alive(state.get("headless")),
        "ready": state.get("ready"),
        "detach_confirmed": state.get("detach_confirmed"),
        "x64dbg_state": state.get("x64dbg_state"),
        "breaks_resumed": state.get("breaks_resumed"),
        "last_break": state.get("last_break"),
        "break_storm": state.get("break_storm"),
        "instrument": state.get("instrument"),
        "error": state.get("error"),
        "log": str(cfg.log_file),
    }
    for k in ("paused_at_detach", "game_released"):
        if k in state:
            out[k] = state[k]
    return out


def game_check(cfg: Config, pid: int, baseline: Iterable[int] = ()) -> dict[str, Any]:
    """The outside check of the game's threads (`tools/thread_state.py`):
    read from the OS in this process, or, when the tests set
    `cfg.probe_cmd`, that command's JSON. Read-only either way. Anything the
    seam prints that is not a check is `unreadable`, never `running`."""
    if not cfg.probe_cmd:
        return thread_state.check(int(pid), baseline=baseline)
    try:
        r = subprocess.run([*cfg.probe_cmd, str(int(pid))], capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout)
        if isinstance(data, dict) and data.get("verdict") in thread_state.VERDICTS:
            return data
        why = f"no verdict in {r.stdout[:200]!r}"
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        why = f"{type(e).__name__}: {e}"
    return {"verdict": "unreadable", "threads": 0, "progress": 0, "suspended": [], "stopped": [],
            "samples": 0, "interval": 0.0, "detail": f"pid {pid}: the probe seam answered no check ({why})."}


def check_tids(check: dict[str, Any] | None) -> list[int]:
    """The threads a check found suspended or stopped."""
    if not check:
        return []
    tids = {int(s["tid"]) for s in check.get("suspended") or [] if isinstance(s, dict) and "tid" in s}
    return sorted(tids | {int(t) for t in check.get("stopped") or []})


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


# --- x64dbg's own state, from the session log --------------------------------

_STATE_LINE = re.compile(r"^\[STATE\]\s+(\w+)")
# The lines x64dbg prints for a break (read from x64dbg 9c8ca1c's source,
# docs/tools/x64dbg-mcp.md): a pause that landed, a software breakpoint (its
# own TLS-callback ones among them), a hardware breakpoint that broke, and a
# hit on a breakpoint x64dbg no longer lists.
_BREAK_LINE = re.compile(r"^(?:paused!|INT3 breakpoint\b|Hardware breakpoint \(|Breakpoint reached not in list!)")
MARKER_PREFIX = "x64dbg_mcp"


def batch_marker(hid: str, name: str) -> str:
    """A batch marker: the text `log "<text>"` prints on its own line. It
    carries no comma, because x64dbg splits a command's arguments on commas
    and a second argument would make the text a format string."""
    return f"{MARKER_PREFIX} {hid} {name}"


class SessionLog:
    """x64dbg's own state, its break lines and the keeper's batch markers,
    read from headless's session log. Headless prints every log message
    there, unbuffered, with no gap during a plugin call, and reading it
    changes nothing.

    x64dbg prints `[STATE] <name>` (`initialized`, `paused`, `running`,
    `stopped`) for every debug-state change, once at once and again within
    about 300 ms, and a non-breaking logpoint hit prints none. So the last
    `[STATE]` line, once `QUIET` seconds pass with no new one, is x64dbg's
    settled state. Each change into `paused` is one pause, numbered from 1,
    with its break line: the last of `_BREAK_LINE`'s lines since the last
    `[STATE]` line, or failing those the line just before."""

    QUIET = 0.4
    HISTORY = 64

    def __init__(self, path: Path, offset: int = 0):
        self.path = path
        self.offset = offset
        self._partial = b""
        self.first = 0  # the number of lines read before lines[0]
        self.lines: list[str] = []
        self.state: str | None = None
        self.state_at = 0.0  # monotonic time the latest [STATE] line was read
        self.pauses = 0
        self.pause_lines: dict[int, dict[str, Any]] = {}
        self._break: str | None = None
        self._prev: str | None = None

    def poll(self) -> list[str]:
        """Read the complete lines written since the last poll."""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read()
        except OSError:
            return []
        if not data:
            return []
        self.offset += len(data)
        chunks = (self._partial + data).split(b"\n")
        self._partial = chunks.pop()
        new = [c.rstrip(b"\r").decode("utf-8", "replace") for c in chunks]
        for line in new:
            self._take(line.strip())
        self.lines.extend(new)
        return new

    def _take(self, text: str) -> None:
        m = _STATE_LINE.match(text)
        if not m:
            if _BREAK_LINE.match(text):
                self._break = text
            if text:
                self._prev = text
            return
        name = m.group(1).lower()
        if name == "paused" and self.state != "paused":
            self.pauses += 1
            self.pause_lines[self.pauses] = {"line": self._break or self._prev, "utc": _utc()}
            self.pause_lines.pop(self.pauses - self.HISTORY, None)
        self.state, self.state_at = name, time.monotonic()
        self._break = None

    def settled(self) -> str | None:
        """x64dbg's settled state, or None while a change may still follow."""
        self.poll()
        if self.state is None or time.monotonic() - self.state_at < self.QUIET:
            return None
        return self.state

    def settled_for(self, name: str) -> float:
        """How long x64dbg's state has read `name` with no new [STATE] line,
        or -1 when it does not read `name`."""
        self.poll()
        return time.monotonic() - self.state_at if self.state == name else -1.0

    def pause_line(self, n: int | None = None) -> dict[str, Any] | None:
        """Pause `n`'s break line and the time it was read (the latest pause by default)."""
        return self.pause_lines.get(self.pauses if n is None else n)

    def mark(self) -> int:
        self.poll()
        return self.first + len(self.lines)

    def since(self, mark: int) -> list[str]:
        """The lines read after `mark`."""
        self.poll()
        return self.lines[max(0, mark - self.first):]

    def breaks_since(self, mark: int) -> list[str]:
        return [ln.strip() for ln in self.since(mark) if _BREAK_LINE.match(ln.strip())]

    def forget(self) -> None:
        """Drop the lines read so far; the state and the pauses stay."""
        self.first += len(self.lines)
        self.lines = []


class Keeper:
    """Holds headless x64dbg's stdin for the session's whole life, so nothing
    else can close it; keeps the game running; and serves `send`, `hold` and
    `detach` requests left as files in the session directory."""

    # x64dbg must read running this long, with no new [STATE] line, before an
    # attach is done.
    ATTACH_STABLE = 1.0
    # A `run` the keeper sent that brought no new [STATE] line within this
    # long is sent again, for the same pause.
    RESEND = 2.0
    # A held change waits this long for an armed breakpoint to break.
    HOLD_BREAK = 2.0
    # This many resumes within this many seconds are a storm.
    STORM_COUNT = 10
    STORM_WINDOW = 10.0

    def __init__(self, cfg: Config, target_pid: int):
        self.cfg = cfg
        self.target_pid = target_pid
        self.retry_at = 0.0
        self.plugin = PluginClient(cfg.url, timeout=5)
        self.proc: subprocess.Popen | None = None
        self.log = SessionLog(cfg.log_file)
        self.plugin_ok = False
        self.attach_pause: int | None = None
        # The pause the keeper's last `run` was for, and when it was sent.
        self.resumed_pause = 0
        self.resumed_at = 0.0
        self.resumes: list[float] = []
        self.state: dict[str, Any] = {
            "schema": SESSION_SCHEMA, "state": "attaching", "target_pid": target_pid,
            "target": identity_of(target_pid), "keeper": identity_of(os.getpid()), "headless": None,
            "ready": None, "attach_logged": None, "detach_confirmed": None,
            "x64dbg_state": None, "breaks_resumed": 0, "last_break": None, "break_storm": False,
            "instrument": {"before_attach": read_state(cfg).get("baseline"), "attach_break": None,
                           "after_resume": None, "proven": False},
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
        while self.state["state"] not in TERMINAL_STATES:
            self.serve_requests()
            if self.state["state"] in TERMINAL_STATES:
                break
            if not self.headless_running():
                self.save(state="ended", error=f"headless x64dbg exited with {self.proc.returncode}")
                break
            live = self.state["state"] in ("running", "attach-unconfirmed")
            if live and not alive(self.state["target"]):
                self.target_gone()
                break
            if self.state["state"] == "attach-unconfirmed" and self.attach_pause is None:
                self.see_attach_break()
            if live:
                self.watchdog()
            if self.state["state"] == "attach-unconfirmed":
                self.promote()
            self.log.forget()
            time.sleep(self.cfg.poll)
        return self.finish()

    def finish(self) -> int:
        self.note(f"keeper done: {self.state['state']} {self.state.get('error') or ''}")
        return 0 if self.state.get("detach_confirmed") else 1

    def check(self) -> dict[str, Any]:
        """The outside check of the game, leaving out the threads that were
        already suspended or stopped before attach."""
        return game_check(self.cfg, self.target_pid, baseline=check_tids(self.state["instrument"]["before_attach"]))

    def set_instrument(self, **checks: Any) -> None:
        """Record checks in `instrument`. It is proven only for the sequence
        running before attach, frozen at the attach break, running after the
        resume: an instrument that cannot see the held game tells nothing by
        reading the game running later."""
        inst = {**self.state["instrument"], **checks}
        verdicts = [(inst.get(k) or {}).get("verdict") for k in ("before_attach", "attach_break", "after_resume")]
        inst["proven"] = verdicts == ["running", "frozen", "running"]
        inst.pop("note", None)
        if inst.get("attach_break") is not None and verdicts[1] != "frozen":
            inst["note"] = (f"the outside check read the game {verdicts[1]}, not frozen, at x64dbg's attach break, "
                            "where x64dbg holds it: it did not see a held game, so its running verdicts in this "
                            "session prove nothing")
        self.save(instrument=inst)

    def see_attach_break(self) -> None:
        """Note x64dbg's attach break (the first `[STATE] paused` after
        `attach`) and take the outside check while the game is held there.
        Its `run` is the keeper's own, so the watchdog sends it uncounted."""
        self.log.poll()
        if self.attach_pause is not None or not self.log.pauses:
            return
        self.attach_pause = 1
        self.resumed_pause, self.resumed_at = self.attach_pause, 0.0
        self.set_instrument(attach_break=self.check())

    def wait_ready(self) -> bool:
        """Attach. Wait for the plugin to answer a debug-only call and for
        x64dbg's attach break, take the outside check there (frozen is
        expected), send `run` on stdin, resume every further pause until
        x64dbg has read running for ATTACH_STABLE seconds, and check the game
        again. Only then is the session `running`."""
        deadline = time.monotonic() + self.cfg.ready_timeout
        while True:
            if not self.headless_running():
                self.save(state="ended", error=f"headless x64dbg exited with {self.proc.returncode} during attach")
                return False
            self.see_attach_break()
            if not self.plugin_ok:
                self.plugin_ok = self.plugin.debug_state() == "debugging"
            if (self.plugin_ok and self.attach_pause) or time.monotonic() >= deadline:
                break
            time.sleep(self.cfg.poll)
        self.save(attach_logged="Attached" in self.log_text())
        if not (self.plugin_ok and self.attach_pause):
            self.unconfirmed()
            return True
        self.send("run")
        self.resumed_at = time.monotonic()
        if self.settle_running(self.ATTACH_STABLE, max(deadline, time.monotonic() + self.cfg.hold_timeout)):
            self.confirm_running()
        else:
            self.unconfirmed()
        return True

    def confirm_running(self) -> bool:
        """x64dbg has settled at running: take the after-resume check, and
        call the session `running` only when it reads the game running."""
        after = self.check()
        self.set_instrument(after_resume=after)
        if after.get("verdict") != "running":
            self.unconfirmed(f"the outside check after the resume read the game {after.get('verdict')} "
                             f"({after.get('detail')})")
            return False
        late = {"late_ready_utc": _utc()} if self.state["state"] == "attach-unconfirmed" else {}
        self.save(state="running", ready=True, x64dbg_state="running", error=None, **late)
        return True

    def unconfirmed(self, seen: str | None = None) -> None:
        """Not everything an attach needs was seen: the session is
        `attach-unconfirmed`, with an error naming what was not. The keeper's
        loop keeps resuming every pause and promotes it (`promote`) once it
        has, serving detach in between."""
        missing = []
        if not self.plugin_ok:
            missing.append(f"the plugin did not answer a debug-only call within {self.cfg.ready_timeout:.0f}s")
        if not self.attach_pause:
            missing.append("x64dbg's attach break (a [STATE] paused after attach) was never seen")
        if self.plugin_ok and self.attach_pause and seen is None:
            missing.append(f"x64dbg's state never settled at running for {self.ATTACH_STABLE:.0f}s (the keeper "
                           f"resumed {self.state['breaks_resumed']} pause(s) after the attach break)")
        if seen:
            missing.append(seen)
        self.retry_at = time.monotonic() + 2 * self.cfg.settle
        self.save(state="attach-unconfirmed", ready=False,
                  error="the attach is unconfirmed: " + "; ".join(missing) + ". So the game may be paused. The "
                        "keeper keeps resuming every pause x64dbg takes, and makes the session running once all of "
                        "this is seen. Run detach (`py -3 -m tools.x64dbg_mcp detach`) rather than use this session")

    def promote(self) -> None:
        """In `attach-unconfirmed`: once the plugin answers, the attach break
        has been seen and x64dbg has read running for ATTACH_STABLE seconds,
        check the game and make the session `running`."""
        if time.monotonic() < self.retry_at:
            return
        self.retry_at = time.monotonic() + 2 * self.cfg.settle
        if not self.plugin_ok:
            self.plugin_ok = self.plugin.debug_state() == "debugging"
        if not (self.plugin_ok and self.attach_pause) or self.log.settled_for("running") < self.ATTACH_STABLE:
            return
        if self.confirm_running():
            self.note("late attach confirmed: the game runs")

    def watchdog(self) -> None:
        """Resume every pause x64dbg has settled in, on stdin. One `run` per
        pause, counted in `breaks_resumed` with its break line in
        `last_break` (the attach break and a held change's pause are the
        keeper's own and are not counted); another `run` for the same pause
        only when the first brought no new [STATE] line within RESEND
        seconds. STORM_COUNT resumes within STORM_WINDOW seconds set
        `break_storm`, which stays set."""
        settled = self.log.settled()
        changes: dict[str, Any] = {}
        if settled and settled != self.state.get("x64dbg_state"):
            changes["x64dbg_state"] = settled
        if settled == "paused":
            now, n = time.monotonic(), self.log.pauses
            if n != self.resumed_pause:
                brk = self.log.pause_line(n) or {}
                self.resumes = [t for t in self.resumes if now - t < self.STORM_WINDOW] + [now]
                changes["breaks_resumed"] = self.state["breaks_resumed"] + 1
                changes["last_break"] = {"line": brk.get("line"), "utc": brk.get("utc")}
                if len(self.resumes) >= self.STORM_COUNT:
                    changes["break_storm"] = True
                self.note(f"resuming pause {n}: {brk.get('line')}")
                self.send("run")
                self.resumed_pause, self.resumed_at = n, now
            elif now - self.resumed_at >= self.RESEND:
                self.send("run")
                self.resumed_at = now
        if changes:
            self.save(**changes)

    def settle_running(self, stable: float, until: float) -> bool:
        """Resume every pause until x64dbg has read running for `stable`
        seconds with no new [STATE] line; False when `until` passes first."""
        while time.monotonic() < until:
            if not self.headless_running():
                return False
            self.watchdog()
            if self.log.settled_for("running") >= stable:
                if self.state.get("x64dbg_state") != "running":
                    self.save(x64dbg_state="running")
                return True
            time.sleep(min(self.cfg.poll, 0.05))
        return False

    def wait_state(self, name: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            self.log.poll()
            if self.log.state == name:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def run_batch(self, hid: str, sections: list[tuple[str, list[str]]], end: str) -> tuple[dict[str, list[str]], bool]:
        """Send each section's marker and commands, then the end marker, and
        wait up to `hold_timeout` for x64dbg to print the end marker. Returns
        the lines x64dbg printed in each section, and whether the end came."""
        mark = self.log.mark()
        for name, commands in sections:
            self.send(f'log "{batch_marker(hid, name)}"')
            for c in commands:
                self.send(c)
        self.send(f'log "{batch_marker(hid, end)}"')
        markers = {batch_marker(hid, n): n for n in [*(s for s, _ in sections), end]}
        deadline = time.monotonic() + self.cfg.hold_timeout
        while True:
            lines = [ln.strip() for ln in self.log.since(mark)]
            done = batch_marker(hid, end) in lines
            if done or time.monotonic() >= deadline or not self.headless_running():
                break
            time.sleep(0.02)
        out: dict[str, list[str]] = {name: [] for name, _ in sections}
        current = None
        for ln in lines:
            if ln in markers:
                current = markers[ln] if markers[ln] in out else None
            elif current is not None and ln:
                out[current].append(ln)
        return out, done

    def hold(self, lines: list[str]) -> dict[str, Any]:
        """Change hardware breakpoints without asking x64dbg to pause.

        Read bplist. With nothing armed, send the lines as a direct batch
        between markers, then settle at running, resuming any pause, and
        report one that came as `window_break`. With breakpoints armed, set
        each one's break condition to 1 and wait HOLD_BREAK seconds for one
        to break: a logging breakpoint then holds the game at its hit, where
        nothing is mid-hit and the change cannot race x64dbg's debug loop.
        Send the lines there, restore the conditions to 0, and `run` (a held
        change, reported as `held`). When nothing breaks, nothing was
        logging: restore the conditions and send a direct batch."""
        for line in lines:
            if any(c in line for c in "\r\n"):
                raise ValueError("one command per line")
        hid = uuid.uuid4().hex[:8]
        t = self.cfg.hold_timeout
        pauses = self.log.pauses
        listing, listed = self.run_batch(hid, [("list", ["bplist"])], "listed")
        if not listed:
            return self.hold_reply(False, f"x64dbg never printed the end of its bplist within {t:.0f}s, so "
                                          "nothing was changed", {}, None, None, None, end_seen=False)
        armed = []
        for row in listing["list"]:
            m = _BPLIST_ROW.match(row)
            if m and m.group(1) != "0" and m.group(2).upper() == "HW":
                armed.append(int(m.group(3), 16))
        held = held_note = None
        out: dict[str, list[str]] = {}
        done = False
        if armed:
            for a in armed:
                self.send(f"SetHardwareBreakpointCondition 0x{a:X}, 1")
            if self.wait_state("paused", self.HOLD_BREAK):
                n = self.log.pauses
                held = (self.log.pause_line(n) or {}).get("line") or "a pause with no break line"
                restore = [f"SetHardwareBreakpointCondition 0x{a:X}, 0" for a in armed]
                out, done = self.run_batch(hid, [("begin", lines), ("mid", [*restore, "bplist"])], "end")
                self.send("run")
                self.resumed_pause, self.resumed_at = n, time.monotonic()
                pauses = n
            else:
                for a in armed:
                    self.send(f"SetHardwareBreakpointCondition 0x{a:X}, 0")
                held_note = (f"no armed hardware breakpoint broke within {self.HOLD_BREAK:.0f} s of its break "
                             "condition being set to 1, so none was logging: the change went out as a direct batch")
        if held is None:
            out, done = self.run_batch(hid, [("begin", lines), ("mid", ["bplist"])], "end")
        settled = self.settle_running(SessionLog.QUIET, time.monotonic() + t)
        window_break = None
        if held is None and self.log.pauses > pauses:
            window_break = (self.log.pause_line(pauses + 1) or {}).get("line") or "a pause with no break line"
        detail = None
        if not done:
            detail = f"x64dbg never printed the batch's end marker within {t:.0f}s"
        elif not settled:
            detail = (f"x64dbg's state never settled at running within {t:.0f}s after the batch "
                      f"(it reads {self.log.state})")
        reply = self.hold_reply(done and settled, detail, out, held, held_note, window_break, end_seen=done)
        return reply

    def hold_reply(self, ok: bool, detail: str | None, out: dict[str, list[str]], held: str | None,
                   held_note: str | None, window_break: str | None, end_seen: bool) -> dict[str, Any]:
        """The hold's reply. `end_seen` says whether x64dbg printed the
        batch's end marker (so its lines are complete), and `log_offset` is
        how far into the session log the hold read: what x64dbg printed after
        it is after the hold, where `logpoint`'s verification window looks."""
        self.log.poll()
        reply: dict[str, Any] = {
            "ok": ok, "lines": out.get("begin", []), "after": out.get("mid", []), "held": held,
            "window_break": window_break, "x64dbg_state": self.log.settled() or self.log.state,
            "end_seen": end_seen, "log_offset": self.log.offset - len(self.log._partial),
            "game": self.check(),
        }
        if held_note:
            reply["held_note"] = held_note
        if detail:
            reply["detail"] = detail
        return reply

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
                elif data.get("op") == "hold":
                    if self.state["state"] != "running":
                        reply = {"ok": False, "detail": f"the session is {self.state['state']}, not running"}
                    else:
                        reply = self.hold([str(line) for line in data.get("lines", [])])
                elif data.get("op") == "detach":
                    reply = self.teardown()
                else:
                    reply = {"ok": False, "detail": f"unknown op {data.get('op')!r}"}
            except Exception as e:  # noqa: BLE001 - reported to the requester
                reply = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
            write_json(self.cfg.replies / req.name, reply)

    def teardown(self) -> dict[str, Any]:
        """A held `bphc`, a settle at running, `detach`, confirm, `exit`, then
        the outside check of the game. Only a confirmed detach lets the keeper
        end a headless that has not exited by itself, and only a game whose
        threads all run again is `ended` with `game_released: true`."""
        self.save(state="detaching")
        cleared = self.hold(["bphc"])
        cleared.pop("game", None)
        # No tool path plants a pause breakpoint any more, so a game x64dbg
        # still holds here is detached anyway, and the outside check decides.
        settled = self.settle_running(SessionLog.QUIET, time.monotonic() + self.cfg.hold_timeout)
        self.save(paused_at_detach=not settled)
        mark = self.log.mark()
        self.send("detach")
        deadline = time.monotonic() + self.cfg.detach_timeout
        confirmed = False
        while time.monotonic() < deadline:
            if self.plugin.debug_state() == "none" and "Detached!" in (ln.strip() for ln in self.log.since(mark)):
                confirmed = True
                break
            time.sleep(self.cfg.poll)
        if not confirmed:
            detail = (f"detach not confirmed within {self.cfg.detach_timeout:.0f}s: the plugin never reported "
                      "that no session remains, or x64dbg never printed Detached!. Headless x64dbg "
                      f"(pid {self.proc.pid}) is left running and was not killed; it may still be attached to the "
                      f"game. Retry detach, or look at {self.cfg.log_file}")
            self.save(state="detach-unconfirmed", detach_confirmed=False, error=detail)
            return {"ok": False, "state": "detach-unconfirmed", "detail": detail, "cleared": cleared,
                    "paused_at_detach": not settled}
        self.send("exit")
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()  # the detach was confirmed, so nothing is attached any more
            self.proc.wait(timeout=10)
        return self.released(cleared, not settled)

    def released(self, cleared: dict[str, Any], paused_at_detach: bool) -> dict[str, Any]:
        """The post-detach check, the threads suspended before attach left
        out: `running` ends the session released, `gone` ends it with a note,
        and anything else is `game-not-released`."""
        game = self.check()
        verdict = game.get("verdict")
        common = {"detach_confirmed": True, "game": game, "paused_at_detach": paused_at_detach, "cleared": cleared}
        if verdict == "running":
            self.save(state="ended", detach_confirmed=True, game_released=True, game=game, error=None)
            return {"ok": True, "state": "ended", "game_released": True,
                    "detail": "detached (confirmed), headless x64dbg exited, and every game thread runs again",
                    **common}
        if verdict == "gone":
            note = (f"the game (pid {self.target_pid}) was gone by the post-detach check, so whether the detach "
                    "released its threads is not known")
            self.save(state="ended", detach_confirmed=True, game_released=None, game=game, error=None, note=note)
            return {"ok": True, "state": "ended", "game_released": None, "note": note,
                    "detail": "detached (confirmed), then headless x64dbg exited", **common}
        released = None if verdict in ("unreadable", "unsupported") else False
        suspended = game.get("suspended") or []
        stopped = game.get("stopped") or []
        error = (f"the detach was confirmed, but the outside check reads the game (pid {self.target_pid}) "
                 f"{verdict}, not running: {len(suspended)} thread(s) suspended ("
                 + (", ".join(f"tid {s.get('tid')} count {s.get('suspend_count')}" for s in suspended) or "none")
                 + f"), {len(stopped)} stopped in Waiting/Suspended ("
                 + (", ".join(f"tid {t}" for t in stopped) or "none")
                 + f"). {game.get('detail')} Nothing but a force-stop releases them, and these tools never resume "
                   "a game thread: the driver runs hs_stop_game with force=true, then hs_saves_restore of this "
                   "session's backup")
        self.save(state="game-not-released", detach_confirmed=True, game_released=released, game=game, error=error)
        return {"ok": False, "state": "game-not-released", "game_released": released, "detail": error, **common}

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
    # headless x64dbg, and the tests' probe seam when one is set
    install_offline_guard(allowed_executables=(cfg.headless_argv[0], *cfg.probe_cmd[:1]) if cfg.probe_cmd
                          else (cfg.headless_argv[0],))
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
    if state.get("state") == "attach-unconfirmed":
        print("x64dbg_mcp: attach unconfirmed: the game may be paused (the error says what was not seen), and "
              "every tool but detach refuses this session. Run `py -3 -m tools.x64dbg_mcp detach`.")
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
    # The baseline of the outside check: attach only to a game seen running,
    # by an instrument that can read it.
    baseline = game_check(cfg, pid)
    verdict = baseline.get("verdict")
    if verdict in ("unreadable", "unsupported"):
        raise Refused("game_unreadable", f"the outside check of pid {pid} (tools/thread_state.py) reads {verdict}: "
                                         f"{baseline.get('detail')} Without it no detach can be shown to release "
                                         "the game")
    if verdict != "running":
        raise Refused("game_not_running", f"the outside check of pid {pid} reads {verdict}, not running: "
                                          f"{baseline.get('detail')} Attach only to a game that runs")
    cfg.session.mkdir(parents=True, exist_ok=True)
    for d in (cfg.requests, cfg.replies):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
    if cfg.log_file.exists():
        os.replace(cfg.log_file, cfg.session / "session.prev.log")
    write_json(cfg.keeper_config, cfg.to_json())
    write_json(cfg.state_file, {"schema": SESSION_SCHEMA, "state": "attaching", "target_pid": pid,
                                "started_utc": _utc(), "baseline": baseline})
    with open(cfg.keeper_log, "ab") as log:
        keeper = subprocess.Popen(
            [sys.executable, "-m", "tools.x64dbg_mcp", "keeper", "--session", str(cfg.session), "--pid", str(pid)],
            cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **_detached_flags())
    deadline = time.monotonic() + cfg.ready_timeout + 30
    while time.monotonic() < deadline:
        state = read_state(cfg)
        if state.get("keeper") and state.get("state") in ("running", "attach-unconfirmed", "ended",
                                                          "detach-unconfirmed"):
            return state
        if keeper.poll() is not None:
            break
        time.sleep(cfg.poll)
    state = read_state(cfg)
    if state.get("state") not in ("running",):
        state.setdefault("error", f"the keeper reported {state.get('state')}; see {cfg.keeper_log}")
    return state


def detach_wait(cfg: Config) -> float:
    """How long a detach may take: the held `bphc` (its bplist, the hold, the
    batch and the settle), the settle before detach, the detach itself, and
    headless's exit."""
    return 4 * cfg.hold_timeout + Keeper.HOLD_BREAK + cfg.detach_timeout + 30


def hold_wait(cfg: Config) -> float:
    """How long a hold may take: its bplist, the wait for a logging
    breakpoint to break, the batch, the settle and the outside check."""
    return 3 * cfg.hold_timeout + Keeper.HOLD_BREAK + 30


def detach(cfg: Config) -> int:
    """Exits 0 only for a session `ended` with every game thread running
    again (`game_released` true), or with the game gone."""
    try:
        reply = keeper_request(cfg, "detach", timeout=detach_wait(cfg))
    except Refused as r:
        print(f"x64dbg_mcp: detach refused ({r.reason}): {r.detail}")
        return 1
    print(json.dumps(reply))
    state = read_state(cfg)
    gone = (state.get("game") or {}).get("verdict") == "gone"
    return 0 if state.get("state") == "ended" and state.get("detach_confirmed") \
        and (state.get("game_released") is True or gone) else 1


# --- the eight tools --------------------------------------------------------

_HEX = re.compile(r"^(?:0x)?([0-9A-Fa-f]+)$")
_MODULE_OFFSET = re.compile(r"^([^\s+]+)\+(?:0x)?([0-9A-Fa-f]+)$")
# One row of the plugin's GetAllModulesFromMemMap table: name, path, then base,
# end and size. The pinned plugin prints those three as **decimal digits behind
# a literal `0x`**: it formats pointer-sized integers with a hex specifier, but
# it targets net472, where that type ignores the specifier (read from the
# pinned source, and measured live on 2026-10-10). So a row is read only when
# each column is decimal with no leading zero (plain decimal never has one; a
# zero-padded hex rendering always does), end == base + size, and the base is
# on a 64 KiB boundary (`module_row_base`). Any other row is refused, never
# guessed at: a hex value made only of digits also reads as decimal.
_MODULE_ROW = re.compile(r"^(\S+)\s.*?\s0x([1-9][0-9]*)\s+0x([1-9][0-9]*)\s+0x([1-9][0-9]*)\s*$")
# Any row ending in three `0x` columns, readable or not.
_MODULE_ROW_SHAPE = re.compile(r"^\S+\s.*\s0x\S+\s+0x\S+\s+0x\S+\s*$")
# Windows maps an image at a multiple of its allocation granularity, 64 KiB.
_IMAGE_ALIGNMENT = 0x10000
# x64dbg's bplist row: `<enabled>:<type>:<address>[:"<name>"]`, the first
# field 1 for an enabled breakpoint and 0 for a disabled one, the type `HW` for
# a hardware breakpoint.
_BPLIST_ROW = re.compile(r"^\s*(\d+):([^:\s]+):([0-9A-Fa-f]+)(?::|\s|$)")
# One instruction row of the plugin's ReadDismAtAddress listing: the address,
# then the instruction's bytes as `48-89-5C`, then its text.
_LISTING_ROW = re.compile(r"^\s*(?:0x)?([0-9A-Fa-f]{8,16})\s+((?:[0-9A-Fa-f]{2}-)*[0-9A-Fa-f]{2})(?:\s|$)")
# No tool path calls the plugin's ExecuteDbgCommand any more: `logpoint`,
# `command` and teardown send x64dbg's commands on headless's stdin, through
# the keeper. What follows records the measured shape of its reply, kept with
# its tests so a later change that calls it again starts from what is known.
# What the plugin's ExecuteDbgCommand answers. At the pinned commit it returns
# whatever reached x64dbg's log while the command ran (it redirects the log to
# a file around the command and reads the file back), behind `Result: `
# (DotNetPlugin.Impl/Plugin.Commands.cs:534-599, :2914-2917). With nothing
# captured it returns PLUGIN_EXEC_SILENT_OK, or PLUGIN_EXEC_FAILED when the
# command could not be queued to x64dbg's command thread (:589); a command
# x64dbg ran and rejected arrives as `Result: <its text>` instead. The bare
# `_QUEUED_REPLY` form is what ExecuteDbgCommand would give for a blank
# capture, kept in case a later plugin returns one.
PLUGIN_EXEC_SILENT_OK = "Command executed successfully (no output captured)"
PLUGIN_EXEC_FAILED = "Command execution failed (no output captured)"
_QUEUED_REPLY = re.compile(r"^Command '.*' executed successfully\.?$", re.S)
# The plugin also writes its own echo of each ExecuteDbgCommand call to that
# same log (its console is x64dbg's log) just before it starts the capture,
# and the echo still lands in it ahead of anything x64dbg printed: measured
# live on 2026-10-10, all five lines for one call and only the last for
# another. `plugin_echo` is those five lines; any tail of them is the
# plugin talking, not x64dbg.
_ECHO_RULE = "-" * 40


def plugin_echo(command: str) -> list[str]:
    """The lines the pinned plugin writes to x64dbg's log for one
    ExecuteDbgCommand call, in order: a rule, the method, the command, a
    rule, and the line it writes as it hands the command to x64dbg."""
    return [_ECHO_RULE, f"METHOD: {PLUGIN_EXECUTE}", f"command: {command}", _ECHO_RULE,
            f"Executing DbgCmdExec: {command}"]
# The most bytes `expect_bytes` may carry.
EXPECT_BYTES_MAX = 32


def _reply_body(reply: str) -> str:
    """An ExecuteDbgCommand reply without its `Result:` wrapper, stripped."""
    text = reply.strip()
    if text[:7].lower() == "result:":
        text = text[7:]
    return text.strip()


def silent_reply_ok(reply: str, command: str) -> bool:
    """Whether a reply to `command`, one x64dbg prints nothing for on success
    (the `Set*` steps), says x64dbg printed nothing: exactly the plugin's
    no-output success text, its bare queued form, blank, or a capture holding
    only a tail of the plugin's own echo of this very command, in order. Any
    other line is something x64dbg printed, which for these commands is their
    failure, and so is the plugin's PLUGIN_EXEC_FAILED."""
    text = reply.strip()
    if _QUEUED_REPLY.match(text):
        return True
    body = _reply_body(text)
    if body in ("", PLUGIN_EXEC_SILENT_OK):
        return True
    lines = [ln.rstrip() for ln in body.splitlines() if ln.strip()]
    echo = plugin_echo(command)
    return any(lines == echo[k:] for k in range(len(echo)))


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


# `command`'s verbs that change debug registers. They go through a hold, as
# `logpoint`'s lines do, so a change never races a logging breakpoint's
# re-arm; the list-only verbs go straight to headless's stdin.
_HOLD_VERBS = {"deletehardwarebreakpoint", "bphc", "bphwc", "enablehardwarebreakpoint", "bphe", "bphwe",
               "disablehardwarebreakpoint", "bphd", "bphwd"}
# What x64dbg prints when a step of arming a hardware breakpoint fails (read
# from x64dbg 9c8ca1c's source, docs/tools/x64dbg-mcp.md): the four-breakpoint
# limit, a failed set, a breakpoint already there, a `Set*` step naming no
# breakpoint or refused, a short argument list, and an unknown verb.
_ARM_FAILURE = re.compile(r"^(?:You can only set \d+ hardware breakpoints|Error setting hardware breakpoint|"
                          r"Hardware breakpoint already set!|No such breakpoint\b|Can't set\b|"
                          r"Not enough arguments!|Unknown command\b)", re.I)


def arming_failure(reply: dict[str, Any], addr: int, name: str | None) -> tuple[str, str] | None:
    """Why a hold that armed `addr` did not arm it, as (stage, detail), or
    None. From the hold's `lines` (x64dbg's output for the arming lines): a
    failure line, or no `Hardware breakpoint at <addr> set!`. From its
    `after` (the bplist that followed): no row for `addr`, a disabled row,
    another kind of breakpoint, or a row without the name given."""
    hexaddr = f"0x{addr:X}"
    lines = [ln.strip() for ln in reply.get("lines") or []]
    bad = [ln for ln in lines if _ARM_FAILURE.match(ln)]
    if bad:
        return "set", f"x64dbg printed, while arming {hexaddr}: {' | '.join(bad)}"
    if f"hardware breakpoint at {addr:016x} set!" not in (ln.lower() for ln in lines):
        return "set", (f"x64dbg never printed `Hardware breakpoint at {addr:016X} set!` for the bph, so {hexaddr} "
                       f"is not known to be set (it printed {lines!r})")
    after = [ln.strip() for ln in reply.get("after") or []]
    listed = bplist_entry(after, addr)
    if listed is None:
        return "set", (f"bplist did not name {hexaddr} after x64dbg reported it set (a reported breakpoint is not "
                       "a set one until x64dbg lists it)")
    if listed == "disabled":
        return "listed-but-disabled", (f"bplist has {hexaddr} listed but disabled (its row's first field is 0): "
                                       "a disabled breakpoint never logs")
    if listed != "armed":
        return "set", f"bplist lists {hexaddr} as a {listed} breakpoint, not an enabled hardware one"
    if name is not None:
        rows = [ln for ln in after if (m := _BPLIST_ROW.match(ln)) and int(m.group(3), 16) == addr]
        if not any(f':"{name}"' in ln for ln in rows):
            return "set", f"bplist lists {hexaddr} without the name {name!r} it was given: {rows!r}"
    return None


def break_on(lines: list[str], addr: int, name: str | None) -> str | None:
    """The first break line naming `addr` (by its 16 hex digits, or by
    `name`) that x64dbg followed with `[STATE] paused`, or None."""
    pending = None
    for raw in lines:
        text = raw.strip()
        m = _STATE_LINE.match(text)
        if m:
            if pending and m.group(1).lower() == "paused":
                return pending
            pending = None
        elif _BREAK_LINE.match(text):
            hit = f"{addr:016X}" in text.upper() or (name is not None and f'"{name}"' in text)
            pending = text if hit else None
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


def parse_expect_bytes(value: str) -> bytes:
    """`expect_bytes` as bytes: hex, with spaces or dashes between bytes
    allowed (`48 89 5C 24`, `48-89-5C-24`, `48895C24`). Raises ValueError."""
    text = re.sub(r"[\s-]", "", value)
    if text.lower().startswith("0x"):
        text = text[2:]
    if not text or len(text) % 2 or not re.fullmatch(r"[0-9A-Fa-f]+", text):
        raise ValueError(f"expect_bytes {value!r} is not whole hex bytes (e.g. '48 89 5C 24 08')")
    data = bytes.fromhex(text)
    if len(data) > EXPECT_BYTES_MAX:
        raise ValueError(f"expect_bytes carries {len(data)} bytes; {EXPECT_BYTES_MAX} at most")
    return data


class Tools:
    """The eight tools' behaviour, apart from MCP, so the tests can drive it."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.plugin = PluginClient(cfg.url)

    # gates

    def _gate(self, tool: str, need_lease: bool = True,
              states: tuple[str, ...] = ("running",)) -> dict[str, Any] | None:
        state = read_state(self.cfg)
        if state.get("state") == "attach-unconfirmed" and "attach-unconfirmed" not in states \
                and alive(state.get("keeper")):
            return _refusal(tool, "attach_unconfirmed",
                            "the attach was never confirmed: the plugin has not answered a debug-only call, or "
                            "the game was never seen running after it, so the game may be paused at x64dbg's "
                            "attach break. Run the detach tool (or "
                            "`py -3 -m tools.x64dbg_mcp detach`); nothing else is served on this session")
        if state.get("state") not in states or not alive(state.get("keeper")):
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

    def _stdin_lines(self, line: str, wait_for: int | None = None) -> list[str]:
        """Send one command on headless's stdin and return the log lines that
        followed it: until a bplist row names `wait_for`, or the settle time
        passed. Stdin, not the plugin's ExecuteDbgCommand, because the plugin
        captures a command's output by redirecting x64dbg's whole log to a temp
        file for about 3 s, and whether logging-breakpoint hits reach the
        session log meanwhile is not established."""
        offset = self._log_size()
        self._stdin([line])
        deadline = time.monotonic() + max(self.cfg.settle, 3.0 if wait_for is not None else 0)
        lines: list[str] = []
        while time.monotonic() < deadline:
            time.sleep(min(0.1, self.cfg.settle))
            lines = self._log_after(offset)
            if wait_for is not None and bplist_entry(lines, wait_for) is not None:
                break
        return lines

    def _bplist_lines(self, wait_for: int | None = None) -> list[str]:
        return self._stdin_lines("bplist", wait_for)

    def _bplist_marked(self) -> list[str]:
        """bplist on headless's stdin between two `log` markers, and the rows
        x64dbg printed between them: complete once the end marker is in the
        log, so an empty list means nothing is listed, not that the rows are
        late."""
        hid = uuid.uuid4().hex[:8]
        start, end = batch_marker(hid, "list"), batch_marker(hid, "listed")
        offset = self._log_size()
        self._stdin([f'log "{start}"', "bplist", f'log "{end}"'])
        deadline = time.monotonic() + self.cfg.hold_timeout
        while True:
            lines = [ln.strip() for ln in self._log_after(offset)]
            if end in lines:
                return lines[lines.index(start) + 1 if start in lines else 0:lines.index(end)]
            if time.monotonic() >= deadline:
                raise Refused("bplist_unanswered", f"x64dbg never printed the end of a bplist within "
                                                   f"{self.cfg.hold_timeout:.0f}s, so nothing was set")
            time.sleep(0.05)

    def _hold(self, lines: list[str]) -> dict[str, Any]:
        """Lines that change hardware breakpoints, through the keeper's hold
        (`Keeper.hold`): never a pause, and held at a hit of a logging
        breakpoint when one is armed."""
        return keeper_request(self.cfg, "hold", timeout=hold_wait(self.cfg), lines=lines)

    def _game(self) -> dict[str, Any] | None:
        """A fresh outside check of the session's game, or None with no live session."""
        live = live_session(self.cfg)
        if live is None or not live.get("target_pid"):
            return None
        return game_check(self.cfg, int(live["target_pid"]),
                          baseline=check_tids((live.get("instrument") or {}).get("before_attach")))

    def _code_at(self, addr: int, count: int) -> bytes:
        """The first bytes of code at `addr`, from the plugin's disassembly."""
        text, is_error = self.plugin.call_checked(PLUGIN_DISASM, {"address": f"0x{addr:X}", "byteCount": count})
        if is_error:
            raise PluginError(f"reading code at 0x{addr:X}: {text}")
        return listing_bytes(text, addr)

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
        table = self.plugin.call_checked(PLUGIN_MODULES)[0]
        base = module_bases(table).get(m.group(1).lower())
        if base is None:
            row = module_row(table, m.group(1))
            if row is not None:
                raise Refused("module_row_unreadable",
                              f"{m.group(1)!r} has a row in the plugin's module list, but not in the format the "
                              f"pinned plugin prints (decimal base, end and size behind 0x, end = base + size, "
                              f"base on a 64 KiB boundary), "
                              f"so no base was read from it rather than a wrong one: {row!r}")
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
        out = {"ok": True, **session_summary(self.cfg), "plugin_answers": answers,
               "plugin_url": self.cfg.url, "lease": {"state": held, "detail": detail}}
        game = self._game()  # a fresh outside check of the game, while the session may hold it
        if game is not None:
            out["game"] = game
        return out

    def logpoint(self, address: str, log: str, log_condition: str | None = None,
                 name: str | None = None, expect_bytes: str | None = None) -> dict[str, Any]:
        tool = "logpoint"
        gate = self._gate(tool)
        if gate:
            return gate
        if read_state(self.cfg).get("break_storm"):
            return _refusal(tool, "break_storm",
                            f"x64dbg paused the game {Keeper.STORM_COUNT} times within {Keeper.STORM_WINDOW:.0f} s "
                            "on its own; the keeper resumed each (status: breaks_resumed, last_break), but no "
                            "breakpoint is set on this session any more. Detach, and read the session log")
        for value, what, forbid in ((log, "log", '"'), (log_condition, "log_condition", '";'),
                                    (name, "name", '";')):
            why = _text_refusal(value, what, forbid) if value is not None else None
            if why:
                return _refusal(tool, "bad_argument", why)
        try:
            expect = parse_expect_bytes(expect_bytes) if expect_bytes else None
        except ValueError as e:
            return _refusal(tool, "bad_argument", str(e))
        try:
            addr = self.resolve(address)
        except Refused as r:
            return _refusal(tool, r.reason, r.detail)
        except PluginError as e:
            return _refusal(tool, "plugin", str(e))
        hexaddr = f"0x{addr:X}"
        # A hardware execute breakpoint fires only where an instruction starts,
        # so a stale or mid-instruction address arms fine and never logs. Read
        # the code there first, and with `expect_bytes` (from Ghidra's copy of
        # the same function) refuse before anything is set.
        try:
            code = self._code_at(addr, max(16, len(expect or b"")))
        except PluginError as e:
            return _refusal(tool, "plugin", str(e), address=hexaddr)
        if expect is not None and not code.startswith(expect):
            return _refusal(tool, "bytes_mismatch",
                            f"the code at {hexaddr} starts {code[:len(expect)].hex(' ').upper() or 'with nothing readable'}, "
                            f"not {expect.hex(' ').upper()}: a stale or mid-instruction address never fires, so "
                            "nothing was set", address=hexaddr, bytes=code.hex(" ").upper(),
                            expect_bytes=expect.hex(" ").upper())
        checked = {"bytes": code.hex(" ").upper(), "bytes_checked": expect is not None}
        if expect is None:
            checked["note"] = ("no expect_bytes: these bytes were not compared with Ghidra's, so a zero from this "
                               "address is not evidence until they are")
        # Refusals that need x64dbg's own view: it must have settled at
        # running (the keeper resumes every pause it takes), and the address
        # must not be listed already, since a failure below clears it.
        settled = read_state(self.cfg).get("x64dbg_state")
        if settled != "running":
            return _refusal(tool, "not_running",
                            f"x64dbg's settled state is {settled}, not running: arming is only done on a running "
                            "game. The keeper resumes every pause; try again once status reads x64dbg_state "
                            "running", address=hexaddr, **checked)
        try:
            listed = bplist_entry(self._bplist_marked(), addr)
        except Refused as r:
            return _refusal(tool, r.reason, r.detail, address=hexaddr, **checked)
        if listed is not None:
            return _refusal(tool, "already_armed",
                            f"bplist already lists {hexaddr} ({listed}); nothing was set. Delete it first with "
                            f"the command tool (bphc {hexaddr}) to arm it again", address=hexaddr, **checked)
        # One hold, never a pause. The never-break condition comes straight
        # after `bph`, so in a direct batch only `bph`'s own pass over the
        # threads can break on a hit (reported as window_break, and resumed).
        steps = [f"bph {hexaddr}, x, 1", f"SetHardwareBreakpointCondition {hexaddr}, 0",
                 f'SetHardwareBreakpointLog {hexaddr}, "{log}"']
        if log_condition:
            steps.append(f"SetHardwareBreakpointLogCondition {hexaddr}, {log_condition}")
        if name:
            steps.append(f'SetHardwareBreakpointName {hexaddr}, "{name}"')
        base = {"tool": tool, "address": hexaddr, "steps": steps, **checked}
        try:
            reply = self._hold(steps)
        except Refused as r:
            return self._arming_failed(base, addr, "set", f"the keeper did not answer the hold ({r.reason}): "
                                                          f"{r.detail}", {})
        if not reply.get("end_seen"):
            return self._arming_failed(base, addr, "set", reply.get("detail") or "the hold did not complete", reply)
        failure = arming_failure(reply, addr, name or None)
        if failure:
            return self._arming_failed(base, addr, *failure, reply)
        if not reply.get("ok"):
            return self._arming_failed(base, addr, "running", f"{hexaddr} was armed, but {reply.get('detail')}: "
                                                              "it may break on its hits", reply)
        # The verification window: a break on this breakpoint after the hold
        # means its never-break condition did not take.
        time.sleep(self.cfg.settle)
        brk = break_on(self._log_after(int(reply.get("log_offset") or 0)), addr, name or None)
        if brk is not None:
            return self._arming_failed(base, addr, "running",
                                       f"x64dbg broke on {hexaddr} within {self.cfg.settle:.1f}s of arming it "
                                       f"({brk}): its never-break condition did not take", reply)
        game = self._game() or {"verdict": "unreadable", "detail": "no live session to check"}
        if game.get("verdict") != "running":
            return self._arming_failed(base, addr, "game-not-running",
                                       f"the outside check reads the game {game.get('verdict')}, not running, after "
                                       f"{hexaddr} was armed: {game.get('detail')}", reply, game=game)
        rows = [ln.strip() for ln in reply.get("after") or [] if _BPLIST_ROW.match(ln)]
        return {"ok": True, **base, "bplist": rows, "held": reply.get("held"),
                "window_break": reply.get("window_break") is not None,
                **({"window_break_line": reply["window_break"]} if reply.get("window_break") else {}),
                **({"held_note": reply["held_note"]} if reply.get("held_note") else {}),
                "x64dbg_state": read_state(self.cfg).get("x64dbg_state") or reply.get("x64dbg_state"),
                "game": game}

    def _arming_failed(self, base: dict[str, Any], addr: int, stage: str, detail: str, reply: dict[str, Any],
                       **fields: Any) -> dict[str, Any]:
        """A failure after the hold went out: clear the breakpoint with a hold
        of its own, and report x64dbg's settled state after it."""
        hexaddr = f"0x{addr:X}"
        try:
            clear = self._hold([f"bphc {hexaddr}"])
            cleared = clear.get("lines", [])
            settled = clear.get("x64dbg_state")
            if not clear.get("ok"):
                fields["clear_detail"] = clear.get("detail")
        except Refused as r:
            cleared = [f"clearing failed ({r.reason}): {r.detail}"]
            settled = read_state(self.cfg).get("x64dbg_state")
        if settled != "running":
            fields["note"] = (f"x64dbg's state after the clear is {settled}, not running; the keeper keeps resuming "
                              "every pause: read status, and detach if it stays so")
        return {"ok": False, **base, "stage": stage, "detail": detail,
                "lines": reply.get("lines", []), "after": reply.get("after", []), "held": reply.get("held"),
                "window_break": reply.get("window_break") is not None, "cleared": cleared,
                "x64dbg_state": settled, **fields}

    def command(self, command: str) -> dict[str, Any]:
        tool = "command"
        why = command_refusal(command)
        if why:
            return _refusal(tool, "not_allowed", f"refused: {why}")
        gate = self._gate(tool)
        if gate:
            return gate
        text = command.strip()
        verb = re.match(r"[^\s,]+", text).group(0).lower()  # type: ignore[union-attr]
        if verb in _HOLD_VERBS:
            try:
                reply = self._hold([text])
            except Refused as r:
                return _refusal(tool, r.reason, r.detail)
            out = {"ok": bool(reply.get("ok")), "tool": tool, "sent": text, "lines": reply.get("lines", []),
                   "after": reply.get("after", []), "held": reply.get("held"),
                   "window_break": reply.get("window_break"), "x64dbg_state": reply.get("x64dbg_state"),
                   "note": "sent through a hold on headless x64dbg's stdin (held at a hit of a logging breakpoint "
                           "when one is armed); `after` carries the bplist that followed it"}
            for key in ("held_note", "detail"):
                if reply.get(key):
                    out[key] = reply[key]
            return out
        try:
            lines = self._stdin_lines(text)
        except Refused as r:
            return _refusal(tool, r.reason, r.detail)
        return {"ok": True, "tool": tool, "sent": text, "lines": lines,
                "note": "sent on headless x64dbg's stdin; x64dbg prints nothing for most of these commands, and "
                        "the lines may include logging-breakpoint hits, so confirm the effect with bplist"}

    def bplist(self) -> dict[str, Any]:
        gate = self._gate("bplist")
        if gate:
            return gate
        try:
            lines = self._bplist_lines()
        except Refused as r:
            return _refusal("bplist", r.reason, r.detail)
        rows = [ln for ln in lines if _BPLIST_ROW.match(ln)]
        return {"ok": True, "tool": "bplist", "lines": lines, "breakpoints": rows,
                "disabled": [ln for ln in rows if _BPLIST_ROW.match(ln).group(1) == "0"]}  # type: ignore[union-attr]

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
        result = {"ok": not is_error, "tool": "modules", "reply": text,
                  "bases": {k: f"0x{v:X}" for k, v in module_bases(text).items()},
                  "unreadable": unreadable_module_rows(text)}
        if result["unreadable"]:
            result["note"] = ("these rows are not in the pinned plugin's format (decimal base, end and size behind "
                              "0x, end = base + size, base on a 64 KiB boundary), so no base was read from them; "
                              "an address in one of these modules is refused with module_row_unreadable")
        return result

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
        # would leave the debugger attached. Served from an unconfirmed attach
        # and as a retry of an unconfirmed detach, too.
        gate = self._gate("detach", need_lease=False,
                          states=("running", "attach-unconfirmed", "detach-unconfirmed"))
        if gate:
            return gate
        try:
            reply = keeper_request(self.cfg, "detach", timeout=detach_wait(self.cfg))
        except Refused as r:
            return _refusal("detach", r.reason, r.detail)
        return {"tool": "detach", **reply, **session_summary(self.cfg)}


def module_row_base(line: str) -> tuple[str, int] | None:
    """(lower-cased name, base) from one row of GetAllModulesFromMemMap's
    table in the pinned plugin's format (`_MODULE_ROW`), or None. Besides the
    format and end == base + size, the base must sit on a 64 KiB boundary, as
    every image Windows maps does: an unpadded hex rendering made only of the
    digits 0-9 with no carry from base to end (0x180000000 0x180001000 0x1000)
    passes the other two rules under a decimal reading, and its decimal
    misreading (180000000, 0xABA9500) is not on one."""
    m = _MODULE_ROW.match(line.strip())
    if not m:
        return None
    base, end, size = (int(g, 10) for g in m.group(2, 3, 4))
    if end != base + size or base % _IMAGE_ALIGNMENT:
        return None
    return m.group(1).lower(), base


def module_bases(text: str) -> dict[str, int]:
    """Lower-cased module name -> base, from GetAllModulesFromMemMap's table,
    for each row `module_row_base` reads. A row in any other format gives no
    base."""
    out = {}
    for line in text.splitlines():
        row = module_row_base(line)
        if row:
            out[row[0]] = row[1]
    return out


def unreadable_module_rows(text: str) -> list[str]:
    """The table's rows that end in three `0x` columns, as a module row does,
    but that `module_row_base` does not read: present, and refused."""
    return [line.strip() for line in text.splitlines()
            if _MODULE_ROW_SHAPE.search(line) and module_row_base(line) is None]


def module_row(text: str, name: str) -> str | None:
    """The table row whose first column is `name` (any case), or None."""
    for line in text.splitlines():
        words = line.split(None, 1)
        if words and words[0].lower() == name.lower():
            return line.strip()
    return None


def bplist_entry(lines: list[str], addr: int) -> str | None:
    """How bplist lists `addr`: "armed" (an enabled hardware breakpoint,
    `1:HW:<addr>`), "disabled" (`0:HW:<addr>`: listed, and never logs), the
    type of another kind of breakpoint there, or None when no row names it."""
    found = None
    for line in lines:
        m = _BPLIST_ROW.match(line)
        if not m or int(m.group(3), 16) != addr:
            continue
        if m.group(2).upper() != "HW":
            found = found or m.group(2)
        elif m.group(1) != "0":
            return "armed"
        else:
            found = "disabled"
    return found


def listing_bytes(text: str, addr: int) -> bytes:
    """The code bytes of a ReadDismAtAddress listing, from its first row at
    `addr` for as long as the rows run on without a gap."""
    out, at = bytearray(), addr
    for line in text.splitlines():
        m = _LISTING_ROW.match(line)
        if not m:
            continue
        row = int(m.group(1), 16)
        if row != at:
            if out:
                break
            continue
        data = bytes.fromhex(m.group(2).replace("-", ""))
        out += data
        at += len(data)
    return bytes(out)


# --- serve ------------------------------------------------------------------

DESCRIPTIONS = {
    "status": "Session state (none, attaching, attach-unconfirmed, running, detaching, ended, "
              "detach-unconfirmed, game-not-released), target pid, keeper and headless alive, x64dbg's own "
              "state (x64dbg_state), the pauses the keeper resumed (breaks_resumed, last_break, break_storm), "
              "the outside check's control (instrument) and a fresh check of the game, whether the plugin "
              "answers on 127.0.0.1, and the hs-drive lease. attach-unconfirmed: the game may be paused; run "
              "detach.",
    "logpoint": "Add one non-breaking hardware logging breakpoint (bph, never breaks). address: 0x<hex> or "
                "<module>+<hex>, e.g. Hero_Siege.exe+427460. log: an x64dbg log format string, braces allowed, "
                "no double quote. expect_bytes: the function's first bytes from Ghidra (hex); a mismatch is "
                "refused before anything is set, and without it a zero from this address is not evidence. "
                "Never pauses the game: arms it on the running game (held at a hit of a logging breakpoint "
                "when one is armed), reads bplist back (enabled hardware row required), watches for a break on "
                "it, and checks from outside the debugger that the game runs; any failure clears it. Refused "
                "while x64dbg is not running, during a break storm, or when bplist lists the address already. "
                "Four hardware breakpoints at most: start with a positive control.",
    "command": "One allowlisted x64dbg command, sent on headless x64dbg's stdin: delete, enable or disable a "
               "hardware breakpoint (through a hold, as logpoint arms), name it, set its log condition, reset "
               "its hit count, or bplist. Anything else is refused. Most print nothing: confirm with bplist.",
    "bplist": "Send bplist and return the log lines it produced (the only trustworthy breakpoint list; "
              "the plugin's GetBreakpointInfo is not).",
    "log": "Lines of the session log after line number `after` (default: the last `limit`), with the total "
           "line count, to page through logging-breakpoint hits.",
    "modules": "The debuggee's modules with their bases (gives Hero_Siege.exe's base).",
    "disasm": "Disassemble byte_count bytes at an address (0x<hex> or <module>+<hex>), to check an address "
              "against Ghidra. Disassembled game code: never paste it into a tracked file.",
    "detach": "Delete every hardware breakpoint, let the game run, detach, confirm, end headless x64dbg, then "
              "check the game's threads from outside the debugger: game-not-released (ok false) names the "
              "threads left suspended, which only hs_stop_game with force=true releases. Detach before "
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

    def logpoint(address: str, log: str, log_condition: str | None = None, name: str | None = None,
                 expect_bytes: str | None = None) -> dict[str, Any]:
        return tools.logpoint(address, log, log_condition, name, expect_bytes)

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


def tool_cli(cfg: Config, name: str, raw: str | None) -> int:
    """`tool <name> [<json object>]`: one of the eight tools from a shell, for
    an operator whose session has not loaded the MCP server. The same `Tools`
    method `serve` registers, so the same gates, under the same offline guard.
    Prints the reply as one JSON object; exits 0 when its `ok` is true, 1 when
    not, and 2 for a name or arguments it cannot call."""
    if name not in LIVE_OPERATOR_TOOLS:
        print(f"x64dbg_mcp tool: {name!r} is not one of the eight tools ({', '.join(LIVE_OPERATOR_TOOLS)})",
              file=sys.stderr)
        return 2
    try:
        args = json.loads(raw) if raw is not None else {}
    except ValueError as e:
        args = e
    if not isinstance(args, dict):
        print(f"x64dbg_mcp tool: the arguments must be one JSON object, e.g. '{{\"after\": 120}}', not {raw!r}",
              file=sys.stderr)
        return 2
    install_offline_guard(allowed_executables=())
    method = getattr(Tools(cfg), name)
    try:
        inspect.signature(method).bind(**args)
    except TypeError as e:
        params = ", ".join(inspect.signature(method).parameters) or "no arguments"
        print(f"x64dbg_mcp tool: {name} takes {params}; {e}", file=sys.stderr)
        return 2
    try:
        reply = method(**args)
    except (TypeError, ValueError) as e:
        # the names bound, a value did not (`{"after": "x"}`)
        print(f"x64dbg_mcp tool: {name} could not take {raw}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(json.dumps(reply, default=str))
    return 0 if reply.get("ok") is True else 1


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
    sub = ap.add_subparsers(dest="cmd", metavar="{serve,status,setup,attach,detach,tool}")
    sub.add_parser("serve", help="the stdio MCP server (the default; what .mcp.json runs)")
    sub.add_parser("status", help="paths, pins, what is missing, the session and the lease")
    sub.add_parser("setup", help="download, clone, edit, build and install, each step skipped when done")
    a = sub.add_parser("attach", help="attach headless x64dbg to the game under the hs-drive lease")
    a.add_argument("pid", nargs="?", type=int)
    a.add_argument("--game", action="store_true", help=f"the sole running {GAME_IMAGE}")
    sub.add_parser("detach", help="detach (confirmed), then end headless x64dbg")
    t = sub.add_parser("tool", help="call one of the eight MCP tools from a shell, its reply printed as JSON "
                                    "(for a session that has not loaded the x64dbg server)")
    t.add_argument("name", help=f"one of: {', '.join(LIVE_OPERATOR_TOOLS)}")
    t.add_argument("arguments", nargs="?", help="the tool's arguments as one JSON object, e.g. '{\"after\": 120}'")
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
    if args.cmd == "tool":
        return tool_cli(cfg, args.name, args.arguments)
    return detach(cfg)


if __name__ == "__main__":
    sys.exit(main())
