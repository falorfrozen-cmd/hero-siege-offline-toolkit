"""tools/x64dbg_mcp.py: the `x64dbg` MCP server's launcher, keeper and proxy.

Every case runs on temp-directory fixtures: a fake x64dbg tree, a fake plugin
clone, a stand-in HTTP server on 127.0.0.1 for the plugin, a fake headless
x64dbg (`tests/x64dbg_fake_headless.py`, run by this interpreter: it records
the lines it reads on stdin and prints what x64dbg would, `[STATE]` lines and
breaks included), and a stand-in game (a child with three threads sleeping
2 ms in a loop). The outside check of the game comes from the fake headless's
probe seam, except in the `real_os` cases, which read the stand-in game's
real threads and suspend them for real. Nothing here downloads, clones, runs
MSBuild, starts x64dbg, touches the game, or reads the real hs-drive lease:
`HS_DRIVE_LEASE_DIR` points at a temp directory, and the module's own offline
guard is installed around every case, so a fetch off 127.0.0.1 or an
unexpected process fails the test instead of running.

What is pinned is the launcher's contract, the part a careless edit could
quietly break:
- the plugin is reached on loopback only, and installed to listen there;
- nothing it writes lands inside a git tree;
- the two plugin edits apply exactly, skip when already applied, keep line
  endings, and refuse anything else before writing;
- the build line and environment, and the two-file install;
- `attach` refuses without a live lease, a game pid, an install, a game the
  outside check reads running, or while a session is live; the keeper reads
  x64dbg's state from the session log only and waits for no attach break
  (headless x64dbg takes none, as the Replan 3 probe measured): an attach is
  ready once the plugin answers, x64dbg has settled at running and the
  outside check reads the game running, after one defensive `bphc` for a
  breakpoint restored from x64dbg's database; it resumes every pause x64dbg
  takes on its own (counted, with a storm flag); the outside check must read
  the game frozen at the first hold at a hardware-breakpoint hit (the control
  hold), naming every thread seen before attach as suspended and stopped
  there, for the instrument to count as proven, and an unproven one never
  reports a detach as releasing the game; an attach it never saw settle is
  `attach-unconfirmed` (refused by every tool but `detach`) until it does; a
  `hold` changes breakpoints between markers, held at a hit of a logging
  breakpoint when one is armed, or at a new breakpoint's own first hit;
  teardown is a held `bphc`, a settle at running, `detach`, confirm, `exit`
  and the outside check, which ends `game-not-released` when game threads
  stay suspended, never killing an unconfirmed headless;
- `logpoint` and `command` never pause the game: no `pause` on stdin and no
  plugin `PauseDebug`, `run` or `ExecuteDbgCommand`. They arm and change
  hardware breakpoints through a hold, held at a hit of a logging breakpoint
  when one is armed. A `bph` x64dbg reported set and never listed, a row
  listed but disabled, a never-break condition x64dbg rejected or that did
  not take (a break on it in the verification window), a game the outside
  check does not read running, and code that differs from `expect_bytes` are
  none of them a pass, and each is cleared;
- the module table is read as the pinned plugin prints it (decimal behind
  `0x`, live 1's row verbatim), and a row in any other format is refused;
- a keeper that never saw x64dbg settle at running leaves the session
  `attach-unconfirmed`, not ready;
- the CLI `tool` route serves exactly the eight tools, through the same gates;
- a server whose module changed on disk since import refuses every tool but
  `status` (`stale_server`), and the keeper refuses a hold or send from other
  code but still detaches;
- `.mcp.json` and Codex start the stdio launcher, not the plugin's URL.
Each acceptance has a negative control beside it.
"""
import asyncio
import contextlib
import http.server
import io
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import x64dbg_mcp as xm  # noqa: E402

# Every child these tests start runs without a console window on Windows.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

_STATE: dict = {}


def setUpModule():  # noqa: N802
    _STATE["lease_dir"] = tempfile.mkdtemp(prefix="x64dbg-mcp-lease-")
    _STATE["env"] = os.environ.get("HS_DRIVE_LEASE_DIR")
    os.environ["HS_DRIVE_LEASE_DIR"] = _STATE["lease_dir"]
    _STATE["uninstall"] = xm.install_offline_guard((sys.executable,))


def tearDownModule():  # noqa: N802
    _STATE["uninstall"]()
    if _STATE["env"] is None:
        os.environ.pop("HS_DRIVE_LEASE_DIR", None)
    else:
        os.environ["HS_DRIVE_LEASE_DIR"] = _STATE["env"]
    shutil.rmtree(_STATE["lease_dir"], ignore_errors=True)


# --- fixtures ---------------------------------------------------------------

def _cfg(base: Path, **over) -> xm.Config:
    values = dict(x64dbg=base / "x64dbg", download=base / "x64dbg-dl", plugin_src=base / "x64dbg-mcp-src",
                  dotnet=base / "dotnet-sdk", session=base / "session", port=50300,
                  ready_timeout=10, detach_timeout=5, settle=0.3, poll=0.05, hold_timeout=5)
    values.update(over)
    return xm.Config(**values)


def _install_fixture(cfg: xm.Config, address: str = xm.LOOPBACK) -> None:
    """Everything `problems()` asks for, as stand-ins."""
    cfg.headless.parent.mkdir(parents=True, exist_ok=True)
    cfg.headless.write_bytes(b"")
    (cfg.x64dbg / "commithash.txt").write_text(xm.X64DBG_COMMIT + "\n", encoding="utf-8")
    cfg.plugin_dir.mkdir(parents=True, exist_ok=True)
    cfg.installed_plugin.write_bytes(b"dp64")
    cfg.plugin_config.write_text(json.dumps({"IpAddress": address, "Port": cfg.port}), encoding="utf-8")


# Synthetic stand-ins for the two plugin files: each fragment the edits anchor
# on, inside filler of our own. No upstream text beyond the fragments.
def _upstream_files(newline: bytes) -> dict[str, bytes]:
    cfg_lines = [b"// stand-in", b"        " + xm.PLUGIN_EDITS[0].upstream, b"// filler",
                 b"                            " + xm.PLUGIN_EDITS[1].upstream, b"// end"]
    log_lines = [b"// stand-in", b"            " + xm.PLUGIN_EDITS[2].upstream, b"// end"]
    return {xm.PLUGIN_EDITS[0].path: newline.join(cfg_lines) + newline,
            xm.PLUGIN_EDITS[2].path: newline.join(log_lines) + newline}


def _write_tree(src: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)


def _hold_lease(holder=None, state="held") -> None:
    lease = xm._lease()
    lease.lease_dir().mkdir(parents=True, exist_ok=True)
    lease.record_path().write_text(json.dumps({
        "schema": lease.SCHEMA, "state": state, "lease_id": "x64dbg-test", "label": "x64dbg-test",
        "holder": holder or lease.process_identity()}), encoding="utf-8")


def _drop_lease() -> None:
    try:
        xm._lease().record_path().unlink()
    except FileNotFoundError:
        pass


DEAD = {"pid": 4194300, "pid_start": 1}


def _fake_live_session(cfg: xm.Config) -> None:
    """A state file naming this process as the keeper: the gate's view of a
    running session, without starting one."""
    cfg.session.mkdir(parents=True, exist_ok=True)
    me = xm._lease().process_identity()
    xm.write_json(cfg.state_file, {"schema": xm.SESSION_SCHEMA, "state": "running", "target_pid": 1,
                                   "keeper": me, "headless": None})


FAKE_HEADLESS = Path(__file__).resolve().parent / "x64dbg_fake_headless.py"

# The stand-in game: three threads sleeping 2 ms in a loop, as the outside
# check's own probe ran (tests/test_thread_state.py). It prints its workers'
# thread ids, so a test can name the one `leak_on_detach` leaves running.
STAND_IN_GAME = ("import json,threading,time\n"
                 "def work():\n"
                 "    while True: time.sleep(0.002)\n"
                 "ts=[threading.Thread(target=work,daemon=True) for _ in range(3)]\n"
                 "[t.start() for t in ts]\n"
                 "print(json.dumps([t.native_id for t in ts]),flush=True)\n"
                 "time.sleep(300)\n")

REAL_OS_SKIP = None
if sys.platform != "win32":
    REAL_OS_SKIP = "real_os cases suspend and read Windows threads; this is not Windows"
elif struct.calcsize("P") != 8:
    REAL_OS_SKIP = "real_os cases need a 64-bit Python, whose layout tools/thread_state.py parses"

GAME_BASE = 0x7FF6A0000000
A = GAME_BASE + 0x427460
B = GAME_BASE + 0x428000
C = GAME_BASE + 0x429000


def _module_table(rows) -> str:
    """GetAllModulesFromMemMap's table as the pinned plugin lays it out: the
    name and path columns padded, then base, end and size each behind `0x`."""
    head = (f"[GetAllModulesFromMemMap] Found {len(rows)} image modules:\n"
            f"{'Name':<30} {'Path':<70} {'Base Address':<18} {'End Address':<18} {'Size':<10}\n" + "-" * 150 + "\n")
    return head + "".join(f"{n:<30} {p:<70} 0x{b} 0x{e} 0x{s}\n" for n, p, b, e, s in rows)


# What the pinned plugin prints: decimal digits behind a literal `0x` (it
# targets net472, where a pointer-sized integer ignores the hex format
# specifier). Measured live on 2026-10-10.
MODULE_TABLE = _module_table([
    ("Hero_Siege.exe", "C:/Games/Hero Siege/Hero_Siege.exe", GAME_BASE, GAME_BASE + 0x9000000, 0x9000000),
    ("kernel32.dll", "C:/Windows/System32/kernel32.dll", 0x7FFB10000000, 0x7FFB100C0000, 0xC0000),
])
# The format the real plugin never printed, and the stand-in used to: padded
# hex. Every round that served this passed while the live resolve was wrong.
HEX_MODULE_TABLE = _module_table([
    ("Hero_Siege.exe", "C:/Games/Hero Siege/Hero_Siege.exe", "00007FF6A0000000", "00007FF6A9000000", "9000000"),
    ("kernel32.dll", "C:/Windows/System32/kernel32.dll", "00007FFB10000000", "00007FFB100C0000", "C0000"),
])
# Live 1's row for the game, verbatim (tooling-484-x64dbg-mcp, 2026-10-10).
LIVE_ROW = "hero_siege.exe  hero_siege.exe  0x140694867017728 0x140695154032640 0x287014912"
LIVE_BASE = 0x7FF613920000


# The stand-in function's first instructions, as the plugin's listing shows
# them: synthetic bytes of our own, not the game's.
CODE = (bytes.fromhex("4889542410"), bytes.fromhex("53"), bytes.fromhex("4883EC30"), bytes.fromhex("90"))


class StandInPlugin:
    """The plugin's MCP endpoint, as far as this proxy uses it. Whether x64dbg
    is "debugging" follows the fake headless's stdin record, as the real
    plugin follows x64dbg's state. Breakpoints live in the fake headless
    (`bps`, its list, which this stand-in never writes). It logs every call.

    No tool path calls its ExecuteDbgCommand, `run` or `PauseDebug` any more,
    and the tests assert that; they answer as the pinned plugin does.
    ExecuteDbgCommand replies with the plugin's own echo of the call (`echo`:
    `full`, the default and what live 1 measured, `tail` or `none`). `run`
    answers RUNNING and touches nothing. `PauseDebug` is asynchronous, as
    Live 2 measured: it answers the "settling" text and leaves a request that
    the fake headless turns into a break a few seconds later. `module_table`
    is what GetAllModulesFromMemMap prints."""

    SETTLING = "Pause command sent but process may still be settling. Try again or use StepInto."

    def __init__(self, record: Path, bps: Path, *, sse=False, never_detach=False, never_ready=False,
                 debugging=None, execute_arg="command", module_table=MODULE_TABLE, echo="full"):
        self.record, self.bps = record, bps
        self.echo = echo
        self.sse, self.never_detach = sse, never_detach
        self.never_ready, self.forced, self.execute_arg = never_ready, debugging, execute_arg
        self.module_table = module_table
        self.calls: list[tuple[str, dict]] = []
        self.sessions: list[str | None] = []
        plugin = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                plugin.sessions.append(self.headers.get("Mcp-Session-Id"))
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                result = plugin.dispatch(body["method"], body.get("params") or {})
                msg = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200)
                if body["method"] == "initialize":
                    self.send_header("Mcp-Session-Id", "standin-session")
                if plugin.sse:
                    msg = b"event: message\ndata: " + msg + b"\n\n"
                    self.send_header("Content-Type", "text/event-stream")
                else:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer((xm.LOOPBACK, 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.srv.server_address[1]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def debugging(self) -> bool:
        if self.forced is not None:
            return self.forced
        if self.never_ready:
            return False
        state = False
        lines = self.record.read_text(encoding="utf-8").splitlines() if self.record.exists() else []
        for line in lines:
            if line.startswith("attach"):
                state = True
            elif (line == "detach" and not self.never_detach) or line == "exit":
                state = False
        return state

    def _tool(self, name, props=()):
        return {"name": name, "description": "stand-in",
                "inputSchema": {"type": "object", "properties": {p: {"type": "string"} for p in props}}}

    def dispatch(self, method, params):
        if method == "initialize":
            return {"protocolVersion": "2025-11-25", "serverInfo": {"name": "stand-in"}}
        if method == "tools/list":
            tools = [self._tool("Echo", ("message",))]
            if self.debugging():
                tools += [self._tool(xm.PLUGIN_EXECUTE, (self.execute_arg,)), self._tool(xm.PLUGIN_MODULES),
                          self._tool(xm.PLUGIN_DISASM, ("address", "byteCount")), self._tool(xm.PLUGIN_PAUSE),
                          self._tool(xm.PLUGIN_RUN), self._tool("StopDebug")]
            return {"tools": tools}
        if method == "tools/call":
            name, args = params["name"], params.get("arguments") or {}
            self.calls.append((name, args))
            if not self.debugging():
                return self._content(f"Tool '{name}' requires an active debug session, but the debugger is not "
                                     "currently debugging a target. Load/attach a target first.", True)
            return self._content(*self.call(name, args))
        return {}

    def _content(self, text, is_error=False):
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def call(self, name, args):
        if name == xm.PLUGIN_EXECUTE:
            return self._execute_reply(args.get(self.execute_arg, ""), []), False
        if name == xm.PLUGIN_MODULES:
            return self.module_table, False
        if name == xm.PLUGIN_PAUSE:
            # x64dbg's `pause` lands when a thread next runs the planted
            # instruction: the fake headless breaks a few seconds later
            (self.record.parent / "pause_request").write_text(str(time.time()), encoding="utf-8")
            return self.SETTLING, False
        if name == xm.PLUGIN_RUN:
            return "STATUS: RUNNING. The target process is now in a running state.", False
        if name == xm.PLUGIN_DISASM:
            at = int(str(args.get("address")), 16)
            rows = [f"stand-in listing for {args.get('address')} ({args.get('byteCount')} bytes)"]
            for ins in CODE:
                rows.append(f"{at:016X}  {'-'.join(f'{b:02X}' for b in ins):<20}  stand-in instruction")
                at += len(ins)
            return "\n".join(rows) + "\n", False
        return f"Tool '{name}' not found.", True

    def _execute_reply(self, cmd, printed):
        """ExecuteDbgCommand's reply as the pinned plugin builds it: whatever
        reached x64dbg's log while the command ran, behind `Result: `. The
        plugin writes its own echo of the call to that log first, so the
        capture carries all of the echo (`full`, live 1's SetHardwareBreakpointLog),
        only its last line (`tail`, live 1's bphc), or none of it (`none`),
        then what x64dbg printed. Blank, it is the no-output success text."""
        rule = "-" * 40
        echo = {"full": [rule, "METHOD: ExecuteDbgCommand", f"command: {cmd}", rule,
                         f"Executing DbgCmdExec: {cmd}"],
                "tail": [f"Executing DbgCmdExec: {cmd}"], "none": []}[self.echo]
        lines = echo + list(printed)
        return "Result: " + "\r\n".join(lines) if lines else f"Result: {xm.PLUGIN_EXEC_SILENT_OK}"

    def names(self):
        return [n for n, _ in self.calls]


def _kill(identity) -> None:
    if identity and xm.alive(identity):
        try:
            os.kill(int(identity["pid"]), signal.SIGTERM)
        except OSError:
            pass


class SessionMixin:
    """A real keeper process, the fake headless, the stand-in plugin and the
    stand-in game. `fake` sets the fake headless's modes
    (tests/x64dbg_fake_headless.py); `probe=False` reads the stand-in game's
    real threads instead of the probe seam."""

    def start_session(self, cfg_over=None, fake=None, probe=True, **plugin_kw):
        base = Path(tempfile.mkdtemp(prefix="x64dbg-mcp-session-"))
        self.addCleanup(shutil.rmtree, base, True)
        self.work = base / "work"
        self.work.mkdir()
        record, bps = self.work / "stdin.txt", self.work / "bps.json"
        plugin = StandInPlugin(record, bps, **plugin_kw)
        self.addCleanup(plugin.close)
        probe_cmd = (sys.executable, str(FAKE_HEADLESS), "probe", str(self.work)) if probe else None
        cfg = _cfg(base, port=plugin.port, headless_cmd=(sys.executable, str(FAKE_HEADLESS), str(self.work)),
                   probe_cmd=probe_cmd, **(cfg_over or {}))
        _install_fixture(cfg)
        target = subprocess.Popen([sys.executable, "-I", "-c", STAND_IN_GAME], stdout=subprocess.PIPE, text=True,
                                  **NO_WINDOW)
        self.addCleanup(target.stdout.close)
        self.addCleanup(target.wait)
        self.addCleanup(target.kill)
        self.workers = json.loads(target.stdout.readline())
        self.set_modes(**{"spare_tid": self.workers[0], **(fake or {})})
        time.sleep(0.3)
        _hold_lease()
        self.addCleanup(_drop_lease)
        self.addCleanup(self._stop_session, cfg)
        with mock.patch.object(xm, "image_name", return_value=xm.GAME_IMAGE):
            state = xm.start_session(cfg, target.pid, game=False)
        return cfg, plugin, state, record, target

    def set_modes(self, **changes):
        path = self.work / "modes.json"
        try:
            modes = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            modes = {}
        modes.update(changes)
        tmp = path.with_name("modes.json.tmp")
        tmp.write_text(json.dumps(modes), encoding="utf-8")
        os.replace(tmp, path)

    def _stop_session(self, cfg):
        state = xm.read_state(cfg)
        _kill(state.get("keeper"))
        _kill(state.get("headless"))

    def stdin_lines(self, record: Path) -> list[str]:
        return record.read_text(encoding="utf-8").splitlines() if record.exists() else []

    def log_lines(self, cfg) -> list[str]:
        return cfg.log_file.read_text(encoding="utf-8", errors="replace").splitlines()

    def wait_for(self, cfg, pred, timeout=15.0):
        """The session state once `pred(state)` holds, or the last one read."""
        deadline = time.monotonic() + timeout
        state = xm.read_state(cfg)
        while not pred(state) and time.monotonic() < deadline:
            time.sleep(0.05)
            state = xm.read_state(cfg)
        return state

    def detach_cli(self, cfg) -> tuple[int, dict]:
        """The CLI `detach`: its exit code and the reply it printed."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = xm.detach(cfg)
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def first_hit(self, cfg, addr, log="hot") -> dict:
        """The keeper's first-hit hold, as the control logpoint asks for it:
        `bph <addr>, x, 1` (breaking), then, held at its first hit, the
        never-break condition and the log text."""
        return xm.keeper_request(cfg, "hold", timeout=60, first_hit=f"bph 0x{addr:X}, x, 1",
                                 lines=[f"SetHardwareBreakpointCondition 0x{addr:X}, 0",
                                        f'SetHardwareBreakpointLog 0x{addr:X}, "{log}"'])

    def prove(self, cfg, addr=A) -> dict:
        """Prove the instrument: a hot control's first-hit hold, which the
        outside check must read frozen."""
        self.set_modes(hot=[addr])
        reply = self.first_hit(cfg, addr)
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(xm.read_state(cfg)["instrument"]["proven"], xm.read_state(cfg)["instrument"])
        return reply


# --- configuration, loopback ------------------------------------------------

class ConfigTests(unittest.TestCase):
    def test_defaults_follow_the_owner_layout(self):
        with tempfile.TemporaryDirectory() as d:
            user = Path(d)
            cfg = xm.load_config({"USERPROFILE": str(user)})
            tools = user / "tools"
            self.assertEqual((cfg.x64dbg, cfg.download, cfg.plugin_src, cfg.dotnet, cfg.session),
                             (tools / "x64dbg", tools / "x64dbg-dl", tools / "x64dbg-mcp-src",
                              tools / "dotnet-sdk", tools / "x64dbg-mcp-session"))
            self.assertEqual(cfg.port, 50300)
            self.assertEqual(cfg.headless, tools / "x64dbg" / "release" / "x64" / "headless.exe")
            self.assertEqual(cfg.installed_plugin.parent,
                             tools / "x64dbg" / "release" / "x64" / "plugins" / "x64DbgMCPServer")

    def test_env_overrides_each_path(self):
        cfg = xm.load_config({"USERPROFILE": "U", "HS_X64DBG_DIR": "X", "HS_X64DBG_DL_DIR": "D",
                              "HS_X64DBG_MCP_SRC": "S", "HS_X64DBG_DOTNET": "N",
                              "HS_X64DBG_MCP_SESSION": "E", "HS_X64DBG_MCP_PORT": "50999"})
        self.assertEqual((cfg.x64dbg, cfg.download, cfg.plugin_src, cfg.dotnet, cfg.session, cfg.port),
                         (Path("X"), Path("D"), Path("S"), Path("N"), Path("E"), 50999))

    def test_loopback_url_whatever_the_port(self):
        for port in ("50300", "61000"):
            cfg = xm.load_config({"USERPROFILE": "U", "HS_X64DBG_MCP_PORT": port})
            self.assertEqual(cfg.url, f"http://127.0.0.1:{port}/")

    def test_pins_are_full_and_named(self):
        self.assertRegex(xm.X64DBG_SHA256, r"^[0-9a-f]{64}$")
        self.assertRegex(xm.X64DBG_COMMIT, r"^[0-9a-f]{40}$")
        self.assertRegex(xm.PLUGIN_COMMIT, r"^[0-9a-f]{40}$")
        self.assertTrue(xm.PLUGIN_COMMIT.startswith("a8303d7"))
        self.assertIn(xm.X64DBG_TAG, xm.X64DBG_URL)
        self.assertTrue(xm.X64DBG_URL.endswith(xm.X64DBG_ASSET))

    def test_the_tool_set_is_the_eight_names(self):
        self.assertEqual(sorted(xm.LIVE_OPERATOR_TOOLS),
                         sorted(["status", "logpoint", "command", "bplist", "log", "modules", "disasm", "detach"]))
        self.assertIsInstance(xm.LIVE_OPERATOR_TOOLS, tuple)

    def test_loopback_problems_flag_a_plugin_listening_elsewhere(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            _install_fixture(cfg)
            self.assertEqual(xm.problems(cfg), [])
            # negative control: the same install, listening on every interface
            _install_fixture(cfg, address="+")
            found = xm.problems(cfg)
            self.assertEqual(len(found), 1)
            self.assertIn("not 127.0.0.1", found[0])

    def test_refuses_an_install_that_is_missing_or_another_build(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            self.assertEqual(len(xm.problems(cfg)), 3)
            self.assertTrue(all("setup" in p for p in xm.problems(cfg)))
            _install_fixture(cfg)
            (cfg.x64dbg / "commithash.txt").write_text("0" * 40, encoding="utf-8")
            self.assertIn("no x64dbg", xm.problems(cfg)[0])


class GitTreeTests(unittest.TestCase):
    def _repo(self, base: Path) -> Path:
        repo = base / "repo"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: elsewhere", encoding="utf-8")  # a worktree's .git is a file
        return repo

    def test_git_tree_refuses_each_written_directory(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(Path(d))
            for field in ("x64dbg", "download", "plugin_src", "session"):
                with self.subTest(field=field):
                    cfg = _cfg(Path(d) / "outside", **{field: repo / "tools" / field})
                    refused = []
                    for path, what in xm.written_directories(cfg):
                        try:
                            xm.refuse_inside_git(path, what)
                        except SystemExit as e:
                            refused.append(str(e))
                    self.assertEqual(len(refused), 1, refused)
                    self.assertIn("Legal", refused[0])

    def test_git_tree_control_allows_directories_outside_any_tree(self):
        with tempfile.TemporaryDirectory() as d:
            for path, what in xm.written_directories(_cfg(Path(d))):
                xm.refuse_inside_git(path, what)

    def test_git_tree_the_clone_itself_may_be_a_repository(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            cfg.plugin_src.mkdir()
            (cfg.plugin_src / ".git").mkdir()
            for path, what in xm.written_directories(cfg):
                xm.refuse_inside_git(path, what)

    def test_git_tree_setup_refuses_before_writing_anything(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d), x64dbg=ROOT / ".claude" / "scratch" / "x64dbg-never")
            with self.assertRaises(SystemExit) as cm:
                xm.setup(cfg)
            self.assertIn("Legal", str(cm.exception))
            self.assertFalse(cfg.x64dbg.exists())
            self.assertFalse(cfg.download.exists())

    def test_git_tree_attach_refuses_a_session_inside_this_repository(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d), session=ROOT / ".claude" / "scratch" / "x64dbg-session-never")
            _install_fixture(cfg)
            _hold_lease()
            self.addCleanup(_drop_lease)
            with mock.patch.object(xm, "image_name", return_value=xm.GAME_IMAGE):
                with self.assertRaises(SystemExit):
                    xm.start_session(cfg, 1234, game=False)
            self.assertFalse(cfg.session.exists())


# --- the plugin edits -------------------------------------------------------

class PatchTests(unittest.TestCase):
    def test_patch_applies_on_crlf_and_lf_and_keeps_the_endings(self):
        for newline in (b"\r\n", b"\n"):
            with self.subTest(newline=newline), tempfile.TemporaryDirectory() as d:
                src = Path(d)
                _write_tree(src, _upstream_files(newline))
                outcomes = xm.apply_plugin_edits(src)
                self.assertEqual(outcomes, {xm.PLUGIN_EDITS[0].path: ["applied", "applied"],
                                            xm.PLUGIN_EDITS[2].path: ["applied"]})
                for edit in xm.PLUGIN_EDITS:
                    data = (src / edit.path).read_bytes()
                    self.assertEqual(data.count(edit.ours), 1)
                    self.assertNotIn(edit.upstream, data)
                    lines = data.split(b"\n")[:-1]
                    self.assertTrue(all(ln.endswith(b"\r") == (newline == b"\r\n") for ln in lines))

    def test_patch_already_applied_is_skipped_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)
            _write_tree(src, _upstream_files(b"\n"))
            xm.apply_plugin_edits(src)
            stamps = {e.path: (src / e.path).stat().st_mtime_ns for e in xm.PLUGIN_EDITS}
            time.sleep(0.02)
            outcomes = xm.apply_plugin_edits(src)
            self.assertEqual(set(o for v in outcomes.values() for o in v), {"already"})
            self.assertEqual(stamps, {e.path: (src / e.path).stat().st_mtime_ns for e in xm.PLUGIN_EDITS})

    def test_patch_refuses_a_fragment_found_twice(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)
            files = _upstream_files(b"\n")
            files[xm.PLUGIN_EDITS[2].path] += b"    " + xm.PLUGIN_EDITS[2].upstream + b"\n"
            _write_tree(src, files)
            with self.assertRaises(xm.EditRefused) as cm:
                xm.apply_plugin_edits(src)
            self.assertIn(xm.PLUGIN_EDITS[2].path, str(cm.exception))
            self.assertIn("found 2", str(cm.exception))

    def test_patch_refuses_a_missing_fragment_and_edits_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)
            files = _upstream_files(b"\n")
            files[xm.PLUGIN_EDITS[2].path] = b"// a different version of the file\n"
            _write_tree(src, files)
            before = (src / xm.PLUGIN_EDITS[0].path).read_bytes()
            with self.assertRaises(xm.EditRefused) as cm:
                xm.apply_plugin_edits(src)
            self.assertIn(xm.PLUGIN_EDITS[2].path, str(cm.exception))
            # the first file's edits were valid, and still nothing was written
            self.assertEqual((src / xm.PLUGIN_EDITS[0].path).read_bytes(), before)

    def test_patch_refuses_a_half_applied_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)
            files = _upstream_files(b"\n")
            files[xm.PLUGIN_EDITS[2].path] += b"    " + xm.PLUGIN_EDITS[2].ours + b"\n"
            _write_tree(src, files)
            with self.assertRaises(xm.EditRefused):
                xm.apply_plugin_edits(src)

    def test_patch_fragments_are_single_short_lines(self):
        # The plugin has no LICENSE: the edits carry fragments, never a body.
        paths = {e.path for e in xm.PLUGIN_EDITS}
        self.assertEqual(paths, {"DotNetPlugin.Impl/McpServerConfig.cs", "DotNetPlugin.Stub/NativeBindings/SDK/PLog.cs"})
        for e in xm.PLUGIN_EDITS:
            for frag in (e.upstream, e.ours):
                self.assertNotIn(b"\n", frag)
                self.assertLess(len(frag), 120)
        self.assertIn(b'"127.0.0.1"', xm.PLUGIN_EDITS[0].ours)
        self.assertIn(b"string.Format", xm.PLUGIN_EDITS[2].ours)

    def _git(self, files: dict[str, bytes], porcelain: bytes):
        def git(src, *args):
            if args[0] == "status":
                return porcelain
            if args[0] == "show":
                return files[args[1].split(":", 1)[1]]
            if args[0] == "rev-parse":
                return (xm.PLUGIN_COMMIT + "\n").encode()
            raise AssertionError(args)
        return git

    def test_patch_dirty_tree_with_only_our_edits_passes(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)
            upstream = _upstream_files(b"\r\n")
            _write_tree(src, _upstream_files(b"\n"))  # LF where git holds CRLF, as in the owner's clone
            xm.apply_plugin_edits(src)
            porcelain = b"".join(b" M " + p.encode() + b"\n" for p in upstream)
            self.assertEqual(xm.dirty_beyond_our_edits(src, self._git(upstream, porcelain)), [])

    def test_refuses_a_dirty_tree_naming_the_files(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)
            upstream = _upstream_files(b"\n")
            files = dict(upstream)
            files[xm.PLUGIN_EDITS[2].path] += b"// something else\n"
            _write_tree(src, files)
            porcelain = (b" M " + xm.PLUGIN_EDITS[2].path.encode() + b"\n"
                         b" M DotNetPlugin.Impl/MCPServer.cs\n?? DotNetPlugin.Impl/Extra.cs\n")
            bad = xm.dirty_beyond_our_edits(src, self._git(upstream, porcelain))
            self.assertEqual(sorted(bad), sorted([xm.PLUGIN_EDITS[2].path, "DotNetPlugin.Impl/MCPServer.cs",
                                                  "DotNetPlugin.Impl/Extra.cs"]))


# --- build and install ------------------------------------------------------

class BuildTests(unittest.TestCase):
    def test_build_command_pins_the_solution_targets_and_platform(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            cmd = xm.build_command(cfg, Path("C:/BT/MSBuild.exe"))
            self.assertEqual(cmd[0], str(Path("C:/BT/MSBuild.exe")))
            self.assertEqual(cmd[1], str(cfg.plugin_src / "x64DbgMCPServer.sln"))
            for flag in ("/restore", "/t:Build;RGieseckeDllExport", "/p:Configuration=Release", "/p:Platform=x64"):
                self.assertIn(flag, cmd)
            self.assertEqual(cfg.built_plugin, cfg.plugin_src / "bin" / "x64" / "Release" / "x64DbgMCPServer.dp64")

    def test_build_env_names_the_sdk_and_a_missing_x96dbg_root(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            env = xm.build_env(cfg, Path("N/sdk/8.0.425/Sdks"), base={"PATH": "p"})
            self.assertEqual(env["MSBuildSDKsPath"], str(Path("N/sdk/8.0.425/Sdks")))
            self.assertEqual(env["MSBuildEnableWorkloadResolver"], "false")
            self.assertFalse(Path(env["X96DBG_ROOT"]).exists())
            self.assertEqual(env["PATH"], "p")  # control: the rest passes through

    def test_build_refuses_an_x96dbg_root_that_exists(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            xm.no_x96dbg_root(cfg).mkdir(parents=True)
            with self.assertRaises(SystemExit):
                xm.build_env(cfg, Path("S"), base={})

    def test_build_finds_the_newest_dotnet_8_sdk(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            for v in ("8.0.100", "8.0.425", "9.0.100", "8.0.99"):
                (cfg.dotnet / "sdk" / v / "Sdks").mkdir(parents=True)
            self.assertEqual(xm.find_sdks_path(cfg), cfg.dotnet / "sdk" / "8.0.425" / "Sdks")

    def test_build_refuses_without_an_sdk_naming_the_fix(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            (cfg.dotnet / "sdk" / "9.0.100" / "Sdks").mkdir(parents=True)
            with mock.patch.object(xm.shutil, "which", return_value=None), \
                    mock.patch.object(xm, "find_msbuild", return_value=None):
                msbuild, sdks, missing = xm.build_prerequisites(cfg)
            self.assertIsNone(sdks)
            self.assertEqual(len(missing), 2)
            self.assertIn("HS_X64DBG_DOTNET", missing[0])
            self.assertIn("Build Tools", missing[1])

    def test_build_reads_dotnet_list_sdks_when_no_private_install(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            system = Path(d) / "system-dotnet" / "sdk"
            (system / "8.0.400" / "Sdks").mkdir(parents=True)
            listing = f"8.0.400 [{system}]\n9.0.100 [{system}]\n"
            run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, listing, ""))
            with mock.patch.object(xm.shutil, "which", return_value="dotnet"):
                self.assertEqual(xm.find_sdks_path(cfg, run=run), system / "8.0.400" / "Sdks")

    def test_build_install_copies_the_dp64_and_writes_a_loopback_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d), port=50301)
            cfg.built_plugin.parent.mkdir(parents=True)
            cfg.built_plugin.write_bytes(b"built plugin")
            changed = xm.install_plugin(cfg)
            self.assertEqual(len(changed), 2)
            self.assertEqual(cfg.installed_plugin.read_bytes(), b"built plugin")
            self.assertEqual(json.loads(cfg.plugin_config.read_text(encoding="utf-8")),
                             {"IpAddress": "127.0.0.1", "Port": 50301})
            self.assertEqual(sorted(p.name for p in cfg.plugin_dir.iterdir()),
                             ["mcp_config.json", "x64DbgMCPServer.dp64"])
            # control: a second run changes nothing
            self.assertEqual(xm.install_plugin(cfg), [])

    def test_build_is_current_only_when_newer_than_the_edited_sources(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            _write_tree(cfg.plugin_src, _upstream_files(b"\n"))
            self.assertFalse(xm.built_is_current(cfg))
            cfg.built_plugin.parent.mkdir(parents=True)
            cfg.built_plugin.write_bytes(b"x")
            later = time.time() + 100
            os.utime(cfg.built_plugin, (later, later))
            self.assertTrue(xm.built_is_current(cfg))
            os.utime(cfg.plugin_src / xm.PLUGIN_EDITS[2].path, (later + 10, later + 10))
            self.assertFalse(xm.built_is_current(cfg))


# --- setup, offline ---------------------------------------------------------

class OfflineTests(unittest.TestCase):
    def _complete(self, cfg: xm.Config) -> None:
        _install_fixture(cfg)
        _write_tree(cfg.plugin_src, _upstream_files(b"\r\n"))
        (cfg.plugin_src / ".git").mkdir()
        xm.apply_plugin_edits(cfg.plugin_src)
        cfg.built_plugin.parent.mkdir(parents=True)
        cfg.built_plugin.write_bytes(b"dp64")
        later = time.time() + 100
        os.utime(cfg.built_plugin, (later, later))

    def _git(self, porcelain=b""):
        def git(src, *args):
            if args[0] == "rev-parse":
                return (xm.PLUGIN_COMMIT + "\n").encode()
            if args[0] == "status":
                return porcelain
            raise AssertionError(f"unexpected git {args}")
        return git

    def test_offline_setup_passes_a_complete_install_through(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            self._complete(cfg)
            with mock.patch.object(xm, "_git", self._git()), \
                    mock.patch.object(xm, "build_prerequisites", side_effect=AssertionError("no build")), \
                    mock.patch("sys.stdout"):
                self.assertEqual(xm.setup(cfg), 0)

    def test_offline_setup_refuses_a_snapshot_with_the_wrong_sha256(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))

            def fake_download(url, out):
                self.assertEqual(url, xm.X64DBG_URL)
                Path(out).write_bytes(b"not the pinned snapshot")

            with mock.patch.object(xm.urllib.request, "urlretrieve", side_effect=fake_download), \
                    mock.patch("sys.stdout"):
                with self.assertRaises(SystemExit) as cm:
                    xm.setup(cfg)
            self.assertIn("sha256", str(cm.exception))
            self.assertFalse(cfg.snapshot_zip.exists())
            self.assertFalse(cfg.x64dbg.exists())

    def test_offline_setup_extracts_a_snapshot_whose_sha_matches(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            cfg.download.mkdir(parents=True)
            with zipfile.ZipFile(cfg.snapshot_zip, "w") as z:
                z.writestr("commithash.txt", xm.X64DBG_COMMIT)
                z.writestr("release/x64/headless.exe", b"")
            digest = xm._sha256(cfg.snapshot_zip)
            with mock.patch.object(xm, "X64DBG_SHA256", digest):
                xm.extract_snapshot(cfg, xm.fetch_snapshot(cfg))
            self.assertTrue(xm.x64dbg_installed(cfg))

    def test_offline_setup_refuses_a_tree_dirty_beyond_our_edits(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            self._complete(cfg)
            with mock.patch.object(xm, "_git", self._git(b"?? DotNetPlugin.Impl/Injected.cs\n")), \
                    mock.patch("sys.stdout"):
                with self.assertRaises(SystemExit) as cm:
                    xm.setup(cfg)
            self.assertIn("Injected.cs", str(cm.exception))

    def test_offline_guard_refuses_a_connection_off_loopback(self):
        with self.assertRaises(xm.OfflineGuardError):
            socket.create_connection(("192.0.2.1", 80), timeout=1)
        with self.assertRaises(xm.OfflineGuardError):
            urllib.request.urlopen("https://github.com/", timeout=1)

    def test_offline_guard_refuses_an_unexpected_process(self):
        with self.assertRaises(xm.OfflineGuardError):
            subprocess.run(["git", "--version"], capture_output=True, **NO_WINDOW)
        with self.assertRaises(xm.OfflineGuardError):
            subprocess.run("echo hi", shell=True, capture_output=True, **NO_WINDOW)
        # control: the interpreter the tests run is allowed
        self.assertEqual(subprocess.run([sys.executable, "-c", "pass"], **NO_WINDOW).returncode, 0)

    def test_offline_guard_control_loopback_connects(self):
        srv = socket.socket()
        srv.bind((xm.LOOPBACK, 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        with socket.create_connection(srv.getsockname(), timeout=2):
            pass

    def test_offline_module_imports_without_mcp(self):
        code = ("import sys; sys.modules['mcp'] = None; sys.path.insert(0, sys.argv[1]); "
                "import tools.x64dbg_mcp as x; print(len(x.LIVE_OPERATOR_TOOLS))")
        r = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True,
                           **NO_WINDOW)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "8")

    def test_offline_help_and_status_need_no_install(self):
        env = dict(os.environ, USERPROFILE=tempfile.gettempdir(), HOME=tempfile.gettempdir(),
                   HS_X64DBG_DIR=str(Path(tempfile.gettempdir()) / "x64dbg-mcp-absent"))
        r = subprocess.run([sys.executable, "-m", "tools.x64dbg_mcp", "--help"], cwd=str(ROOT),
                           capture_output=True, text=True, env=env, **NO_WINDOW)
        self.assertEqual(r.returncode, 0, r.stderr)
        for word in ("serve", "status", "setup", "attach", "detach", "tool"):
            self.assertIn(word, r.stdout)
        s = subprocess.run([sys.executable, "-m", "tools.x64dbg_mcp", "status"], cwd=str(ROOT),
                           capture_output=True, text=True, env=env, timeout=60, **NO_WINDOW)
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertIn("127.0.0.1", s.stdout)
        self.assertIn("missing", s.stdout)


# --- the lease and attach's refusals ----------------------------------------

class LeaseTests(unittest.TestCase):
    def tearDown(self):
        _drop_lease()

    def test_lease_held_by_a_live_process(self):
        _hold_lease()
        self.assertEqual(xm.lease_state()[0], "held")

    def test_lease_refuses_free_released_stale_and_unreadable(self):
        _drop_lease()
        self.assertEqual(xm.lease_state()[0], "free")
        _hold_lease(state="released")
        self.assertEqual(xm.lease_state()[0], "free")
        _hold_lease(holder=DEAD)
        self.assertEqual(xm.lease_state()[0], "stale")
        xm._lease().record_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(xm.lease_state()[0], "unavailable")


class AttachRefusalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = _cfg(Path(self.tmp.name))
        _install_fixture(self.cfg)
        _hold_lease()
        self.addCleanup(_drop_lease)

    def attempt(self, pid=1234, game=False, image=xm.GAME_IMAGE):
        popen = mock.Mock(side_effect=AssertionError("no keeper may start"))
        with mock.patch.object(xm, "image_name", return_value=image), \
                mock.patch.object(xm.subprocess, "Popen", popen):
            try:
                xm.start_session(self.cfg, pid, game)
            except xm.Refused as r:
                return r.reason
        return None

    def test_lease_refuses_attach_without_a_live_lease(self):
        for holder, state in ((DEAD, "held"), (None, "released")):
            with self.subTest(state=state):
                _hold_lease(holder=holder, state=state)
                self.assertEqual(self.attempt(), "no_lease")
        _drop_lease()
        self.assertEqual(self.attempt(), "no_lease")

    def test_refuses_a_pid_that_is_not_the_game(self):
        self.assertEqual(self.attempt(image="notepad.exe"), "not_the_game")
        self.assertEqual(self.attempt(image=None), "not_the_game")

    def test_refuses_when_x64dbg_or_the_plugin_is_not_installed(self):
        self.cfg.installed_plugin.unlink()
        self.assertEqual(self.attempt(), "not_installed")

    def test_refuses_a_second_session_while_one_is_live(self):
        _fake_live_session(self.cfg)
        self.assertEqual(self.attempt(), "session_live")

    def test_refuses_game_lookup_with_none_or_several(self):
        for pids in ([], [11, 12]):
            with self.subTest(pids=pids), mock.patch.object(xm, "game_pids", return_value=pids):
                self.assertEqual(self.attempt(pid=None, game=True), "no_single_game")

    def test_refuses_a_game_the_outside_check_does_not_read_running(self):
        for verdict, reason in (("frozen", "game_not_running"), ("threads-suspended", "game_not_running"),
                                ("gone", "game_not_running"), ("unreadable", "game_unreadable"),
                                ("unsupported", "game_unreadable")):
            with self.subTest(verdict=verdict), \
                    mock.patch.object(xm, "game_check", return_value={"verdict": verdict, "detail": "d"}):
                self.assertEqual(self.attempt(), reason)

    def test_lease_keeper_control_starts_once_every_check_passes(self):
        keeper = mock.Mock()
        keeper.poll.return_value = 0
        running = {"verdict": "running", "suspended": [], "stopped": [], "detail": "pid 1234: running."}
        with mock.patch.object(xm, "image_name", return_value=xm.GAME_IMAGE), \
                mock.patch.object(xm, "game_check", return_value=running) as checked, \
                mock.patch.object(xm.subprocess, "Popen", return_value=keeper) as popen:
            xm.start_session(self.cfg, 1234, game=False)
        checked.assert_called_once_with(self.cfg, 1234)
        self.assertEqual(xm.read_state(self.cfg)["baseline"], running)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:4], [sys.executable, "-m", "tools.x64dbg_mcp", "keeper"])
        self.assertIn("1234", argv)
        kwargs = popen.call_args.kwargs
        if os.name == "nt":
            want = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            self.assertEqual(kwargs["creationflags"] & want, want)
            # DETACHED_PROCESS would void CREATE_NO_WINDOW and leave the keeper's own
            # console children opening visible windows.
            self.assertFalse(kwargs["creationflags"] & subprocess.DETACHED_PROCESS)
        else:
            self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)


# --- command's allowlist and the tools' gates -------------------------------

class AllowlistTests(unittest.TestCase):
    def test_allowlist_accepts_each_listed_verb_in_any_case(self):
        for verb in xm.COMMAND_ALLOWLIST:
            for spelled in (verb, verb.upper(), verb.lower()):
                with self.subTest(verb=spelled):
                    self.assertIsNone(xm.command_refusal(f"{spelled} 0x7FF6A0427460"))
        self.assertIsNone(xm.command_refusal('SetHardwareBreakpointName 0x1, "a;b"'))

    def test_allowlist_refuses_everything_that_breaks_stops_steps_or_writes(self):
        for cmd in ("bph 0x1", "SetHardwareBreakpoint 0x1", "bphws 0x1", "bp 0x1", "SetBreakpointLog 0x1, x",
                    "bpm 0x1", "SetHardwareBreakpointCommand 0x1, run", "StopDebug", "detach", "exit",
                    "run", "pause", "sti", "mov [0x1], 0", "savedata", "SetHardwareBreakpointSilent 0x1",
                    # sets $result and prints nothing: it would answer ok with no number
                    "GetHardwareBreakpointHitCount 0x1"):
            with self.subTest(cmd=cmd):
                why = xm.command_refusal(cmd)
                self.assertIsNotNone(why)
                self.assertIn("allowlist", why)

    def test_allowlist_refuses_a_chained_or_multi_line_command(self):
        for cmd in ("bplist; StopDebug", "bphc 0x1;exit", 'bphc "x";detach', "bplist\nexit", "", '"bplist'):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(xm.command_refusal(cmd))

    def test_allowlist_tool_refuses_before_reaching_the_plugin(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            result = xm.Tools(cfg).command("StopDebug")
            self.assertEqual(result["reason"], "not_allowed")
            self.assertIn("allowlist", result["detail"])


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = _cfg(Path(self.tmp.name), port=1)
        self.tools = xm.Tools(self.cfg)
        self.addCleanup(_drop_lease)

    def calls(self):
        return {
            "logpoint": lambda: self.tools.logpoint("Hero_Siege.exe+427460", "hit"),
            "command": lambda: self.tools.command("bplist"),
            "bplist": self.tools.bplist,
            "modules": self.tools.modules,
            "disasm": lambda: self.tools.disasm("0x1000"),
            "detach": self.tools.detach,
        }

    def test_refuses_every_acting_tool_without_a_session(self):
        _hold_lease()
        for name, call in self.calls().items():
            with self.subTest(tool=name):
                self.assertEqual(call()["reason"], "not_attached")

    def test_lease_refuses_every_acting_tool_but_detach_without_a_live_lease(self):
        _fake_live_session(self.cfg)
        _hold_lease(holder=DEAD)
        for name, call in self.calls().items():
            if name == "detach":
                continue
            with self.subTest(tool=name):
                self.assertEqual(call()["reason"], "no_lease")

    def test_refuses_logpoint_arguments_that_would_escape_their_quotes(self):
        _fake_live_session(self.cfg)
        _hold_lease()
        for kwargs in ({"log": 'say "hi"'}, {"log": "two\nlines"}, {"log": "x", "log_condition": "rcx==1;exit"},
                       {"log": "x", "log_condition": '"1"'}, {"log": "x", "name": 'a"b'},
                       {"log": "x", "expect_bytes": "48 8"}, {"log": "x", "expect_bytes": "zz"},
                       {"log": "x", "expect_bytes": "90" * (xm.EXPECT_BYTES_MAX + 1)}):
            with self.subTest(**kwargs):
                result = self.tools.logpoint("0x1000", **kwargs)
                self.assertEqual(result["reason"], "bad_argument", result)

    def test_refuses_logpoint_while_x64dbg_is_not_running(self):
        _fake_live_session(self.cfg)
        _hold_lease()
        state = xm.read_state(self.cfg)
        code = bytes.fromhex("4889542410")
        with mock.patch.object(xm.Tools, "resolve", return_value=0x7FF6A0427460), \
                mock.patch.object(xm.Tools, "_code_at", return_value=code), \
                mock.patch.object(xm, "keeper_request", side_effect=xm.Refused("keeper_gone", "stand-in")) as asked:
            for settled in ("paused", None):
                with self.subTest(x64dbg_state=settled):
                    xm.write_json(self.cfg.state_file, {**state, "x64dbg_state": settled})
                    result = self.tools.logpoint("0x7FF6A0427460", "hit")
                    self.assertEqual(result["reason"], "not_running", result)
            asked.assert_not_called()  # nothing reached the keeper
            # the control: a running x64dbg passes, and the next step asks the keeper
            xm.write_json(self.cfg.state_file, {**state, "x64dbg_state": "running"})
            self.assertEqual(self.tools.logpoint("0x7FF6A0427460", "hit")["reason"], "keeper_gone")
            asked.assert_called_once()

    def test_expect_bytes_parses_every_hex_spelling(self):
        for spelled in ("48 89 54 24 10", "48-89-54-24-10", "4889542410", "0x4889542410"):
            with self.subTest(spelled=spelled):
                self.assertEqual(xm.parse_expect_bytes(spelled), CODE[0])

    def test_refuses_an_unconfirmed_attach_for_every_tool_but_detach(self):
        _fake_live_session(self.cfg)
        state = xm.read_state(self.cfg)
        xm.write_json(self.cfg.state_file, {**state, "state": "attach-unconfirmed"})
        _hold_lease()
        for name, call in self.calls().items():
            with self.subTest(tool=name):
                if name == "detach":
                    # the control: detach passes the gate and reaches the keeper
                    with mock.patch.object(xm, "keeper_request", return_value={"ok": True}) as asked:
                        call()
                    asked.assert_called_once()
                    self.assertEqual(asked.call_args.args[1], "detach")
                else:
                    result = call()
                    self.assertEqual(result["reason"], "attach_unconfirmed", result)
                    self.assertIn("detach", result["detail"])

    def test_status_and_log_answer_without_a_session(self):
        status = self.tools.status()
        self.assertEqual(status["state"], "none")
        self.assertFalse(status["plugin_answers"])
        self.assertEqual(self.tools.log(), {"ok": True, "tool": "log", "total": 0, "first": 1, "lines": [],
                                            "log": str(self.cfg.log_file)})

    def test_log_pages_after_a_line_number(self):
        self.cfg.session.mkdir(parents=True)
        self.cfg.log_file.write_text("".join(f"line {i}\n" for i in range(1, 301)), encoding="utf-8")
        tail = self.tools.log()
        self.assertEqual((tail["total"], tail["first"], len(tail["lines"])), (300, 101, 200))
        page = self.tools.log(after=295)
        self.assertEqual(page["lines"], [f"line {i}" for i in range(296, 301)])


STALE_ID = "0" * 64  # a code id no file hashes to: the module as it was before an edit


class StaleServerTests(unittest.TestCase):
    """A long-lived stdio server keeps the module it imported. Once
    tools/x64dbg_mcp.py changes on disk, its tools refuse with `stale_server`
    (all but `status`, which says why), and the keeper refuses a hold or send
    from a client whose code differs from its own (Live 3 rerun 3)."""

    setUp = GateTests.setUp
    calls = GateTests.calls

    def all_calls(self):
        return {**self.calls(), "log": self.tools.log}

    def test_stale_server_refuses_every_tool_but_status(self):
        _fake_live_session(self.cfg)
        _hold_lease()
        with mock.patch.object(xm, "CODE_ID", STALE_ID):
            for name, call in self.all_calls().items():
                with self.subTest(tool=name):
                    with mock.patch.object(xm, "keeper_request") as asked:
                        result = call()
                    asked.assert_not_called()
                    self.assertEqual(result["reason"], "stale_server", result)
                    self.assertIn("py -3 -m tools.x64dbg_mcp tool", result["detail"])
                    self.assertIn("py -3 -m tools.x64dbg_mcp detach", result["detail"])
            status = self.tools.status()
        self.assertTrue(status["ok"], status)
        self.assertIs(status["code_current"], False, status)

    def test_stale_server_control_current_code_passes_the_gate(self):
        # the same module, unchanged on disk: status reads current and no tool says stale
        self.assertIs(self.tools.status()["code_current"], True)
        self.assertTrue(xm.code_current())
        _hold_lease()
        for name, call in self.calls().items():
            with self.subTest(tool=name):
                self.assertEqual(call()["reason"], "not_attached")
        self.assertTrue(self.tools.log()["ok"])

    def test_stale_server_keeper_request_carries_the_code_id(self):
        _fake_live_session(self.cfg)
        state = xm.read_state(self.cfg)
        with mock.patch.object(xm, "read_state", return_value=state), \
                mock.patch.object(xm, "write_json") as wrote, \
                mock.patch.object(xm, "read_json", return_value={"ok": True}):
            self.assertEqual(xm.keeper_request(self.cfg, "send", timeout=5, lines=["bplist"]), {"ok": True})
        self.assertEqual(wrote.call_args.args[1], {"op": "send", "code_id": xm.CODE_ID, "lines": ["bplist"]})


class StaleKeeperTests(SessionMixin, unittest.TestCase):
    def test_stale_server_keeper_refuses_a_hold_or_send_from_other_code(self):
        cfg, _, _, record, _ = self.start_session(fake={"hot": [A]})
        before = self.stdin_lines(record)
        with mock.patch.object(xm, "CODE_ID", STALE_ID):
            for op, fields in (("hold", {"first_hit": f"bph 0x{A:X}, x, 1",
                                         "lines": [f"SetHardwareBreakpointCondition 0x{A:X}, 0"]}),
                               ("send", {"lines": [f"bph 0x{A:X}, x, 1"]})):
                with self.subTest(op=op):
                    with self.assertRaises(xm.Refused) as cm:
                        xm.keeper_request(cfg, op, timeout=30, **fields)
                    self.assertEqual(cm.exception.reason, "stale_server")
                    self.assertIn("py -3 -m tools.x64dbg_mcp detach", cm.exception.detail)
        time.sleep(0.3)
        self.assertEqual(self.stdin_lines(record), before)  # nothing reached x64dbg
        self.assertEqual(xm.read_state(cfg)["state"], "running")
        # control: the keeper's own code is served, and the hold proves the instrument
        self.prove(cfg)
        # detach is served whatever code asks for it, so a stale client never strands the game
        with mock.patch.object(xm, "CODE_ID", STALE_ID):
            reply = xm.keeper_request(cfg, "detach", timeout=xm.detach_wait(cfg))
        self.assertNotEqual(reply.get("reason"), "stale_server", reply)
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["detach_confirmed"]), ("ended", True), reply)


# --- the loopback client ----------------------------------------------------

class LoopbackClientTests(unittest.TestCase):
    def plugin(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = StandInPlugin(Path(tmp.name) / "rec", Path(tmp.name) / "bps", debugging=True, **kw)
        self.addCleanup(p.close)
        return p

    def test_loopback_client_initializes_and_carries_the_session_id(self):
        p = self.plugin()
        c = xm.PluginClient(f"http://127.0.0.1:{p.port}/")
        text, is_error = c.call_checked(xm.PLUGIN_EXECUTE, {"command": "bplist"})
        self.assertFalse(is_error)
        self.assertIn("Executing DbgCmdExec: bplist", text)
        self.assertEqual(p.sessions[0], None)  # initialize
        self.assertTrue(all(s == "standin-session" for s in p.sessions[1:]), p.sessions)

    def test_loopback_client_reads_sse_framed_replies(self):
        p = self.plugin(sse=True)
        c = xm.PluginClient(f"http://127.0.0.1:{p.port}/")
        self.assertIn("Hero_Siege.exe", c.call(xm.PLUGIN_MODULES)[0])
        self.assertEqual(xm.module_bases(c.call(xm.PLUGIN_MODULES)[0])["hero_siege.exe"], GAME_BASE)

    def test_loopback_client_refuses_any_other_host(self):
        for url in ("http://localhost:50300/", "http://10.0.0.5:50300/", "https://127.0.0.1:50300/",
                    "http://0.0.0.0:50300/", "http://127.0.0.1/"):
            with self.subTest(url=url), self.assertRaises(xm.PluginError):
                xm.PluginClient(url)

    def test_refuses_to_forward_a_tool_missing_from_tools_list(self):
        p = self.plugin()
        c = xm.PluginClient(f"http://127.0.0.1:{p.port}/")
        with self.assertRaises(xm.PluginMismatch) as cm:
            c.call_checked("NoSuchTool")
        self.assertIn("NoSuchTool", str(cm.exception))
        self.assertNotIn("NoSuchTool", p.names())

    def test_refuses_to_forward_an_argument_the_plugin_does_not_take(self):
        p = self.plugin(execute_arg="cmd")
        c = xm.PluginClient(f"http://127.0.0.1:{p.port}/")
        with self.assertRaises(xm.PluginMismatch) as cm:
            c.call_checked(xm.PLUGIN_EXECUTE, {"command": "bplist"})
        self.assertIn("'command'", str(cm.exception))
        self.assertEqual(p.names(), [])

    def test_loopback_debug_state_never_reads_silence_as_detached(self):
        p = self.plugin()
        c = xm.PluginClient(f"http://127.0.0.1:{p.port}/", timeout=1)
        self.assertEqual(c.debug_state(), "debugging")
        p.forced = False
        self.assertEqual(c.debug_state(), "none")
        p.close()
        self.assertEqual(xm.PluginClient(f"http://127.0.0.1:{p.port}/", timeout=1).debug_state(), "unknown")


# --- the module table -------------------------------------------------------

class ModuleTableTests(unittest.TestCase):
    """The pinned plugin prints the module table's base, end and size as
    decimal digits behind `0x`. The stand-in printed padded hex for nine
    rounds, which is how a wrong live resolve passed every test."""

    def tools(self, table):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = StandInPlugin(Path(tmp.name) / "rec", Path(tmp.name) / "bps", debugging=True, module_table=table)
        self.addCleanup(p.close)
        return xm.Tools(_cfg(Path(tmp.name), port=p.port))

    def test_live_decimal_row_resolves_to_the_real_base(self):
        self.assertEqual(xm.module_bases(LIVE_ROW), {"hero_siege.exe": LIVE_BASE})
        tools = self.tools(_module_table([]).replace("Found 0", "Found 1") + LIVE_ROW + "\n")
        self.assertEqual(tools.resolve("Hero_Siege.exe+427460"), 0x7FF613D47460)
        self.assertEqual(tools.resolve("hero_siege.exe+0"), LIVE_BASE)
        with mock.patch.object(tools, "_gate", return_value=None):
            self.assertEqual(tools.modules()["bases"], {"hero_siege.exe": "0x7FF613920000"})

    def test_live_decimal_row_layout_is_what_the_stand_in_serves(self):
        self.assertEqual(xm.module_bases(MODULE_TABLE), {"hero_siege.exe": GAME_BASE, "kernel32.dll": 0x7FFB10000000})
        self.assertIn(f"0x{GAME_BASE} 0x{GAME_BASE + 0x9000000} 0x{0x9000000}", MODULE_TABLE)
        tools = self.tools(MODULE_TABLE)
        self.assertEqual(tools.resolve("Hero_Siege.exe+427460"), GAME_BASE + 0x427460)
        with mock.patch.object(tools, "_gate", return_value=None):
            self.assertEqual(tools.modules()["bases"], {"hero_siege.exe": "0x7FF6A0000000",
                                                        "kernel32.dll": "0x7FFB10000000"})

    def test_hex_formatted_row_gives_no_base_and_resolve_refuses(self):
        self.assertEqual(xm.module_bases(HEX_MODULE_TABLE), {})
        # a hex rendering made only of digits passes end == base + size under a
        # decimal reading; its leading zeros are what refuse it
        self.assertEqual(xm.module_bases("a.dll  C:/a.dll  0x0000000140000000 0x0000000150000000 0x10000000"), {})
        tools = self.tools(HEX_MODULE_TABLE)
        with self.assertRaises(xm.Refused) as cm:
            tools.resolve("Hero_Siege.exe+427460")
        self.assertEqual(cm.exception.reason, "module_row_unreadable")
        self.assertIn("0x00007FF6A0000000", cm.exception.detail)
        # control: a module with no row at all is still no_such_module
        with self.assertRaises(xm.Refused) as cm:
            tools.resolve("absent.dll+10")
        self.assertEqual(cm.exception.reason, "no_such_module")

    def test_hex_formatted_row_refused_by_logpoint_before_anything_is_set(self):
        tools = self.tools(HEX_MODULE_TABLE)
        _fake_live_session(tools.cfg)
        _hold_lease()
        self.addCleanup(_drop_lease)
        result = tools.logpoint("Hero_Siege.exe+427460", "hit")
        self.assertEqual(result["reason"], "module_row_unreadable", result)

    def test_hex_formatted_row_end_must_equal_base_plus_size(self):
        self.assertEqual(xm.module_bases("a.dll  C:/a.dll  0x65536 0x73728 0x4096"), {})
        self.assertEqual(xm.module_bases("a.dll  C:/a.dll  0x65536 0x69632 0x4096"), {"a.dll": 0x10000})  # control
        self.assertEqual(xm.module_bases("a.dll  C:/a.dll  0x4194304 0x4198400 0x4096"), {"a.dll": 0x400000})

    def test_hex_formatted_row_unpadded_and_all_digits_gives_no_base(self):
        # Unpadded hex using only the digits 0-9, with no carry from base to
        # end: 0x180000000 + 0x1000 reads as 180000000 + 1000 = 180001000, so
        # the end check passes under a decimal reading. Windows maps an image
        # on a 64 KiB boundary, and 180000000 (0xABA9500) is not on one.
        row = "a.dll  C:/a.dll  0x180000000 0x180001000 0x1000"
        self.assertEqual(xm.module_bases(row), {})
        tools = self.tools(_module_table([]).replace("Found 0", "Found 1") + row + "\n")
        with self.assertRaises(xm.Refused) as cm:
            tools.resolve("a.dll+10")
        self.assertEqual(cm.exception.reason, "module_row_unreadable")
        # control: the same image in the pinned format (decimal) is read
        self.assertEqual(xm.module_bases(f"a.dll  C:/a.dll  0x{0x180000000} 0x{0x180001000} 0x{0x1000}"),
                         {"a.dll": 0x180000000})

    def test_hex_formatted_row_listed_as_unreadable_by_modules(self):
        tools = self.tools(HEX_MODULE_TABLE)
        with mock.patch.object(tools, "_gate", return_value=None):
            result = tools.modules()
        self.assertEqual(result["bases"], {})
        self.assertEqual(len(result["unreadable"]), 2, result)
        self.assertTrue(result["unreadable"][0].startswith("Hero_Siege.exe"), result["unreadable"])
        self.assertIn("module_row_unreadable", result["note"])
        # control: the pinned format leaves nothing unreadable
        tools = self.tools(MODULE_TABLE)
        with mock.patch.object(tools, "_gate", return_value=None):
            result = tools.modules()
        self.assertEqual(result["unreadable"], [], result)
        self.assertEqual(len(result["bases"]), 2)


# --- the keeper, teardown and release (real processes) ---------------------

PLUGIN_STATE_CALLS = (xm.PLUGIN_RUN, xm.PLUGIN_PAUSE, xm.PLUGIN_EXECUTE)


class KeeperTests(SessionMixin, unittest.TestCase):
    def test_keeper_attach_no_break_is_running_and_ready_with_the_instrument_unproven(self):
        # Headless x64dbg takes no attach break (Replan 3 probe, Live 3): the
        # stand-in prints `[STATE] running` after attach and never `paused`.
        started = time.monotonic()
        cfg, plugin, state, record, target = self.start_session()
        elapsed = time.monotonic() - started
        self.assertEqual((state["state"], state["ready"]), ("running", True), state)
        self.assertIsNone(state["error"])
        log = self.log_lines(cfg)
        self.assertIn("Attached to process!", log)
        self.assertNotIn("[STATE] paused", log)
        # the attach and the defensive clear, nothing else: no `run`, since nothing paused
        self.assertEqual(_commands(self.stdin_lines(record)), [f"attach 0x{target.pid:X}", "bphc", "bplist"])
        self.assertEqual(state["ready_check"]["verdict"], "running", state)
        inst = state["instrument"]
        self.assertEqual(inst["before_attach"]["verdict"], "running", inst)
        self.assertEqual((inst["control_hold"], inst["after_resume"], inst["proven"]), (None, None, False), inst)
        self.assertNotIn("attach_break", inst)
        names = plugin.names()
        self.assertIn(xm.PLUGIN_MODULES, names)
        self.assertFalse([n for n in names if n in PLUGIN_STATE_CALLS], names)
        summary = xm.session_summary(cfg)
        self.assertTrue(summary["keeper_alive"] and summary["headless_alive"], summary)
        self.assertEqual((summary["x64dbg_state"], summary["breaks_resumed"], summary["break_storm"]),
                         ("running", 0, False), summary)
        self.assertIsNone(summary["last_break"])
        self.assertFalse(summary["instrument"]["proven"])
        self.assertNotIn("game_released", summary)  # only once set, at detach
        self.assertNotEqual(state["keeper"]["pid"], os.getpid())
        self.assertLess(elapsed, cfg.ready_timeout, "attach waited out its ready timeout")

    def test_keeper_attach_no_break_control_no_run_before_the_first_logpoint(self):
        # The keeper never blocks on a pause and never resumes one it did not
        # see: with nothing paused, no `run` goes out, and status says the
        # instrument waits for the control hold.
        cfg, _, state, record, _ = self.start_session()
        self.assertEqual(state["state"], "running", state)
        time.sleep(1.5)
        self.assertNotIn("run", self.stdin_lines(record))
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], 0)
        status = xm.Tools(cfg).status()
        self.assertFalse(status["instrument"]["proven"], status)
        self.assertIn("control hold", status["instrument"]["note"])

    def test_keeper_without_readiness_is_attach_unconfirmed_not_running(self):
        cfg, plugin, state, record, _ = self.start_session(cfg_over={"ready_timeout": 1}, never_ready=True)
        self.assertEqual(state["state"], "attach-unconfirmed", state)
        self.assertFalse(state["ready"])
        self.assertIn("did not answer", state["error"])
        self.assertIn("may be paused", state["error"])
        self.assertNotIn("attach break", state["error"])
        later = self.wait_for(cfg, lambda s: s.get("x64dbg_state") == "running")
        self.assertEqual(later["breaks_resumed"], 0, later)
        self.assertNotIn("run", self.stdin_lines(record))  # nothing paused, so nothing resumed
        self.assertFalse([n for n in plugin.names() if n in PLUGIN_STATE_CALLS])
        refused = xm.Tools(cfg).logpoint("0x7FF6A0427460", "hit")
        self.assertEqual(refused["reason"], "attach_unconfirmed", refused)
        with mock.patch.object(xm, "start_session", return_value=state), mock.patch("sys.stdout"):
            self.assertEqual(xm.attach(cfg, 1, False), 1)

    def test_keeper_promotes_a_late_attach_once_everything_is_seen(self):
        cfg, plugin, state, record, _ = self.start_session(cfg_over={"ready_timeout": 1}, never_ready=True)
        self.assertEqual(state["state"], "attach-unconfirmed", state)
        time.sleep(1.5)
        self.assertEqual(xm.read_state(cfg)["state"], "attach-unconfirmed")  # control: not without the plugin
        plugin.never_ready = False  # the plugin answers late
        late = self.wait_for(cfg, lambda s: s.get("state") == "running")
        self.assertEqual((late["state"], late["ready"]), ("running", True), late)
        self.assertIsNone(late["error"])
        self.assertTrue(late["late_ready_utc"])
        self.assertEqual(late["ready_check"]["verdict"], "running", late)
        self.assertEqual(_commands(self.stdin_lines(record)).count("bphc"), 1)  # the defensive clear, once
        self.assertFalse([n for n in plugin.names() if n in PLUGIN_STATE_CALLS])

    def test_keeper_unconfirmed_resume_is_attach_unconfirmed_not_running(self):
        # The plugin answers, but x64dbg breaks again after every run: it
        # never settles at running, so the session is not ready, other tools
        # refuse, and detach is served.
        cfg, plugin, state, record, _ = self.start_session(cfg_over={"ready_timeout": 3, "hold_timeout": 1.5},
                                                           fake={"never_running": True})
        self.assertEqual(state["state"], "attach-unconfirmed", state)
        self.assertFalse(state["ready"])
        self.assertIn("never settled at running", state["error"])
        self.assertIn("detach", state["error"])
        self.assertNotIn("attach break", state["error"])
        self.assertGreater(self.stdin_lines(record).count("run"), 1)
        time.sleep(1)  # the keeper keeps resuming; still never settled, so never `running`
        later = xm.read_state(cfg)
        self.assertEqual((later["state"], later["ready"]), ("attach-unconfirmed", False), later)
        self.assertGreater(later["breaks_resumed"], 0, later)
        refused = xm.Tools(cfg).bplist()
        self.assertEqual(refused["reason"], "attach_unconfirmed", refused)
        with mock.patch.object(xm, "start_session", return_value=state), mock.patch("sys.stdout"):
            self.assertEqual(xm.attach(cfg, 1, False), 1)
        detached = xm.Tools(cfg).detach()
        self.assertEqual((detached["state"], detached["detach_confirmed"]), ("ended", True), detached)
        self.assertTrue(detached["paused_at_detach"], detached)
        # no control hold ever proved the instrument, so its `running` is no release
        self.assertIsNone(detached["game_released"], detached)
        self.assertFalse(detached["ok"], detached)
        self.assertEqual(self.stdin_lines(record)[-2:], ["detach", "exit"])
        self.assertFalse([n for n in plugin.names() if n in PLUGIN_STATE_CALLS])

    def test_keeper_unconfirmed_resume_control_a_settling_x64dbg_is_running(self):
        cfg, _, state, record, _ = self.start_session(cfg_over={"ready_timeout": 3})
        self.assertEqual((state["state"], state["ready"]), ("running", True), state)
        self.assertEqual(self.stdin_lines(record).count("run"), 0)

    def test_keeper_hold_direct_batch_reports_x64dbgs_lines_between_markers(self):
        # A batch with no `bph` in it, and nothing armed. A `bph` with nothing
        # armed goes through the first-hit hold instead (BreakingBphInLinesTests).
        cfg, plugin, _, record, _ = self.start_session()
        reply = xm.keeper_request(cfg, "hold", timeout=60, lines=[f'SetHardwareBreakpointName 0x{A:X}, "x"', "bphc"])
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["lines"], [f'No such breakpoint "0x{A:X}"', "No hardware breakpoints to delete!"])
        self.assertEqual(reply["after"], [])
        self.assertIsNone(reply["held"])
        self.assertNotIn("window_break", reply)  # a first hit is now the expected hold, not an anomaly
        self.assertNotIn("held_note", reply)  # nothing was armed, so nothing to hold
        self.assertEqual(reply["x64dbg_state"], "running")
        self.assertEqual(reply["game"]["verdict"], "running")
        sent = self.stdin_lines(record)
        begin = next(i for i, ln in enumerate(sent) if ln.startswith('log "x64dbg_mcp ') and ln.endswith(' begin"'))
        self.assertEqual(sent[begin + 1:begin + 3], [f'SetHardwareBreakpointName 0x{A:X}, "x"', "bphc"])
        self.assertTrue(sent[begin + 3].endswith(' mid"'), sent)
        self.assertEqual(sent[begin + 4], "bplist")
        self.assertTrue(sent[begin + 5].endswith(' end"'), sent)
        self.assertNotIn("run", sent[begin:])
        self.assertFalse([n for n in plugin.names() if n in PLUGIN_STATE_CALLS])

    def test_keeper_hold_keeps_a_logging_breakpoint_logging(self):
        # A change while a logpoint logs is made with the game held at one of
        # its hits; the same lines sent plainly, under `race`, silence it.
        cfg, _, _, record, _ = self.start_session(fake={"race": True})
        a, b, c = 0x7FF6A0427460, 0x7FF6A0428000, 0x7FF6A0429000
        armed = xm.keeper_request(cfg, "hold", timeout=60, lines=[
            f"bph 0x{a:X}, x, 1", f"SetHardwareBreakpointCondition 0x{a:X}, 0", f'SetHardwareBreakpointLog 0x{a:X}, "hot"'])
        self.assertTrue(armed["ok"], armed)
        self.set_modes(hot=[a])
        self.assertTrue(self._hits_grow(cfg), "the hot logpoint never logged")
        before = xm.read_state(cfg)["breaks_resumed"]
        reply = xm.keeper_request(cfg, "hold", timeout=60, lines=[f"bph 0x{b:X}, x, 1",
                                                                   f"SetHardwareBreakpointCondition 0x{b:X}, 0"])
        self.assertTrue(reply["ok"], reply)
        self.assertIn(f"({a:016X})", reply["held"] or "", reply)
        self.assertIn(f"Hardware breakpoint at {b:016X} set!", reply["lines"])
        self.assertEqual(reply["x64dbg_state"], "running")
        sent = self.stdin_lines(record)
        held_at = sent.index(f"SetHardwareBreakpointCondition 0x{a:X}, 1")
        tail = sent[held_at:]
        self.assertEqual(tail[2:4], [f"bph 0x{b:X}, x, 1", f"SetHardwareBreakpointCondition 0x{b:X}, 0"])
        self.assertLess(tail.index(f"SetHardwareBreakpointCondition 0x{a:X}, 0"), tail.index("run"))
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], before)  # its own hold is no stray pause
        self.assertTrue(self._hits_grow(cfg), "the held change silenced the hot logpoint")
        # control: the same kind of change, sent plainly while it logs, races it
        xm.keeper_request(cfg, "send", timeout=15, lines=[f"bph 0x{c:X}, x, 1"])
        time.sleep(0.3)
        self.assertFalse(self._hits_grow(cfg), "the stand-in cannot represent the lost DR7 update")

    def _hits_grow(self, cfg, wait=1.0) -> bool:
        count = lambda: sum(1 for ln in self.log_lines(cfg) if ln.startswith("hot #"))  # noqa: E731
        first = count()
        time.sleep(wait)
        return count() > first

    def test_keeper_refuses_a_second_attach_while_live(self):
        cfg, _, _, _, target = self.start_session()
        with mock.patch.object(xm, "image_name", return_value=xm.GAME_IMAGE):
            with self.assertRaises(xm.Refused) as cm:
                xm.start_session(cfg, target.pid, game=False)
        self.assertEqual(cm.exception.reason, "session_live")

    def test_keeper_bplist_and_command_go_through_the_session(self):
        cfg, plugin, _, record, _ = self.start_session()
        tools = xm.Tools(cfg)
        reply = tools.command("bphc 0x7FF6A0427460")
        self.assertTrue(reply["ok"], reply)
        # on headless's stdin, never through the plugin's log-redirecting ExecuteDbgCommand
        self.assertIn("bphc 0x7FF6A0427460", self.stdin_lines(record))
        self.assertNotIn(xm.PLUGIN_EXECUTE, plugin.names())
        listed = tools.bplist()
        self.assertTrue(listed["ok"], listed)
        self.assertIn("bplist", self.stdin_lines(record))
        self.assertTrue(tools.modules()["bases"]["hero_siege.exe"].startswith("0x7FF6A"))
        self.assertTrue(tools.disasm("Hero_Siege.exe+427460")["reply"].startswith("stand-in listing for 0x7FF6A0427460"))


def _commands(lines: list[str]) -> list[str]:
    """Stdin lines without the keeper's batch markers."""
    return [ln for ln in lines if not ln.startswith('log "x64dbg_mcp ')]


class StaleBreakpointTests(SessionMixin, unittest.TestCase):
    """x64dbg restores a module's saved breakpoints from its database on
    attach (Replan 3 probe), so the keeper clears hardware breakpoints once,
    after x64dbg settles at running and before the session is used."""

    def test_stale_breakpoint_restored_from_the_database_is_cleared_at_attach(self):
        cfg, _, state, record, target = self.start_session(fake={"stale_db": A})
        self.assertEqual((state["state"], state["ready"]), ("running", True), state)
        log = self.log_lines(cfg)
        restored = log.index(f"Set hardware breakpoint on {A:016X}!")
        deleted = log.index("All hardware breakpoints deleted!")
        self.assertIn("[STATE] running", log[restored:deleted])  # cleared after x64dbg settled at running
        self.assertEqual(_commands(self.stdin_lines(record)), [f"attach 0x{target.pid:X}", "bphc", "bplist"])
        cleared = state["attach_bphc"]
        self.assertEqual((cleared["lines"], cleared["bplist"], cleared["end_seen"]),
                         (["All hardware breakpoints deleted!"], [], True), cleared)
        self.assertIsNone(xm.bplist_entry(xm.Tools(cfg).bplist()["lines"], A))
        self.assertEqual(state["breaks_resumed"], 0)  # the clear is no hold of its own

    def test_stale_breakpoint_control_a_clean_database_leaves_nothing_to_delete(self):
        cfg, _, state, _, _ = self.start_session()
        self.assertEqual(state["attach_bphc"]["lines"], ["No hardware breakpoints to delete!"], state)
        self.assertEqual(state["attach_bphc"]["bplist"], [])
        self.assertNotIn("Set hardware breakpoint on", "\n".join(self.log_lines(cfg)))


class TeardownTests(SessionMixin, unittest.TestCase):
    def test_teardown_clears_detaches_confirms_then_exits(self):
        cfg, plugin, _, record, _ = self.start_session()
        self.prove(cfg)
        code, reply = self.detach_cli(cfg)
        self.assertEqual(code, 0, reply)
        lines = _commands(self.stdin_lines(record))
        # held at a hit of the logging control, cleared there, resumed, then detached
        self.assertEqual(lines[-7:], [f"SetHardwareBreakpointCondition 0x{A:X}, 1", "bphc",
                                      f"SetHardwareBreakpointCondition 0x{A:X}, 0", "bplist", "run", "detach",
                                      "exit"])
        self.assertIn("All hardware breakpoints deleted!", reply["cleared"]["lines"])
        self.assertIn(f"({A:016X})", reply["cleared"]["held"] or "", reply)
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["detach_confirmed"], state["game_released"]), ("ended", True, True))
        self.assertFalse(state["paused_at_detach"])
        self.assertFalse([n for n in plugin.names() if n in PLUGIN_STATE_CALLS])
        deadline = time.monotonic() + 10
        while xm.alive(state["headless"]) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(xm.alive(state["headless"]))

    def test_teardown_unconfirmed_leaves_headless_running_and_fails(self):
        cfg, _, _, record, _ = self.start_session(cfg_over={"detach_timeout": 1}, never_detach=True)
        code, _ = self.detach_cli(cfg)
        self.assertEqual(code, 1)
        lines = _commands(self.stdin_lines(record))
        self.assertEqual(lines[-3:], ["bphc", "bplist", "detach"])
        self.assertNotIn("exit", lines)
        state = xm.read_state(cfg)
        self.assertEqual(state["state"], "detach-unconfirmed")
        self.assertIn("not killed", state["error"])
        self.assertTrue(xm.alive(state["headless"]))
        self.assertTrue(xm.alive(state["keeper"]))

    def test_teardown_tool_ends_an_unconfirmed_attach(self):
        cfg, _, state, record, _ = self.start_session(cfg_over={"ready_timeout": 1}, never_ready=True)
        self.assertEqual(state["state"], "attach-unconfirmed", state)
        result = xm.Tools(cfg).detach()
        self.assertEqual((result["state"], result["detach_confirmed"]), ("ended", True), result)
        self.assertIsNone(result["game_released"], result)  # never proven, so no release is claimed
        self.assertEqual(_commands(self.stdin_lines(record))[-2:], ["detach", "exit"])

    def test_teardown_tool_needs_no_lease_to_give_the_game_back(self):
        cfg, _, _, _, _ = self.start_session()
        self.prove(cfg)
        _hold_lease(state="released")
        result = xm.Tools(cfg).detach()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "ended")

    def test_teardown_resumes_first_when_x64dbg_is_paused(self):
        # x64dbg breaks as the teardown clears the breakpoints: the keeper
        # sends `run` and sees x64dbg settle at running before `detach`. Set
        # after attach, so the attach's own clear does not take the break.
        cfg, _, _, record, _ = self.start_session()
        self.set_modes(break_after="bphc")
        time.sleep(0.2)
        _, reply = self.detach_cli(cfg)
        self.assertEqual((reply["state"], reply["detach_confirmed"]), ("ended", True), reply)
        lines = _commands(self.stdin_lines(record))
        bphc = len(lines) - 1 - lines[::-1].index("bphc")
        self.assertEqual(lines[bphc:], ["bphc", "bplist", "run", "detach", "exit"])
        log = self.log_lines(cfg)
        paused = max(i for i, ln in enumerate(log) if ln == "[STATE] paused")
        self.assertIn("[STATE] running", log[paused:log.index("Detached!")])
        self.assertFalse(reply["paused_at_detach"], reply)
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], 1)

    def test_teardown_resumes_first_control_no_pause_no_run(self):
        cfg, _, _, record, _ = self.start_session()
        _, reply = self.detach_cli(cfg)
        self.assertEqual(reply["state"], "ended", reply)
        self.assertNotIn("run", _commands(self.stdin_lines(record)))
        self.assertFalse(reply["paused_at_detach"], reply)


class WatchdogTests(SessionMixin, unittest.TestCase):
    """The keeper resumes every pause x64dbg takes on its own, and reports it."""

    def test_late_break_is_resumed_once_and_reported(self):
        cfg, _, state, record, _ = self.start_session(fake={"late_break": 2.0})
        self.assertEqual(state["state"], "running", state)
        later = self.wait_for(cfg, lambda s: s.get("breaks_resumed") == 1 and s.get("x64dbg_state") == "running")
        self.assertEqual(later["breaks_resumed"], 1, later)
        self.assertEqual(later["last_break"]["line"], "paused!", later)
        self.assertTrue(later["last_break"]["utc"])
        self.assertFalse(later["break_storm"])
        time.sleep(1)
        self.assertEqual(self.stdin_lines(record).count("run"), 1)  # the late one's: nothing else paused
        self.assertEqual(xm.Tools(cfg).status()["breaks_resumed"], 1)

    def test_late_break_control_no_break_no_extra_run(self):
        cfg, _, state, record, _ = self.start_session()
        self.assertEqual(state["state"], "running", state)
        time.sleep(3)
        self.assertEqual(self.stdin_lines(record).count("run"), 0)
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], 0)

    def test_tls_storm_attach_is_running_only_once_settled(self):
        # x64dbg's TLS-callback breakpoints pause the game right after attach;
        # the keeper resumes each, and no attach break is waited for.
        cfg, _, state, record, _ = self.start_session(fake={"tls_breaks": 3})
        self.assertEqual((state["state"], state["ready"]), ("running", True), state)
        self.assertEqual(state["breaks_resumed"], 3, state)
        self.assertEqual(state["x64dbg_state"], "running")
        self.assertIn("TLS Callback", state["last_break"]["line"])
        self.assertFalse(state["break_storm"])
        self.assertEqual(self.stdin_lines(record).count("run"), 3)  # one per TLS break
        log = self.log_lines(cfg)
        self.assertEqual(sum(1 for ln in log if ln.startswith('INT3 breakpoint "TLS Callback')), 3)
        first_tls = next(i for i, ln in enumerate(log) if ln.startswith('INT3 breakpoint "TLS Callback'))
        self.assertNotIn("[STATE] paused", log[:first_tls])  # no pause before x64dbg's own TLS breaks
        # the defensive clear went out only once x64dbg had settled at running
        sent = _commands(self.stdin_lines(record))
        self.assertLess(len(sent) - 1 - sent[::-1].index("run"), sent.index("bphc"), sent)

    def test_break_storm_sets_the_flag_refuses_logpoint_and_still_detaches(self):
        cfg, _, state, _, _ = self.start_session(cfg_over={"hold_timeout": 3})
        self.assertEqual(state["state"], "running", state)
        self.set_modes(breaks=12)
        stormed = self.wait_for(cfg, lambda s: s.get("break_storm"), timeout=30)
        self.assertTrue(stormed["break_storm"], stormed)
        self.assertGreaterEqual(stormed["breaks_resumed"], 10)
        refused = xm.Tools(cfg).logpoint("0x7FF6A0427460", "hit")
        self.assertEqual(refused["reason"], "break_storm", refused)
        self.assertTrue(xm.Tools(cfg).status()["break_storm"])
        self.wait_for(cfg, lambda s: s.get("breaks_resumed") >= 12 and s.get("x64dbg_state") == "running")
        detached = xm.Tools(cfg).detach()
        self.assertEqual((detached["state"], detached["detach_confirmed"]), ("ended", True), detached)
        self.assertTrue(detached["break_storm"])  # stays set until the session ends

    def test_break_storm_control_a_few_breaks_raise_no_flag(self):
        cfg, _, state, _, _ = self.start_session()
        self.set_modes(breaks=3)
        later = self.wait_for(cfg, lambda s: s.get("breaks_resumed") == 3 and s.get("x64dbg_state") == "running")
        self.assertEqual(later["breaks_resumed"], 3, later)
        self.assertFalse(later["break_storm"])


class InstrumentTests(SessionMixin, unittest.TestCase):
    """The outside check must read the game frozen at the control's first-hit
    hold, the first time the keeper holds the game at a hardware-breakpoint
    hit: that is what makes its later `running` verdicts mean anything."""

    def test_instrument_control_frozen_at_the_first_hit_hold_is_proven(self):
        cfg, _, state, record, _ = self.start_session()
        self.assertFalse(state["instrument"]["proven"], state["instrument"])  # attach holds nothing
        self.set_modes(hot=[A])
        reply = self.first_hit(cfg, A)
        self.assertTrue(reply["ok"], reply)
        self.assertIn(f"({A:016X})", reply["held"] or "", reply)
        self.assertEqual(reply["hold_game"]["verdict"], "frozen", reply)
        self.assertEqual(reply["game"]["verdict"], "running", reply)
        self.assertEqual(reply["x64dbg_state"], "running", reply)
        self.assertIn(f"Hardware breakpoint at {A:016X} set!", reply["lines"])
        self.assertIn(f"1:HW:{A:016X}", reply["after"])
        inst = xm.read_state(cfg)["instrument"]
        self.assertEqual([inst[k]["verdict"] for k in ("before_attach", "control_hold", "after_resume")],
                         ["running", "frozen", "running"], inst)
        self.assertEqual(xm.check_tids(inst["control_hold"]), [9001, 9002], inst)
        self.assertEqual(inst["control_hold"]["unreadable_counts"], [], inst)
        self.assertTrue(inst["proven"], inst)
        self.assertNotIn("note", inst)
        # bph (breaking), then held at its first hit the rest, then run
        sent = _commands(self.stdin_lines(record))
        bph = sent.index(f"bph 0x{A:X}, x, 1")
        self.assertEqual(sent[bph:], [f"bph 0x{A:X}, x, 1", f"SetHardwareBreakpointCondition 0x{A:X}, 0",
                                      f'SetHardwareBreakpointLog 0x{A:X}, "hot"', "bplist", "run"])
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], 0)  # its own hold, not a stray pause
        before = _hits(cfg, "hot")
        time.sleep(1)
        self.assertGreater(_hits(cfg, "hot"), before, "the control never logged after its hold")
        status = xm.Tools(cfg).status()
        self.assertTrue(status["instrument"]["proven"])
        self.assertEqual(status["game"]["verdict"], "running")

    def test_instrument_control_a_cold_first_hit_holds_nothing_and_proves_nothing(self):
        # Control: an address with no hit within the window is armed
        # never-break on the running game, and proves nothing.
        cfg, _, _, record, _ = self.start_session(cfg_over={"hold_timeout": 1.5})
        reply = self.first_hit(cfg, A)
        self.assertTrue(reply["ok"], reply)
        self.assertIsNone(reply["held"], reply)
        self.assertIn("no hit", reply["held_note"])
        self.assertIsNone(reply.get("hold_game"), reply)
        self.assertIn(f"1:HW:{A:016X}", reply["after"])
        inst = xm.read_state(cfg)["instrument"]
        self.assertEqual((inst["control_hold"], inst["proven"]), (None, False), inst)
        sent = _commands(self.stdin_lines(record))
        self.assertEqual(sent[sent.index(f"bph 0x{A:X}, x, 1"):],
                         [f"bph 0x{A:X}, x, 1", f"SetHardwareBreakpointCondition 0x{A:X}, 0",
                          f'SetHardwareBreakpointLog 0x{A:X}, "hot"', "bplist"])

    def assert_unproven_session(self, cfg, says):
        """Not proven: the session still runs (attach does not depend on the
        instrument), status names the gap, and a clean `running` after the
        detach is not reported as a release."""
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["ready"]), ("running", True), state)
        inst = state["instrument"]
        self.assertFalse(inst["proven"], inst)
        status = xm.Tools(cfg).status()
        self.assertFalse(status["instrument"]["proven"])
        self.assertIn(says, status["instrument"]["note"])
        code, reply = self.detach_cli(cfg)
        self.assertEqual(code, 1, reply)
        self.assertFalse(reply["ok"], reply)
        self.assertIsNone(reply["game_released"], reply)
        self.assertEqual(reply["game"]["verdict"], "running", reply)
        self.assertIn("not proven", reply["note"])
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["detach_confirmed"], state["game_released"]),
                         ("ended", True, None), state)

    def test_instrument_control_a_blind_probe_is_not_proven_and_status_says_so(self):
        cfg, _, _, _, _ = self.start_session(fake={"blind_probe": True, "hot": [A]})
        reply = self.first_hit(cfg, A)
        self.assertTrue(reply["ok"], reply)
        self.assertIsNotNone(reply["held"], reply)  # x64dbg held the game; the probe did not see it
        self.assertEqual(xm.read_state(cfg)["instrument"]["control_hold"]["verdict"], "running")
        self.assert_unproven_session(cfg, "not frozen")

    def test_instrument_control_frozen_with_no_thread_named_is_not_proven(self):
        # Negative control: `frozen` alone, from a check that named no held thread.
        cfg, _, _, _, _ = self.start_session(fake={"empty_lists": True, "hot": [A]})
        self.assertTrue(self.first_hit(cfg, A)["ok"])
        brk = xm.read_state(cfg)["instrument"]["control_hold"]
        self.assertEqual((brk["verdict"], brk["suspended"], brk["stopped"]), ("frozen", [], []), brk)
        self.assert_unproven_session(cfg, "0 suspended and 0 stopped")


class InstrumentGapsTests(unittest.TestCase):
    """`instrument_gaps` on hand-built checks: what the control hold's lists
    must cover, and each way they can fall short."""

    @staticmethod
    def chk(verdict, held=(), tids=(1, 2, 3), unread=(), stopped=None):
        return {"verdict": verdict, "suspended": [{"tid": t, "suspend_count": 2} for t in held],
                "stopped": list(held if stopped is None else stopped), "unreadable_counts": list(unread),
                "tids": list(tids)}

    def inst(self, brk, before=None):
        return {"before_attach": before or self.chk("running"), "control_hold": brk,
                "after_resume": self.chk("running")}

    def test_instrument_gaps_control_every_thread_held_and_a_new_break_in_thread_is_proven(self):
        self.assertEqual(xm.instrument_gaps(self.inst(self.chk("frozen", (1, 2, 3), tids=(1, 2, 3, 99)))), [])

    def test_instrument_gaps_a_baseline_thread_need_not_be_listed(self):
        before = self.chk("running", held=(3,))
        self.assertEqual(xm.instrument_gaps(self.inst(self.chk("frozen", (1, 2)), before)), [])

    def test_instrument_gaps_name_each_shortfall(self):
        cases = [
            (self.chk("frozen", (1, 2)), "1 of the 3 thread(s)"),
            (self.chk("frozen", (1, 2, 3), stopped=(1, 2)), "tid 3"),
            (self.chk("frozen", (1, 2, 3), unread=(2,)), "could not read the suspend count"),
            (self.chk("frozen"), "0 suspended and 0 stopped"),
            (self.chk("frozen", (1, 2, 3), tids=(7, 8)), "no thread seen before attach"),
            ({**self.chk("frozen", (1, 2, 3)), "tids": None}, "list no tids"),
            ({k: v for k, v in self.chk("frozen", (1, 2, 3)).items() if k != "unreadable_counts"},
             "carried no unreadable_counts"),
            (None, "no check at a control hold"),
        ]
        for brk, says in cases:
            with self.subTest(says=says):
                gaps = xm.instrument_gaps(self.inst(brk))
                self.assertTrue(gaps, brk)
                self.assertEqual({k for k, _ in gaps}, {"control_hold"}, gaps)
                self.assertIn(says, "; ".join(why for _, why in gaps))


# The Replan 3 probe's run2 (measured 2026-10-10 on a throwaway process, not the
# game). Before attach, seven threads switching; at the control's first-hit hold,
# two identical samples per thread of (context switches, state, wait reason,
# suspend count). State 5 is Waiting; wait reason 5 is Suspended, 0 Executive.
# 6320 raised the hardware-breakpoint exception and waits for the debugger's reply.
RUN2_TIDS = [6320, 10656, 11216, 22076, 25024, 31564, 32248]
RUN2_AFTER_ATTACH = {"verdict": "running", "threads": 7, "progress": 85, "suspended": [], "stopped": [],
                     "unreadable_counts": [], "tids": RUN2_TIDS, "executive_waits": []}
RUN2_HELD = {6320: (1717, 5, 0, 1), 31564: (39, 5, 5, 1), 25024: (39, 5, 5, 1), 10656: (40, 5, 5, 1),
             22076: (65, 5, 5, 1), 32248: (78, 5, 5, 1), 11216: (76, 5, 5, 1)}
RUN2_HELD_AT_FIRST_HIT = {
    "verdict": "frozen", "threads": 7, "progress": 0,
    "suspended": [{"tid": t, "suspend_count": 1} for t in RUN2_TIDS],
    "stopped": [t for t in RUN2_TIDS if t != 6320], "unreadable_counts": [], "tids": RUN2_TIDS}


class BreakingThreadTests(unittest.TestCase):
    """At the control hold the thread that raised the hit waits in an Executive
    wait, not Suspended, so `stopped` leaves it out: it is the one exemption,
    on its signature (suspended, the only expected Executive wait), recorded as
    `control_hold.breaking_tid`."""

    @staticmethod
    def hold(**second):
        """The outside check over the run2 held samples, read by thread_state's own
        rules; `second` replaces a thread's reading (key `t<tid>`) in the second
        sample, or in both when the value is a pair of readings."""
        from tools import thread_state as ts
        samples = [[], []]
        for tid, r in RUN2_HELD.items():
            over = second.get(f"t{tid}", r)
            pair = over if isinstance(over[0], tuple) else (r, over)
            for i in (0, 1):
                samples[i].append(ts.ThreadSample(tid, *pair[i]))
        return ts.classify(4242, samples)

    @staticmethod
    def inst(hold):
        return {"before_attach": RUN2_AFTER_ATTACH, "control_hold": hold, "after_resume": RUN2_AFTER_ATTACH}

    def coverage_gap(self, inst):
        return "; ".join(why for k, why in xm.instrument_gaps(inst) if k == "control_hold" and "tid " in why)

    def test_breaking_thread_run2_replay_is_proven_and_recorded(self):
        hold = {**RUN2_HELD_AT_FIRST_HIT, "executive_waits": [6320]}
        # thread_state's reading of the measured samples is the probe's recorded check
        read = self.hold()
        self.assertEqual({k: read[k] for k in hold}, hold)
        self.assertEqual(xm.instrument_gaps(self.inst(hold)), [])
        rec = xm.instrument_record(self.inst(hold))
        self.assertTrue(rec["proven"], rec)
        self.assertEqual(rec["control_hold"]["breaking_tid"], 6320)
        self.assertIn("6320", rec["note"])
        self.assertIn("breaking thread", rec["note"])
        self.assertNotIn("breaking_tid", hold)  # the check passed in is not changed

    def test_breaking_thread_at_suspend_count_0_is_not_proven(self):
        hold = self.hold(t6320=((1717, 5, 0, 0), (1717, 5, 0, 0)))
        self.assertEqual(hold["verdict"], "frozen", hold)
        self.assertIn("6320", self.coverage_gap(self.inst(hold)))
        rec = xm.instrument_record(self.inst(hold))
        self.assertFalse(rec["proven"], rec)
        self.assertIsNone(rec["control_hold"].get("breaking_tid"), rec)

    def test_breaking_thread_a_second_expected_executive_wait_is_not_proven(self):
        hold = self.hold(t31564=((39, 5, 0, 1), (39, 5, 0, 1)))
        self.assertEqual(hold["executive_waits"], [6320, 31564], hold)
        gap = self.coverage_gap(self.inst(hold))
        self.assertIn("6320", gap)
        self.assertIn("31564", gap)
        self.assertFalse(xm.instrument_record(self.inst(hold))["proven"])
        # The same on a hand-built check: 31564 stopped, yet a second expected
        # Executive wait still leaves the one exemption unclaimed.
        hand = {**RUN2_HELD_AT_FIRST_HIT, "executive_waits": [6320, 31564]}
        self.assertIn("2 expected thread(s)", self.coverage_gap(self.inst(hand)))

    def test_breaking_thread_switching_between_samples_is_not_proven(self):
        hold = self.hold(t6320=(1720, 5, 0, 1))
        self.assertIn("6320", self.coverage_gap(self.inst(hold)))
        self.assertFalse(xm.instrument_record(self.inst(hold))["proven"])

    def test_breaking_thread_needs_the_executive_waits_field(self):
        # A check with no executive_waits (an older or stand-in shape) gets no exemption.
        gap = self.coverage_gap(self.inst(RUN2_HELD_AT_FIRST_HIT))
        self.assertIn("executive_waits", gap)
        self.assertIn("6320", gap)

    def test_breaking_thread_not_in_an_executive_wait_is_not_exempt(self):
        # A missing thread that is suspended but not in the check's executive_waits.
        hold = {**RUN2_HELD_AT_FIRST_HIT, "executive_waits": []}
        self.assertIn("Executive", self.coverage_gap(self.inst(hold)))

    def test_breaking_thread_control_every_thread_stopped_needs_no_exemption(self):
        hold = {**RUN2_HELD_AT_FIRST_HIT, "stopped": RUN2_TIDS, "executive_waits": []}
        rec = xm.instrument_record(self.inst(hold))
        self.assertTrue(rec["proven"], rec)
        self.assertIsNone(rec["control_hold"].get("breaking_tid"))
        self.assertNotIn("note", rec)


class BreakingThreadKeeperTests(SessionMixin, unittest.TestCase):
    """The same exemption through the keeper, on the stand-in's thread-check
    route: `breaking_thread` N makes the first N game threads wait in an
    Executive wait at a break."""

    def test_breaking_thread_keeper_records_the_one_exemption(self):
        cfg, _, _, _, _ = self.start_session(fake={"breaking_thread": 1, "hot": [A]})
        reply = self.first_hit(cfg, A)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["hold_game"]["executive_waits"], [9001], reply)
        inst = xm.read_state(cfg)["instrument"]
        self.assertTrue(inst["proven"], inst)
        self.assertEqual(inst["control_hold"]["breaking_tid"], 9001, inst)
        self.assertIn("9001", inst["note"])
        self.assertIn("9001", xm.Tools(cfg).status()["instrument"]["note"])

    def test_breaking_thread_keeper_two_executive_waits_are_not_proven(self):
        cfg, _, _, _, _ = self.start_session(fake={"breaking_thread": 2, "hot": [A]})
        self.assertTrue(self.first_hit(cfg, A)["ok"])
        inst = xm.read_state(cfg)["instrument"]
        self.assertFalse(inst["proven"], inst)
        self.assertIsNone(inst["control_hold"].get("breaking_tid"), inst)
        self.assertIn("not proven", inst["note"])


class ReleaseTests(SessionMixin, unittest.TestCase):
    """A detach is checked from outside the debugger: every game thread
    running again, or a loud `game-not-released` naming the threads."""

    def test_game_not_released_names_the_threads_and_the_recovery(self):
        cfg, _, _, _, _ = self.start_session(fake={"leak_on_detach": True})
        code, reply = self.detach_cli(cfg)
        self.assertEqual(code, 1, reply)
        self.assertFalse(reply["ok"], reply)
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["detach_confirmed"], state["game_released"]),
                         ("game-not-released", True, False), state)
        self.assertEqual(state["game"]["verdict"], "threads-suspended")
        for word in ("9001", "9002", "hs_stop_game", "force=true", "hs_saves_restore"):
            self.assertIn(word, state["error"])
        self.assertNotIn(state["state"], xm.LIVE_STATES)
        self.assertEqual(xm.Tools(cfg).detach()["reason"], "not_attached")

    def test_game_not_released_control_a_clean_detach_releases_the_game(self):
        cfg, _, _, _, _ = self.start_session()
        self.prove(cfg)
        code, reply = self.detach_cli(cfg)
        self.assertEqual(code, 0, reply)
        self.assertTrue(reply["ok"], reply)
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["game_released"]), ("ended", True), state)
        self.assertEqual(xm.session_summary(cfg)["game_released"], True)


@unittest.skipIf(REAL_OS_SKIP is not None, REAL_OS_SKIP or "")
class RealOsTests(SessionMixin, unittest.TestCase):
    """End to end on the stand-in game's real threads: the fake headless
    suspends them for real at a breaking breakpoint's first-hit hold and
    under `leak_on_detach` (never on attach), and the keeper reads them
    through tools/thread_state.py."""

    def test_real_os_instrument_control_reads_the_first_hit_hold_frozen(self):
        cfg, _, state, _, _ = self.start_session(fake={"real_os": True}, probe=False)
        self.assertEqual(state["state"], "running", state)
        self.assertEqual(state["ready_check"]["verdict"], "running", state)  # attach suspends nothing
        self.assertFalse(state["instrument"]["proven"])
        reply = self.prove(cfg)
        self.assertEqual(reply["hold_game"]["verdict"], "frozen", reply)
        inst = xm.read_state(cfg)["instrument"]
        self.assertEqual([inst[k]["verdict"] for k in ("before_attach", "control_hold", "after_resume")],
                         ["running", "frozen", "running"], inst)
        # The lists at the control hold name the held threads themselves: every
        # stand-in thread suspended and stopped, no count unread.
        brk = inst["control_hold"]
        self.assertEqual(brk["unreadable_counts"], [], brk)
        held = {s["tid"] for s in brk["suspended"]}
        self.assertTrue(set(self.workers) <= held, (self.workers, brk))
        self.assertTrue(set(self.workers) <= set(brk["stopped"]), (self.workers, brk))
        self.assertTrue(set(inst["before_attach"]["tids"]) <= held & set(brk["stopped"]), inst)
        self.assertTrue(inst["proven"], inst)

    def test_real_os_leak_on_detach_is_game_not_released(self):
        cfg, _, _, _, _ = self.start_session(fake={"real_os": True, "leak_on_detach": True}, probe=False)
        code, reply = self.detach_cli(cfg)
        self.assertEqual(code, 1, reply)
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["game_released"]), ("game-not-released", False), state)
        self.assertEqual(state["game"]["verdict"], "threads-suspended", state["game"])
        named = {s["tid"] for s in state["game"]["suspended"]}
        self.assertTrue(set(self.workers[1:]) <= named, (self.workers, state["game"]))
        self.assertNotIn(self.workers[0], named)  # the one left running
        for tid in self.workers[1:]:
            self.assertIn(str(tid), state["error"])

    def test_real_os_clean_detach_releases_the_game(self):
        cfg, _, _, _, _ = self.start_session(fake={"real_os": True}, probe=False)
        self.prove(cfg)
        code, reply = self.detach_cli(cfg)
        self.assertEqual(code, 0, reply)
        state = xm.read_state(cfg)
        self.assertEqual((state["state"], state["game_released"]), ("ended", True), state)
        self.assertEqual(state["game"]["verdict"], "running")


# --- logpoint and command: arming without a pause (real processes) --------

def _hits(cfg, prefix: str) -> int:
    """How many `<prefix> #<n>` hit lines the session log holds."""
    lines = cfg.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return sum(1 for ln in lines if ln.startswith(f"{prefix} #"))


class ArmingMixin(SessionMixin):
    def hits_grow(self, cfg, prefix="hot", wait=1.0) -> bool:
        first = _hits(cfg, prefix)
        time.sleep(wait)
        return _hits(cfg, prefix) > first

    def assert_never_paused(self, plugin, record):
        """Nothing asked x64dbg to pause: no `pause` on stdin, and none of the
        plugin's PauseDebug, run or ExecuteDbgCommand."""
        verbs = [ln.split()[0].lower() for ln in self.stdin_lines(record) if ln.strip()]
        self.assertNotIn("pause", verbs)
        self.assertFalse([n for n in plugin.names() if n in PLUGIN_STATE_CALLS], plugin.names())

    def modes_after_hold(self, record, addr, delay=1.5, **modes):
        """Set the fake headless's `modes` `delay` seconds after the first-hit
        hold that armed `addr` sent its `run` (the stdin line after its end
        marker): whatever they cause then lands in logpoint's verification
        window, after the hold has settled and returned."""
        bph = f"bph 0x{addr:X}, x, 1"

        def run():
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                lines = self.stdin_lines(record)
                if bph in lines:
                    rest = lines[lines.index(bph):]
                    ends = [i for i, ln in enumerate(rest) if ln.endswith(' end"')]
                    if ends and "run" in rest[ends[0]:]:
                        time.sleep(delay)
                        self.set_modes(**modes)
                        return
                time.sleep(0.02)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.addCleanup(t.join, 65)

    def assert_first_hit_hold(self, result, record, addr, *steps):
        """`result` armed `addr` held at its own first hit: `held` is A's
        break, the outside check read the game frozen there and running
        after, and stdin carried `bph <A>, x, 1`, then `steps` and the
        bplist read-back, then `run`."""
        self.assertIn(f"({addr:016X})", result["held"] or "", result)
        self.assertEqual(result["hold_game"]["verdict"], "frozen", result)
        self.assertEqual(result["game"]["verdict"], "running", result)
        sent = _commands(self.stdin_lines(record))
        bph = f"bph 0x{addr:X}, x, 1"
        self.assertEqual(sent[sent.index(bph):], [bph, *steps, "bplist", "run"])


class NeverPausesTests(ArmingMixin, unittest.TestCase):
    """`logpoint` arms on the running game and teardown clears it, and none
    of them asks x64dbg or the plugin to pause."""

    def test_never_pauses_control_candidate_and_teardown(self):
        cfg, plugin, _, record, _ = self.start_session(fake={"hot": [A]})
        tools = xm.Tools(cfg)
        control = tools.logpoint(f"0x{A:X}", "hot")
        self.assertTrue(control["ok"], control)
        self.assertIn(f"({A:016X})", control["held"] or "", control)  # held at its own first hit
        self.assertTrue(self.hits_grow(cfg), "the hot logpoint never logged")
        held = tools.logpoint(f"0x{B:X}", "second")
        self.assertTrue(held["ok"], held)
        self.assertIn(f"({A:016X})", held["held"] or "", held)
        _, reply = self.detach_cli(cfg)
        self.assertEqual((reply["state"], reply["detach_confirmed"]), ("ended", True), reply)
        self.assert_never_paused(plugin, record)
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], 0)  # every pause was a hold's own

    def test_never_pauses_control_the_plugins_pause_lands_late_and_only_the_watchdog_resumes_it(self):
        # The stand-in's PauseDebug can represent Live 2's failure: it answers
        # "settling", and the break lands seconds later, with nothing but the
        # keeper's watchdog there to resume it.
        cfg, plugin, _, record, _ = self.start_session()
        runs = self.stdin_lines(record).count("run")
        text, _ = xm.PluginClient(cfg.url).call_checked(xm.PLUGIN_PAUSE)
        self.assertIn("settling", text)
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], 0)  # not yet: the pause is asynchronous
        later = self.wait_for(cfg, lambda s: s.get("breaks_resumed") == 1 and s.get("x64dbg_state") == "running")
        self.assertEqual(later["breaks_resumed"], 1, later)
        self.assertEqual(later["last_break"]["line"], "paused!", later)
        self.assertEqual(self.stdin_lines(record).count("run"), runs + 1)
        self.assertIn(xm.PLUGIN_PAUSE, plugin.names())


class FirstHitHoldTests(ArmingMixin, unittest.TestCase):
    """With nothing armed, `logpoint` arms its breakpoint breaking, holds the
    game at its own first hit, and sets the rest there: the control's hold
    is also the instrument's frozen reading."""

    def test_first_hit_hold_arms_the_control_held_at_its_own_first_hit(self):
        cfg, plugin, _, record, _ = self.start_session(fake={"hot": [A]})
        self.assertFalse(xm.read_state(cfg)["instrument"]["proven"])  # attach holds nothing
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hot", name="control")
        self.assertTrue(result["ok"], result)
        self.assert_first_hit_hold(result, record, A, f"SetHardwareBreakpointCondition 0x{A:X}, 0",
                                   f'SetHardwareBreakpointLog 0x{A:X}, "hot"',
                                   f'SetHardwareBreakpointName 0x{A:X}, "control"')
        self.assertNotIn("held_note", result)
        self.assertEqual(result["x64dbg_state"], "running")
        self.assertEqual(result["bplist"], [f'1:HW:{A:016X}:"control"'])
        inst = xm.read_state(cfg)["instrument"]
        self.assertTrue(inst["proven"], inst)  # the hold was the frozen control reading
        self.assertEqual(inst["control_hold"]["verdict"], "frozen", inst)
        self.assertTrue(self.hits_grow(cfg), "the control never logged after its hold")
        self.assert_never_paused(plugin, record)
        self.assertEqual(xm.read_state(cfg)["breaks_resumed"], 0)  # the hold's pause was its own

    def test_first_hit_hold_control_a_cold_address_is_armed_never_break_and_proves_nothing(self):
        cfg, plugin, _, record, _ = self.start_session(cfg_over={"hold_timeout": 2})
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "cold")
        self.assertTrue(result["ok"], result)
        self.assertIsNone(result["held"], result)
        self.assertIn("no hit within", result["held_note"])
        self.assertNotIn("hold_game", result)
        sent = _commands(self.stdin_lines(record))
        bph = f"bph 0x{A:X}, x, 1"
        self.assertEqual(sent[sent.index(bph):], [bph, f"SetHardwareBreakpointCondition 0x{A:X}, 0",
                                                  f'SetHardwareBreakpointLog 0x{A:X}, "cold"', "bplist"])  # no run
        self.assertFalse(xm.read_state(cfg)["instrument"]["proven"])
        self.assert_never_paused(plugin, record)


class HeldChangeTests(ArmingMixin, unittest.TestCase):
    """With a logpoint logging, a change is made with the game held at one of
    its hits, so it cannot race the debug loop's re-arm."""

    def test_held_change_keeps_a_logging_logpoint_logging(self):
        cfg, plugin, _, record, _ = self.start_session(fake={"race": True, "hot": [A]})
        tools = xm.Tools(cfg)
        self.assertTrue(tools.logpoint(f"0x{A:X}", "hot")["ok"])
        self.assertTrue(self.hits_grow(cfg), "the hot logpoint never logged")
        result = tools.logpoint(f"0x{B:X}", "second", name="second")
        self.assertTrue(result["ok"], result)
        self.assertIn(f"({A:016X})", result["held"] or "", result)
        sent = self.stdin_lines(record)
        held_at = sent.index(f"SetHardwareBreakpointCondition 0x{A:X}, 1")
        self.assertEqual(_commands(sent[held_at:]), [
            f"SetHardwareBreakpointCondition 0x{A:X}, 1",
            f"bph 0x{B:X}, x, 1", f"SetHardwareBreakpointCondition 0x{B:X}, 0",
            f'SetHardwareBreakpointLog 0x{B:X}, "second"', f'SetHardwareBreakpointName 0x{B:X}, "second"',
            f"SetHardwareBreakpointCondition 0x{A:X}, 0", "bplist", "run"])
        self.assertTrue(self.hits_grow(cfg), "the held change silenced the hot logpoint")
        self.assert_never_paused(plugin, record)
        # control: the same lines sent plainly while it logs race it
        xm.keeper_request(cfg, "send", timeout=15, lines=[f"bph 0x{C:X}, x, 1"])
        time.sleep(0.3)
        self.assertFalse(self.hits_grow(cfg), "the stand-in cannot represent the lost DR7 update")

    def test_held_change_command_changes_debug_registers_through_a_hold(self):
        cfg, plugin, _, record, _ = self.start_session(fake={"race": True, "hot": [A]})
        tools = xm.Tools(cfg)
        self.assertTrue(tools.logpoint(f"0x{A:X}", "hot")["ok"])
        self.assertTrue(tools.logpoint(f"0x{B:X}", "second")["ok"])
        self.assertTrue(self.hits_grow(cfg), "the hot logpoint never logged")
        reply = tools.command(f"bphc 0x{B:X}")
        self.assertTrue(reply["ok"], reply)
        self.assertIn(f"({A:016X})", reply["held"] or "", reply)
        self.assertIn("Hardware breakpoint deleted!", reply["lines"])
        self.assertIsNone(xm.bplist_entry(reply["after"], B))
        self.assertEqual(reply["x64dbg_state"], "running")
        self.assertTrue(self.hits_grow(cfg), "the held delete silenced the hot logpoint")
        # a list-only verb keeps the direct stdin route: no hold, no condition change
        before = len(self.stdin_lines(record))
        listed = tools.command("bplist")
        self.assertTrue(listed["ok"], listed)
        self.assertNotIn("held", listed)
        self.assertEqual(self.stdin_lines(record)[before:], ["bplist"])
        self.assert_never_paused(plugin, record)


class BreakingBphInLinesTests(ArmingMixin, unittest.TestCase):
    """The shape a stale client sent in Live 3 rerun 3: the breaking `bph`
    among a hold's lines, with no `first_hit`. With nothing armed it goes
    through the first-hit hold anyway, so its first hit is the hold and not a
    stray pause the watchdog resumes."""

    def test_breaking_bph_in_lines_goes_through_the_first_hit_hold(self):
        cfg, _, _, record, _ = self.start_session(fake={"hot": [A]})
        steps = [f"SetHardwareBreakpointCondition 0x{A:X}, 0", f'SetHardwareBreakpointLog 0x{A:X}, "hot"']
        reply = xm.keeper_request(cfg, "hold", timeout=60, lines=[f"bph 0x{A:X}, x, 1", *steps])
        self.assertTrue(reply["ok"], reply)
        self.assertIn(f"({A:016X})", reply["held"] or "", reply)  # held at its own first hit
        self.assertEqual(reply["hold_game"]["verdict"], "frozen", reply)
        self.assertEqual(reply["game"]["verdict"], "running", reply)
        sent = _commands(self.stdin_lines(record))
        bph = f"bph 0x{A:X}, x, 1"
        self.assertEqual(sent[sent.index(bph):], [bph, *steps, "bplist", "run"])
        state = xm.read_state(cfg)
        self.assertEqual(state["breaks_resumed"], 0, state)  # the first hit was the hold's, not a stray pause
        self.assertTrue(state["instrument"]["proven"], state["instrument"])
        self.assertTrue(self.hits_grow(cfg), "the logpoint never logged after its hold")

    def test_breaking_bph_in_lines_control_a_batch_without_bph_stays_direct(self):
        cfg, _, _, record, _ = self.start_session(fake={"hot": [A]})
        reply = xm.keeper_request(cfg, "hold", timeout=60, lines=["bphc"])
        self.assertTrue(reply["ok"], reply)
        self.assertIsNone(reply["held"], reply)
        self.assertNotIn("held_note", reply)
        self.assertNotIn("hold_game", reply)
        self.assertNotIn("run", _commands(self.stdin_lines(record)))  # nothing held, nothing to resume


EXCEPTION_LINE = f"First chance exception on {A:016X} (80000004, EXCEPTION_SINGLE_STEP)!"
TODO_LINE = "[TODO] Not implemented GUI_SET_LAST_EXCEPTION (37)"


class ExceptionHoldTests(ArmingMixin, unittest.TestCase):
    """x64dbg can report a hardware execute hit as a first-chance single-step
    exception (Live 3 rerun 3): its GUI_SET_LAST_EXCEPTION notice, the pause,
    then `First chance exception on <A> ...` and only then `set!`. The
    first-hit hold claims that pause, names the exception line as its break
    line, and never the [TODO] notice."""

    def test_exception_hold_claims_the_exception_shaped_first_hit(self):
        cfg, plugin, _, record, _ = self.start_session(fake={"hot": [A], "exception_hold": True})
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hot")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["held"], EXCEPTION_LINE, result)
        self.assertEqual(result["hold_game"]["verdict"], "frozen", result)
        self.assertEqual(result["game"]["verdict"], "running", result)
        log = self.log_lines(cfg)
        self.assertLess(log.index(TODO_LINE), log.index("[STATE] paused"))  # the stand-in printed the shape
        self.assertLess(log.index(EXCEPTION_LINE), log.index(f"Hardware breakpoint at {A:016X} set!"))
        sent = _commands(self.stdin_lines(record))
        bph = f"bph 0x{A:X}, x, 1"
        self.assertEqual(sent[sent.index(bph):], [bph, f"SetHardwareBreakpointCondition 0x{A:X}, 0",
                                                  f'SetHardwareBreakpointLog 0x{A:X}, "hot"', "bplist", "run"])
        state = xm.read_state(cfg)
        self.assertEqual(state["breaks_resumed"], 0, state)  # the hold claimed it: no stray pause
        self.assertIsNone(state["last_break"], state)
        self.assertTrue(state["instrument"]["proven"], state["instrument"])
        self.assertTrue(self.hits_grow(cfg), "the logpoint never logged after its hold")
        self.assert_never_paused(plugin, record)

    def test_exception_hold_settles_a_stray_pause_before_the_bph(self):
        # A pause already pending when the hold starts (here, right after its
        # bplist) is resumed and counted before the `bph`, so it is not taken
        # for the first hit.
        cfg, _, _, record, _ = self.start_session(fake={"hot": [A]})
        self.set_modes(break_after="bplist")
        reply = self.first_hit(cfg, A)
        self.assertTrue(reply["ok"], reply)
        self.assertIn(f"({A:016X})", reply["held"] or "", reply)
        state = xm.read_state(cfg)
        self.assertEqual(state["breaks_resumed"], 1, state)
        self.assertEqual(state["last_break"]["line"], "paused!", state)
        sent = _commands(self.stdin_lines(record))
        self.assertIn("run", sent[:sent.index(f"bph 0x{A:X}, x, 1")])

    def test_exception_hold_session_log_never_takes_the_todo_line_as_a_break_line(self):
        tmp = Path(tempfile.mkdtemp(prefix="x64dbg-mcp-log-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "session.log"
        log = xm.SessionLog(path)

        def write(*lines):
            with open(path, "a", encoding="utf-8") as f:
                f.write("".join(f"{ln}\n" for ln in lines))
            log.poll()

        write("x64dbg_mcp 1234 begin", TODO_LINE, "[STATE] paused")
        self.assertNotEqual((log.pause_line() or {}).get("line"), TODO_LINE)
        write("[STATE] paused", "x64dbg_mcp 1234 begin", EXCEPTION_LINE, f"Hardware breakpoint at {A:016X} set!")
        self.assertEqual(log.pause_line()["line"], EXCEPTION_LINE)  # filled in once x64dbg prints it
        # control: a hardware breakpoint line before the pause is the break line, as before
        write("[STATE] running", f"Hardware breakpoint (byte, execute) at x ({A:016X})!", "[STATE] paused")
        self.assertEqual(log.pauses, 2)
        self.assertEqual(log.pause_line()["line"], f"Hardware breakpoint (byte, execute) at x ({A:016X})!")
        # a notice with no exception line after it leaves no break line rather than the notice
        write("[STATE] running", "hot #1", TODO_LINE, "[STATE] paused")
        self.assertIsNone(log.pause_line()["line"])


class PausedFirstRunTests(ArmingMixin, unittest.TestCase):
    """The first hit is the expected hold. A never-break condition that did
    not take shows as a break on a hit after it: in the verification window
    after the hold returned, or while the hold settled. Either way it is
    cleared and the game resumed."""

    def test_paused_first_run_a_break_in_the_verification_window_is_cleared(self):
        cfg, plugin, _, record, _ = self.start_session(cfg_over={"settle": 3.0}, fake={"hot": [A]})
        # the hold itself sets the condition; it stops taking only after the hold's run
        self.modes_after_hold(record, A, condition_ignored=True)
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "running")
        self.assertIn("never-break condition did not take", result["detail"])
        self.assertIn(f"{A:016X}", result["detail"])
        self.assertIn("Hardware breakpoint deleted!", result["cleared"])
        self.assertEqual(result["x64dbg_state"], "running")
        self.assertIsNone(xm.bplist_entry(xm.Tools(cfg).bplist()["lines"], A))
        self.assertEqual(self.wait_for(cfg, lambda s: s.get("x64dbg_state") == "running")["x64dbg_state"], "running")
        self.assert_never_paused(plugin, record)

    def test_paused_first_run_a_breakpoint_that_keeps_breaking_after_its_first_hit_is_cleared(self):
        cfg, plugin, _, record, _ = self.start_session(cfg_over={"hold_timeout": 2},
                                                       fake={"condition_ignored": True, "hot": [A]})
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertFalse(result["ok"], result)
        self.assertIn(f"({A:016X})", result["held"] or "", result)  # the first hit held it, as intended
        # It then breaks on every hit after the hold's run. Whether the hold's
        # settle saw 0.4 s of running between two breaks depends on how the
        # stand-in is scheduled (on a loaded machine it can), and the outside
        # check then reads the game held, or the verification window sees the
        # next break: either way the arming failed and is cleared.
        self.assertIn(result["stage"], ("running", "game-not-running"), result)
        self.assertIn("Hardware breakpoint deleted!", result["cleared"])
        self.assertEqual(result["x64dbg_state"], "running")
        self.assertIsNone(xm.bplist_entry(xm.Tools(cfg).bplist()["lines"], A))
        self.assert_never_paused(plugin, record)

    def test_paused_first_run_control_a_logging_breakpoint_passes_the_window(self):
        cfg, _, _, record, _ = self.start_session(cfg_over={"settle": 1.5}, fake={"hot": [A]})
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertTrue(result["ok"], result)
        self.assertIn(f"({A:016X})", result["held"] or "", result)
        self.assertTrue(self.hits_grow(cfg, prefix="hit"), "the logpoint never logged")


class FalseSuccessTests(ArmingMixin, unittest.TestCase):
    # The failure cases arm a breakpoint nothing hits: a cold address, armed
    # after the first-hit wait, kept short here.
    COLD = {"hold_timeout": 2}

    def test_false_success_control_a_breakpoint_x64dbg_lists_is_ok(self):
        cfg, plugin, _, record, _ = self.start_session(fake={"hot": [A]})
        result = xm.Tools(cfg).logpoint("Hero_Siege.exe+427460", "hit rcx={rcx} rdx={rdx}", name="control",
                                        expect_bytes="48 89 54 24 10 53")
        self.assertTrue(result["ok"], result)
        addr = f"0x{A:X}"
        self.assertEqual(result["address"], addr)
        self.assertTrue(result["bytes_checked"])
        self.assertTrue(result["bytes"].startswith("48 89 54 24 10 53 48 83 EC 30"), result["bytes"])
        steps = [f"bph {addr}, x, 1", f"SetHardwareBreakpointCondition {addr}, 0",
                 f'SetHardwareBreakpointLog {addr}, "hit rcx={{rcx}} rdx={{rdx}}"',
                 f'SetHardwareBreakpointName {addr}, "control"']
        self.assertEqual(result["steps"], steps)
        self.assert_first_hit_hold(result, record, A, *steps[1:])  # the condition first, while held
        self.assertEqual(result["bplist"], [f'1:HW:{A:016X}:"control"'])
        self.assertNotIn("window_break", result)  # the first hit is the expected hold, not an anomaly
        self.assertEqual((result["x64dbg_state"], result["game"]["verdict"]), ("running", "running"))
        names = plugin.names()
        self.assertLess(names.index(xm.PLUGIN_MODULES), names.index(xm.PLUGIN_DISASM))
        self.assert_never_paused(plugin, record)

    def test_false_success_without_expect_bytes_says_a_zero_is_not_evidence(self):
        cfg, _, _, _, _ = self.start_session(cfg_over=self.COLD)
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["bytes_checked"])
        self.assertIn("not evidence", result["note"])

    def test_false_success_refuses_an_address_whose_bytes_differ_from_ghidra(self):
        cfg, plugin, _, record, _ = self.start_session()
        attached = len(self.stdin_lines(record))  # the attach and its defensive clear
        # Ghidra's copy starts differently: a stale address, or one mid-instruction
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit", expect_bytes="48 8B 05 00")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "bytes_mismatch")
        self.assertIn("never fires", result["detail"])
        self.assertEqual(result["bytes"][:14], "48 89 54 24 10")
        self.assertEqual(self.stdin_lines(record)[attached:], [])  # nothing reached x64dbg
        self.assert_never_paused(plugin, record)

    def test_false_success_an_address_bplist_lists_already_is_refused(self):
        cfg, _, _, record, _ = self.start_session(cfg_over=self.COLD)
        tools = xm.Tools(cfg)
        self.assertTrue(tools.logpoint(f"0x{A:X}", "hit")["ok"])
        again = tools.logpoint(f"0x{A:X}", "hit")
        self.assertEqual(again["reason"], "already_armed", again)
        self.assertEqual(self.stdin_lines(record).count(f"bph 0x{A:X}, x, 1"), 1)  # nothing set again
        self.assertEqual(xm.bplist_entry(tools.bplist()["lines"], A), "armed")  # and nothing cleared

    def test_false_success_a_breakpoint_listed_but_disabled_is_not_ok(self):
        cfg, plugin, _, record, _ = self.start_session(cfg_over=self.COLD, fake={"listed_as": [0, "HW"]})
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "listed-but-disabled")
        self.assertIn("listed but disabled", result["detail"])
        self.assertIn("Hardware breakpoint deleted!", result["cleared"])
        self.assertEqual(_commands(self.stdin_lines(record))[-2:], [f"bphc 0x{A:X}", "bplist"])
        self.assertEqual(result["x64dbg_state"], "running")
        self.assert_never_paused(plugin, record)

    def test_false_success_a_rejected_never_break_condition_is_not_ok(self):
        cfg, plugin, _, record, _ = self.start_session(cfg_over=self.COLD, fake={"fail_condition": True})
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "set")
        self.assertIn("Can't set break condition", result["detail"])
        self.assertIn("Hardware breakpoint deleted!", result["cleared"])
        self.assertIn(f"bphc 0x{A:X}", self.stdin_lines(record))
        self.assertEqual(result["x64dbg_state"], "running")
        self.assert_never_paused(plugin, record)

    def test_false_success_a_breakpoint_x64dbg_reported_set_and_never_listed_is_not_ok(self):
        cfg, plugin, _, record, _ = self.start_session(cfg_over=self.COLD, fake={"false_success": True})
        result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "set")
        # x64dbg said it was set, then named no such breakpoint for each step
        # after (with no row to show, the bplist branch is pinned by shape below)
        self.assertIn(f"Hardware breakpoint at {A:016X} set!", result["lines"])
        self.assertIn(f'No such breakpoint "0x{A:X}"', result["detail"])
        self.assertIn(f"bphc 0x{A:X}", self.stdin_lines(record))
        self.assertEqual(result["x64dbg_state"], "running")
        self.assert_never_paused(plugin, record)

    def test_false_success_a_game_the_outside_check_reads_held_is_not_ok(self):
        cfg, _, _, record, _ = self.start_session(cfg_over=self.COLD)
        held = {"verdict": "frozen", "detail": "stand-in: no thread made progress", "suspended": [], "stopped": []}
        with mock.patch.object(xm, "game_check", return_value=held):
            result = xm.Tools(cfg).logpoint(f"0x{A:X}", "hit")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "game-not-running")
        self.assertEqual(result["game"]["verdict"], "frozen")
        self.assertIn("Hardware breakpoint deleted!", result["cleared"])
        self.assertIn(f"bphc 0x{A:X}", self.stdin_lines(record))

    def test_false_success_arming_failure_reads_the_hold_reply(self):
        set_line, row = f"Hardware breakpoint at {A:016X} set!", f"1:HW:{A:016X}"
        self.assertIsNone(xm.arming_failure({"lines": [set_line], "after": [row]}, A, None))
        self.assertIsNone(xm.arming_failure({"lines": [set_line, "hot #3"], "after": [f'{row}:"ctl"']}, A, "ctl"))
        cases = [
            ("set", {"lines": [set_line, f'Can\'t set log text on breakpoint "0x{A:X}"'], "after": [row]}, None),
            ("set", {"lines": ["You can only set 4 hardware breakpoints"], "after": []}, None),
            ("set", {"lines": ["Hardware breakpoint already set!"], "after": [row]}, None),
            ("set", {"lines": [set_line, f'No such breakpoint "0x{A:X}"'], "after": [row]}, None),
            ("set", {"lines": [set_line, "Not enough arguments!"], "after": [row]}, None),
            ("set", {"lines": [], "after": [row]}, None),  # x64dbg never said it was set
            ("set", {"lines": [f"Hardware breakpoint at {A + 1:016X} set!"], "after": [row]}, None),
            ("set", {"lines": [set_line], "after": []}, None),
            ("set", {"lines": [set_line], "after": [f"1:BP:{A:016X}"]}, None),
            ("set", {"lines": [set_line], "after": [row]}, "ctl"),  # the name is missing
            ("set", {"lines": [set_line], "after": [f'1:HW:{A + 1:016X}:"ctl"', row]}, "ctl"),
            ("listed-but-disabled", {"lines": [set_line], "after": [f"0:HW:{A:016X}"]}, None),
        ]
        for stage, reply, name in cases:
            with self.subTest(reply=reply, name=name):
                failure = xm.arming_failure(reply, A, name)
                self.assertIsNotNone(failure)
                self.assertEqual(failure[0], stage, failure)

    def test_false_success_break_on_needs_a_break_naming_it_then_a_pause(self):
        brk = f"Hardware breakpoint (byte, execute) at hero_siege.exe+427460 ({A:016X})!"
        named = 'Hardware breakpoint (byte, execute) "ctl" at hero_siege.exe+427460!'
        self.assertEqual(xm.break_on(["hit #1", brk, "[STATE] paused"], A, None), brk)
        self.assertEqual(xm.break_on([named, "[STATE] paused"], A, "ctl"), named)
        for lines in ([brk], [brk, "[STATE] running"], ["paused!", "[STATE] paused"],
                      [f"Hardware breakpoint (byte, execute) at x+1 ({A + 1:016X})!", "[STATE] paused"],
                      [f"hit {A:016X}", "[STATE] paused"], [brk, "[STATE] running", "[STATE] paused"]):
            with self.subTest(lines=lines):
                self.assertIsNone(xm.break_on(lines, A, None))

    def test_false_success_silent_step_replies_by_shape(self):
        cmd = 'SetHardwareBreakpointName 0x1, "a"'
        # Success: what the pinned plugin returns when x64dbg printed nothing,
        # plus the two blank forms its ExecuteDbgCommand could give.
        for ok in (f"Result: {xm.PLUGIN_EXEC_SILENT_OK}", "Command 'SetHardwareBreakpointName 0x1, \"a\"' "
                   "executed successfully.", "Result:", "", f"  Result: {xm.PLUGIN_EXEC_SILENT_OK}\r\n"):
            self.assertTrue(xm.silent_reply_ok(ok, cmd), ok)
        # Failure: anything x64dbg printed, and the plugin's own could-not-queue reply.
        for bad in (f"Result: {xm.PLUGIN_EXEC_FAILED}", "Result: Can't set break condition on breakpoint \"0x1\"",
                    f"Result: {xm.PLUGIN_EXEC_SILENT_OK}\nCan't set log text", "Result: Command executed"):
            self.assertFalse(xm.silent_reply_ok(bad, cmd), bad)

    def test_false_success_live_set_reply_carrying_the_plugin_echo_is_ok(self):
        # Live 1 (2026-10-10), verbatim: the pinned plugin's reply to a Set*
        # step x64dbg printed nothing for. The plugin writes its own echo of
        # the call to x64dbg's log, and its capture of that log while the
        # command runs picks the echo up. x64dbg logged no error after it.
        cmd = 'SetHardwareBreakpointLog 0x7FF613D47460, "ctu #{d:$breakpointcounter} self={rcx} other={rdx} argc={d:r9d}"'
        live = ("Result: ----------------------------------------\r\nMETHOD: ExecuteDbgCommand\r\n"
                f"command: {cmd}\r\n----------------------------------------\r\nExecuting DbgCmdExec: {cmd}")
        self.assertTrue(xm.silent_reply_ok(live, cmd))
        # live 1's bphc reply carried only the echo's last line: any tail of it is the echo
        self.assertTrue(xm.silent_reply_ok(f"Result: Executing DbgCmdExec: {cmd}", cmd))
        self.assertTrue(xm.silent_reply_ok("Result: " + live.split("\r\n", 1)[1], cmd))  # from METHOD on
        # Negative controls: an x64dbg line after the echo is the command's
        # failure, and so is an echo that is not this command's, out of
        # order, or the no-output text beside a capture.
        for bad in (live + "\r\nInvalid address \"0x7FF613D47460\"",
                    live + "\r\nCan't set log text on hardware breakpoint",
                    live.replace("0x7FF613D47460", "0x7FF613D47461"),
                    f"Result: Executing DbgCmdExec: {cmd}\r\nMETHOD: ExecuteDbgCommand",
                    f"Result: Executing DbgCmdExec: {cmd}\r\n{xm.PLUGIN_EXEC_SILENT_OK}",
                    "Result: Executing DbgCmdExec: bphc 0x7FF613D47460",
                    f"Result: ctu #12 self=1 other=1 argc=3\r\nExecuting DbgCmdExec: {cmd}"):
            self.assertFalse(xm.silent_reply_ok(bad, cmd), bad)

    def test_false_success_bplist_rows_by_enabled_flag_and_type(self):
        a = 0x7FF6A0427460
        self.assertEqual(xm.bplist_entry([f"1:HW:{a:016X}"], a), "armed")
        self.assertEqual(xm.bplist_entry([f'1:HW:{a:016X}:"control"'], a), "armed")
        self.assertEqual(xm.bplist_entry([f"0:HW:{a:016X}"], a), "disabled")
        self.assertEqual(xm.bplist_entry([f"1:BP:{a:016X}"], a), "BP")
        self.assertIsNone(xm.bplist_entry([f"1:HW:{a + 1:016X}", "hit 42"], a))

    def test_false_success_listing_bytes_run_from_the_address_without_a_gap(self):
        a = 0x7FF6A0427460
        listing = (f"header\nsome_label:\n{a:016X}  48-89-54-24-10        mov\n{a + 5:016X}  53                    push\n"
                   f"{a + 9:016X}  90                    nop\n; Byte read limit (16) reached\n")
        self.assertEqual(xm.listing_bytes(listing, a), bytes.fromhex("48 89 54 24 10 53"))  # stops at the gap
        self.assertEqual(xm.listing_bytes(listing, a + 1), b"")  # no row starts there


# --- the CLI `tool` route ---------------------------------------------------

class CliToolTests(unittest.TestCase):
    """`py -3 -m tools.x64dbg_mcp tool <name> [<json>]`: the eight tools for an
    operator whose session has not loaded the MCP server, through the same
    `Tools` methods and gates."""

    def run_tool(self, *args):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = dict(os.environ, HS_X64DBG_MCP_SESSION=str(Path(tmp.name) / "session"),
                   HS_X64DBG_MCP_PORT="1", HS_DRIVE_LEASE_DIR=str(Path(tmp.name) / "lease"))
        return subprocess.run([sys.executable, "-m", "tools.x64dbg_mcp", "tool", *args], cwd=str(ROOT),
                              capture_output=True, text=True, env=env, timeout=60, **NO_WINDOW)

    def test_cli_tool_prints_the_reply_as_json_and_exits_by_ok(self):
        s = self.run_tool("status")
        self.assertEqual(s.returncode, 0, s.stdout + s.stderr)
        reply = json.loads(s.stdout)
        self.assertEqual((reply["ok"], reply["state"]), (True, "none"), reply)
        # the same gate as the MCP tool: no session, so refused, exit 1
        m = self.run_tool("modules")
        self.assertEqual(m.returncode, 1, m.stdout + m.stderr)
        self.assertEqual(json.loads(m.stdout)["reason"], "not_attached")
        c = self.run_tool("command", '{"command": "StopDebug"}')
        self.assertEqual(c.returncode, 1, c.stdout + c.stderr)
        self.assertEqual(json.loads(c.stdout)["reason"], "not_allowed")
        lg = self.run_tool("log", '{"after": 0, "limit": 5}')
        self.assertEqual(lg.returncode, 0, lg.stdout + lg.stderr)
        self.assertEqual(json.loads(lg.stdout)["total"], 0)

    def test_cli_tool_refuses_a_name_outside_the_eight(self):
        for name in ("StopDebug", "keeper", "serve"):
            with self.subTest(name=name):
                r = self.run_tool(name)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                for tool in xm.LIVE_OPERATOR_TOOLS:
                    self.assertIn(tool, r.stdout + r.stderr)

    def test_cli_tool_refuses_arguments_that_are_not_a_json_object(self):
        for arg in ("[1]", "not json", '"after"', "3"):
            with self.subTest(arg=arg):
                r = self.run_tool("log", arg)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("JSON object", r.stdout + r.stderr)

    def test_cli_tool_refuses_an_argument_the_tool_does_not_take(self):
        r = self.run_tool("status", '{"verbose": true}')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("verbose", r.stdout + r.stderr)
        # a required argument left out is refused the same way, before the gate
        r = self.run_tool("logpoint", '{"log": "x"}')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("address", r.stdout + r.stderr)

    def test_cli_tool_refuses_an_argument_of_the_wrong_type(self):
        # the name binds, the value does not: exit 2 naming it, not a traceback
        for arg in ('{"after": "x"}', '{"limit": [1]}'):
            with self.subTest(arg=arg):
                r = self.run_tool("log", arg)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertIn("log", r.stderr)
        # control: the right type is served
        r = self.run_tool("log", '{"after": "0"}')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# --- wiring -----------------------------------------------------------------

class WiringTests(unittest.TestCase):
    def test_mcp_json_entry_is_the_stdio_launcher_not_a_url(self):
        servers = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(servers["x64dbg"], {"command": "py", "args": ["-3", "-m", "tools.x64dbg_mcp"]})
        self.assertNotIn("url", servers["x64dbg"])
        # control: the ghidra entry this one is modelled on
        self.assertEqual(servers["ghidra"]["args"][:2], ["-3", "-m"])

    def test_mcp_json_codex_entry_matches(self):
        import tomllib
        codex = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
        self.assertEqual(codex["x64dbg"]["command"], "py")
        self.assertEqual(codex["x64dbg"]["args"], ["-3", "-m", "tools.x64dbg_mcp"])
        self.assertNotIn("url", codex["x64dbg"])


# --- the stdio round trip ---------------------------------------------------

def _stdio_skip_reason():
    try:
        import mcp  # noqa: F401
        from mcp.client.stdio import stdio_client  # noqa: F401
    except ImportError as exc:
        return f"{exc.name} is not installed; run `py -3 -m pip install -r tools/hs_drive_mcp/requirements.txt`"
    return None


STDIO_SKIP = _stdio_skip_reason()


async def _stdio_session(env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "tools.x64dbg_mcp"], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            listed = await s.list_tools()
            status = await s.call_tool("status", {})
            logpoint = await s.call_tool("logpoint", {"address": "Hero_Siege.exe+427460", "log": "x"})
            command = await s.call_tool("command", {"command": "StopDebug"})
    return {"names": [t.name for t in listed.tools], "status": status.structured_content,
            "logpoint": logpoint.structured_content, "command": command.structured_content}


class StdioTests(unittest.TestCase):
    @unittest.skipIf(STDIO_SKIP is not None, STDIO_SKIP or "")
    def test_stdio_round_trip_serves_exactly_the_eight_tools(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = dict(os.environ, HS_X64DBG_MCP_SESSION=str(Path(tmp.name) / "session"),
                   HS_X64DBG_MCP_PORT="1", HS_DRIVE_LEASE_DIR=str(Path(tmp.name) / "lease"))
        got = asyncio.run(_stdio_session(env))
        self.assertEqual(sorted(got["names"]), sorted(xm.LIVE_OPERATOR_TOOLS))
        self.assertEqual(got["status"]["state"], "none")
        self.assertFalse(got["status"]["plugin_answers"])
        self.assertEqual(got["logpoint"]["reason"], "not_attached")
        self.assertEqual(got["command"]["reason"], "not_allowed")
        self.assertFalse((Path(tmp.name) / "session").exists(), "serve wrote a session without an attach")


if __name__ == "__main__":
    unittest.main()
